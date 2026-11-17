"""지금까지 쌓인 데이터를 SQLite + 로컬 폴더에서 설정된 DB·이미지 저장소로 옮긴다.

옮길 곳은 .env (또는 환경 변수)의 설정을 따른다. 보통은 이렇게 쓴다.
    DOROTHY_DATABASE_URL=postgresql+psycopg://dorothy:dorothy@127.0.0.1:5432/dorothy
    DOROTHY_STORAGE=s3  (+ DOROTHY_S3_* : docker compose 의 RustFS)

    python3 backend/scripts/migrate_storage.py            # 옮기기
    python3 backend/scripts/migrate_storage.py --dry-run  # 무엇을 옮길지만 보기

여러 번 실행해도 된다. 작업과 프리셋은 같은 id 로 덮어쓰고, 이미 있는 이미지는 건너뛴다.
원본(SQLite 파일, outputs 폴더)은 건드리지 않는다.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.presets import PresetStore  # noqa: E402
from app.storage import ImageStorage, LocalStorage, create_storage  # noqa: E402
from app.store import JobStore  # noqa: E402

MEDIA = {"png": "image/png", "webp": "image/webp"}


def migrate(
    src_db: str | pathlib.Path,
    src_images: ImageStorage,
    dst_db: str | pathlib.Path,
    dst_images: ImageStorage,
    dry_run: bool = False,
) -> dict:
    src_jobs, src_presets = JobStore(src_db), PresetStore(src_db)
    dst_jobs, dst_presets = JobStore(dst_db), PresetStore(dst_db)
    stats = {"jobs": 0, "presets": 0, "images": 0, "images_skipped": 0, "images_missing": 0}
    try:
        for preset in src_presets.list():
            if not dry_run:
                dst_presets.put(preset)
            stats["presets"] += 1

        total = src_jobs.count()
        for offset in range(0, total, 200):
            for job in src_jobs.list(limit=200, offset=offset):
                if not dry_run:
                    dst_jobs.save(job)
                stats["jobs"] += 1
                if not job.image_url:
                    continue
                key = job.image_url.rsplit("/", 1)[1]
                if dst_images.exists(key):
                    stats["images_skipped"] += 1
                    continue
                data = src_images.get(key)
                if data is None:
                    stats["images_missing"] += 1
                    continue
                if not dry_run:
                    dst_images.put(key, data, MEDIA[key.rsplit(".", 1)[1]])
                stats["images"] += 1
    finally:
        for store in (src_jobs, src_presets, dst_jobs, dst_presets):
            store.close()
    return stats


def main():
    settings = Settings()
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-db", type=pathlib.Path, default=settings.db_path, help="원본 SQLite 파일")
    ap.add_argument("--from-dir", type=pathlib.Path, default=settings.output_dir, help="원본 이미지 폴더")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not settings.database_url and settings.storage != "s3":
        sys.exit("옮길 곳이 원본과 같다. .env 에 DOROTHY_DATABASE_URL 또는 DOROTHY_STORAGE=s3 를 먼저 설정하자.")

    print(f"DB     : {args.from_db} -> {settings.database_target}")
    print(f"이미지 : {args.from_dir} -> {settings.storage}{' (' + settings.s3_bucket + ')' if settings.storage == 's3' else ''}")
    stats = migrate(args.from_db, LocalStorage(args.from_dir), settings.database_target, create_storage(settings), args.dry_run)
    print(
        f"{'(미리 보기) ' if args.dry_run else ''}작업 {stats['jobs']}개, 프리셋 {stats['presets']}개, "
        f"이미지 {stats['images']}장 옮김 (이미 있음 {stats['images_skipped']}, 원본 없음 {stats['images_missing']})"
    )


if __name__ == "__main__":
    main()
