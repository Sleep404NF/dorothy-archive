from __future__ import annotations

import asyncio
import copy
import json
import pathlib
import time
import uuid

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from .base import GeneratedImage, GenerationParams, ImageBackend, ProgressFn


class ComfyUIBackend(ImageBackend):
    """로컬 ComfyUI 서버에 API 형식 워크플로를 제출한다.

    워크플로의 노드 번호는 workflows/txt2img_sdxl.api.json 기준:
    1 체크포인트, 2 긍정, 3 부정, 4 빈 latent, 5 KSampler.

    진행률은 ComfyUI 웹소켓(/ws?clientId=...)의 progress 메시지로 받는다.
    웹소켓에 붙지 못하거나 중간에 끊기면 진행률 없이 /history 폴링으로 끝까지 기다린다.
    """

    name = "comfyui"
    uses_local_memory = True

    def __init__(self, host: str, workflow_path: pathlib.Path, checkpoint: str | None = None, timeout: float = 1800):
        self._host = host.rstrip("/")
        self._client = httpx.AsyncClient(base_url=host, timeout=30)
        self._workflow = json.loads(workflow_path.read_text())
        self._checkpoint = checkpoint
        self._timeout = timeout

    def _build(self, p: GenerationParams) -> dict:
        wf = copy.deepcopy(self._workflow)
        if self._checkpoint:
            wf["1"]["inputs"]["ckpt_name"] = self._checkpoint
        wf["2"]["inputs"]["text"] = p.positive
        wf["3"]["inputs"]["text"] = p.negative
        wf["4"]["inputs"].update(width=p.width, height=p.height)
        wf["5"]["inputs"].update(seed=p.seed, steps=p.steps, cfg=p.cfg)
        return wf

    async def generate(self, params: GenerationParams, on_progress: ProgressFn | None = None) -> GeneratedImage:
        client_id = uuid.uuid4().hex
        ws = await self._connect_ws(client_id) if on_progress else None
        try:
            res = await self._client.post("/prompt", json={"prompt": self._build(params), "client_id": client_id})
            if res.status_code != 200:
                raise RuntimeError(f"ComfyUI rejected the workflow: {res.text}")
            prompt_id = res.json()["prompt_id"]
            deadline = time.monotonic() + self._timeout
            if ws is not None:
                try:
                    await self._watch(ws, prompt_id, on_progress, deadline)
                except (ConnectionClosed, OSError):
                    pass  # 웹소켓이 끊겨도 아래 폴링으로 마무리한다.
            entry = await self._wait_history(prompt_id, deadline)
        finally:
            if ws is not None:
                await ws.close()

        image = next(img for node in entry["outputs"].values() for img in node.get("images", []))
        view = await self._client.get("/view", params=image)
        view.raise_for_status()
        return GeneratedImage(data=view.content, mime=view.headers.get("content-type", "image/png"))

    async def _connect_ws(self, client_id: str):
        try:
            url = self._host.replace("http://", "ws://").replace("https://", "wss://") + f"/ws?clientId={client_id}"
            return await websockets.connect(url, open_timeout=5, max_size=None)
        except Exception:
            return None

    @staticmethod
    async def _watch(ws, prompt_id: str, on_progress: ProgressFn, deadline: float) -> None:
        """이 프롬프트가 끝날 때까지 웹소켓 메시지를 읽으며 진행률을 알린다."""
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("ComfyUI did not finish in time")
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            if isinstance(raw, bytes):  # 미리보기 이미지 같은 바이너리 메시지는 건너뛴다.
                continue
            message = json.loads(raw)
            kind, data = message.get("type"), message.get("data") or {}
            if data.get("prompt_id") not in (None, prompt_id):
                continue  # 다른 클라이언트의 작업
            if kind == "progress":
                await on_progress(int(data["value"]), int(data["max"]))
            elif kind in ("execution_success", "execution_error", "execution_interrupted"):
                return  # 성공/실패 판정은 /history 가 한다.
            elif kind == "executing" and data.get("node") is None and data.get("prompt_id") == prompt_id:
                return

    async def _wait_history(self, prompt_id: str, deadline: float) -> dict:
        while True:
            entry = (await self._client.get(f"/history/{prompt_id}")).json().get(prompt_id)
            status = (entry or {}).get("status", {})
            if status.get("completed"):
                break
            if status.get("status_str") == "error":
                raise RuntimeError(f"ComfyUI execution failed: {json.dumps(status.get('messages'))}")
            if time.monotonic() > deadline:
                raise TimeoutError(f"ComfyUI did not finish within {self._timeout}s")
            await asyncio.sleep(1)
        return entry

    async def health(self) -> bool:
        try:
            return (await self._client.get("/system_stats", timeout=3)).status_code == 200
        except httpx.HTTPError:
            return False

    async def release(self) -> None:
        res = await self._client.post("/free", json={"unload_models": True, "free_memory": True})
        res.raise_for_status()

    async def close(self) -> None:
        await self._client.aclose()
