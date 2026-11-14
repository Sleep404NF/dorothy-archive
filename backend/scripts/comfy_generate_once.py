"""ComfyUI에 워크플로를 한 번 제출하고 결과 이미지를 내려받는 스모크 테스트.

표준 라이브러리만 쓴다. 예:
    python3 backend/scripts/comfy_generate_once.py \
        --workflow workflows/txt2img_sdxl.api.json --out outputs/first.png
"""

import argparse
import json
import pathlib
import time
import urllib.parse
import urllib.request


def call(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://127.0.0.1:8188")
    ap.add_argument("--workflow", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--positive", help="노드 2(긍정 프롬프트) 덮어쓰기")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--free", action="store_true", help="끝난 뒤 ComfyUI 모델을 메모리에서 내림")
    args = ap.parse_args()

    wf = json.loads(pathlib.Path(args.workflow).read_text())
    if args.positive:
        wf["2"]["inputs"]["text"] = args.positive
    if args.seed is not None:
        wf["5"]["inputs"]["seed"] = args.seed

    start = time.time()
    prompt_id = json.loads(call(f"{args.host}/prompt", {"prompt": wf}))["prompt_id"]
    print("queued", prompt_id, flush=True)

    while True:
        entry = json.loads(call(f"{args.host}/history/{prompt_id}")).get(prompt_id)
        if entry and entry.get("status", {}).get("completed"):
            break
        if entry and entry.get("status", {}).get("status_str") == "error":
            raise SystemExit(json.dumps(entry["status"], ensure_ascii=False, indent=2))
        if time.time() - start > args.timeout:
            raise SystemExit("timeout")
        time.sleep(2)

    image = next(img for node in entry["outputs"].values() for img in node.get("images", []))
    query = urllib.parse.urlencode(image)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(call(f"{args.host}/view?{query}"))
    print(f"saved {out} ({time.time() - start:.0f}s)")

    if args.free:
        call(f"{args.host}/free", {"unload_models": True, "free_memory": True})
        print("freed ComfyUI models")


if __name__ == "__main__":
    main()
