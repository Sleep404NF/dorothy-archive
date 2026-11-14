from __future__ import annotations

import asyncio
import copy
import json
import pathlib
import time

import httpx

from .base import GeneratedImage, GenerationParams, ImageBackend


class ComfyUIBackend(ImageBackend):
    """로컬 ComfyUI 서버에 API 형식 워크플로를 제출한다.

    워크플로의 노드 번호는 workflows/txt2img_sdxl.api.json 기준:
    1 체크포인트, 2 긍정, 3 부정, 4 빈 latent, 5 KSampler.
    """

    name = "comfyui"
    uses_local_memory = True

    def __init__(self, host: str, workflow_path: pathlib.Path, checkpoint: str | None = None, timeout: float = 1800):
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

    async def generate(self, params: GenerationParams) -> GeneratedImage:
        res = await self._client.post("/prompt", json={"prompt": self._build(params)})
        if res.status_code != 200:
            raise RuntimeError(f"ComfyUI rejected the workflow: {res.text}")
        prompt_id = res.json()["prompt_id"]

        deadline = time.monotonic() + self._timeout
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

        image = next(img for node in entry["outputs"].values() for img in node.get("images", []))
        view = await self._client.get("/view", params=image)
        view.raise_for_status()
        return GeneratedImage(data=view.content, mime=view.headers.get("content-type", "image/png"))

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
