"""이미 PNG로 저장된 생성 기록을 WebP로 바꾼다.

생성 기록(DB)에 있는 작업만 바꾸고, 기록의 image_url 도 .webp 로 고친다.
원본 PNG는 기본으로 남겨 두고, --delete-png 를 주면 변환이 끝난 PNG를 지운다.
기록에 없는 파일(first.png 같은 테스트 파일)은 건드리지 않는다.

    python3 backend/scripts/convert_outputs_to_webp.py              # 변환만
    python3 backend/scripts/convert_outputs_to_webp.py --delete-png # 변환 후 PNG 삭제
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.image.encode import encode  # noqa: E402


def convert(db_path: pathlib.Path, output_dir: pathlib.Path, quality: int = 90, delete_png: bool = False) -> dict:
    db = sqlite3.connect(str(db_path), isolation_level=None)
    stats = {"converted": 0, "skipped": 0, "before": 0, "after": 0}
    for job_id, data in db.execute("SELECT id, data FROM jobs").fetchall():
        job = json.loads(data)
        if not (job.get("image_url") or "").endswith(".png"):
            continue
        png = output_dir / f"{job_id}.png"
        if not png.is_file():
            stats["skipped"] += 1
            continue
        raw = png.read_bytes()
        webp, ext = encode(raw, "webp", quality)
        if ext != "webp":
            stats["skipped"] += 1
            continue
        (output_dir / f"{job_id}.webp").write_bytes(webp)
        job["image_url"] = f"/images/{job_id}.webp"
        db.execute("UPDATE jobs SET data = ? WHERE id = ?", (json.dumps(job, ensure_ascii=False), job_id))
        if delete_png:
            png.unlink()
        stats["converted"] += 1
        stats["before"] += len(raw)
        stats["after"] += len(webp)
    db.close()
    return stats


def main():
    settings = Settings()
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=pathlib.Path, default=settings.db_path)
    ap.add_argument("--outputs", type=pathlib.Path, default=settings.output_dir)
    ap.add_argument("--quality", type=int, default=settings.webp_quality)
    ap.add_argument("--delete-png", action="store_true")
    args = ap.parse_args()

    s = convert(args.db, args.outputs, args.quality, args.delete_png)
    mb = lambda n: f"{n / 1024 / 1024:.1f}MB"  # noqa: E731
    print(f"{s['converted']}장 변환 ({mb(s['before'])} -> {mb(s['after'])}), 건너뜀 {s['skipped']}장")
    if s["converted"] and not args.delete_png:
        print("원본 PNG는 남겨 뒀다. 지우려면 --delete-png 를 붙여 다시 실행하면 된다 (이미 바뀐 기록은 다시 바꾸지 않으니 --delete-png 는 처음부터 붙이는 게 낫다).")


if __name__ == "__main__":
    main()
