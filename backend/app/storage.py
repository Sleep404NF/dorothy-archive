"""생성 이미지 저장소.

- LocalStorage: outputs/ 폴더 (기본값). Docker 없이 바로 쓸 수 있다.
- S3Storage: S3 호환 오브젝트 스토리지. 로컬 개발은 docker compose 의 RustFS, 나중에는 설정만 바꿔
  Cloudflare R2, Backblaze B2, AWS S3 로 옮길 수 있다.

파일 이름은 "{작업 id}.webp" 처럼 작업마다 고유하고 바뀌지 않는다.
DB 에는 "/images/{이름}" 만 저장하므로, 저장소를 바꿔도 기록은 그대로다.
"""

from __future__ import annotations

import pathlib


class ImageStorage:
    name: str

    def put(self, key: str, data: bytes, content_type: str) -> None:
        raise NotImplementedError

    def get(self, key: str) -> bytes | None:
        """없으면 None."""
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def close(self) -> None:
        pass


class LocalStorage(ImageStorage):
    name = "local"

    def __init__(self, directory: pathlib.Path):
        self.directory = pathlib.Path(directory)

    def path(self, key: str) -> pathlib.Path:
        return self.directory / key

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path(key).write_bytes(data)

    def get(self, key: str) -> bytes | None:
        path = self.path(key)
        return path.read_bytes() if path.is_file() else None

    def exists(self, key: str) -> bool:
        return self.path(key).is_file()


class S3Storage(ImageStorage):
    name = "s3"

    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str = "us-east-1",
        prefix: str = "images/",
        client=None,
        create_bucket: bool = True,
    ):
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
                # RustFS·MinIO 같은 로컬 S3 는 path-style 주소(http://host/bucket/key)를 쓴다.
                config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
            )
        self._s3 = client
        self.bucket = bucket
        self.prefix = prefix
        if create_bucket:
            self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError

        try:
            self._s3.head_bucket(Bucket=self.bucket)
        except ClientError:
            self._s3.create_bucket(Bucket=self.bucket)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._s3.put_object(Bucket=self.bucket, Key=self.prefix + key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes | None:
        from botocore.exceptions import ClientError

        try:
            return self._s3.get_object(Bucket=self.bucket, Key=self.prefix + key)["Body"].read()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return None
            raise

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._s3.head_object(Bucket=self.bucket, Key=self.prefix + key)
            return True
        except ClientError:
            return False


def create_storage(settings) -> ImageStorage:
    if settings.storage == "s3":
        return S3Storage(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint or None,
            access_key=settings.s3_access_key or None,
            secret_key=settings.s3_secret_key or None,
            region=settings.s3_region,
        )
    return LocalStorage(settings.output_dir)
