"""Danbooru 태그 사전을 내려받아 검증용으로 줄인다.

원본: DominikDoom/a1111-sd-webui-tagcomplete 의 tags/danbooru.csv (MIT License)
형식: name,category,post_count,"alias1,alias2,..."

검증에는 작가 태그(category 1)가 필요 없고, 거의 안 쓰이는 태그는 모델도 잘 모르므로
작가 태그를 빼고 사용 횟수가 --min-count 이상인 태그만 남겨 gzip 으로 저장한다.

    python3 backend/scripts/build_tag_dictionary.py
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import pathlib
import urllib.request

SOURCE = "https://raw.githubusercontent.com/DominikDoom/a1111-sd-webui-tagcomplete/main/tags/danbooru.csv"
OUT = pathlib.Path(__file__).resolve().parents[2] / "prompts" / "tags" / "danbooru_tags.csv.gz"
ARTIST = "1"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=SOURCE, help="URL 또는 로컬 CSV 경로")
    ap.add_argument("--out", type=pathlib.Path, default=OUT)
    ap.add_argument("--min-count", type=int, default=50)
    args = ap.parse_args()

    if args.source.startswith("http"):
        with urllib.request.urlopen(args.source, timeout=60) as res:
            text = res.read().decode("utf-8")
    else:
        text = pathlib.Path(args.source).read_text(encoding="utf-8")

    kept = [
        row
        for row in csv.reader(io.StringIO(text))
        if len(row) >= 3 and row[1] != ARTIST and row[2].isdigit() and int(row[2]) >= args.min_count
    ]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.out, "wt", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        for row in kept:
            writer.writerow([row[0], row[1], row[2], row[3] if len(row) > 3 else ""])
    print(f"{len(kept)} tags -> {args.out} ({args.out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
