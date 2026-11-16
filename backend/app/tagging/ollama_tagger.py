"""한국어 요청 → Danbooru 태그 변환 (Ollama).

응답을 받자마자 LLM을 메모리에서 내리도록 keep_alive=0 으로 호출한다.
SDXL과 LLM을 동시에 올리지 않기 위한 장치다.

CLI:
    python3 backend/app/tagging/ollama_tagger.py "벚꽃 아래 교복 입은 소녀"
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import urllib.request
from dataclasses import dataclass, field

FIELDS = ["subject", "character", "appearance", "clothing", "pose_expression", "composition", "background"]
QUALITY_TAGS = ["masterpiece", "best quality", "newest", "absurdres", "highres"]
# "nsfw" 는 여기 넣지 않는다. 요청의 exclude_nsfw 옵션에 따라 파이프라인이 앞에 붙인다.
NSFW_NEGATIVE_TAG = "nsfw"
NEGATIVE_PROMPT = (
    "worst quality, old, early, low quality, lowres, signature, username, logo, "
    "bad hands, mutated hands, watermark, text"
)
SYSTEM_PROMPT_PATH = pathlib.Path(__file__).resolve().parents[3] / "prompts" / "danbooru_tagger.system.md"

SCHEMA = {
    "type": "object",
    "properties": {name: {"type": "array", "items": {"type": "string"}} for name in FIELDS},
    "required": FIELDS,
}


@dataclass
class TagResult:
    request: str
    tags: dict = field(default_factory=dict)
    # 사전·용어집 검증 보고서 (TagRefiner). 검증하지 않았거나 바뀐 게 없으면 None.
    report: dict | None = None

    @property
    def positive(self) -> str:
        seen, ordered = set(), []
        for tag in QUALITY_TAGS + [t for name in FIELDS for t in self.tags.get(name, [])]:
            if tag not in seen:
                seen.add(tag)
                ordered.append(tag)
        return ", ".join(ordered)

    @property
    def negative(self) -> str:
        return NEGATIVE_PROMPT


def _clean(tag: str) -> str | None:
    tag = tag.strip().lower().replace("_", " ")
    tag = re.sub(r"\s+", " ", tag)
    # 태그가 아닌 것(한글, 문장, 빈 값)은 버린다.
    if not tag or not tag.isascii() or len(tag.split()) > 5:
        return None
    if tag in QUALITY_TAGS:
        return None
    # ComfyUI 프롬프트 문법에서 괄호는 가중치라서 이스케이프한다.
    return tag.replace("(", r"\(").replace(")", r"\)")


def to_tags(
    request: str,
    model: str = "gemma3:4b",
    host: str = "http://127.0.0.1:11434",
    keep_alive: int | str = 0,
) -> TagResult:
    payload = {
        "model": model,
        "stream": False,
        "format": SCHEMA,
        "keep_alive": keep_alive,
        "options": {"temperature": 0.2, "num_ctx": 2048},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_PATH.read_text()},
            {"role": "user", "content": f"Request: {request}"},
        ],
    }
    req = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as res:
        raw = json.loads(json.loads(res.read())["message"]["content"])

    tags = {}
    for name in FIELDS:
        values = raw.get(name) or []
        tags[name] = [c for c in (_clean(v) for v in values if isinstance(v, str)) if c]

    # 작은 모델이 자주 틀리는 인원수 태그 보정: "1cat" -> "cat", 대상이 둘 이상이면 "solo" 제거.
    subject = [re.sub(r"^1(?!girl$|boy$|other$)", "", t) for t in tags["subject"]]
    if "no humans" in subject:
        subject = [t for t in subject if not re.match(r"^\d+(girl|boy)s?$|^solo$", t)]
    elif len([t for t in subject if t != "solo"]) > 1:
        subject = [t for t in subject if t != "solo"]
    tags["subject"] = subject
    return TagResult(request=request, tags=tags)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("request")
    ap.add_argument("--model", default="gemma3:4b")
    ap.add_argument("--json", action="store_true", help="필드별 태그를 JSON으로 출력")
    args = ap.parse_args()

    result = to_tags(args.request, model=args.model)
    print(json.dumps(result.tags, ensure_ascii=False) if args.json else result.positive)


if __name__ == "__main__":
    main()
