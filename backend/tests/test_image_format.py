"""생성 이미지를 WebP로 저장하고, 기존 PNG 기록을 변환하는 스크립트를 검증한다."""

import io
import json
import sys
import pathlib

from fastapi.testclient import TestClient
from PIL import Image
from test_pipeline import wait_done

from app.config import Settings
from app.image.base import GeneratedImage, ImageBackend
from app.image.encode import encode
from app.main import create_app
from app.pipeline import Pipeline
from app.store import JobStore
from app.tagging.ollama_tagger import TagResult

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from convert_outputs_to_webp import convert  # noqa: E402


def png_bytes(size=(64, 96)):
    img = Image.new("RGB", size)
    img.putdata([(x * 4 % 256, y * 2 % 256, (x + y) % 256) for y in range(size[1]) for x in range(size[0])])
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class PngBackend(ImageBackend):
    name = "png"

    async def generate(self, params, on_progress=None):
        return GeneratedImage(data=png_bytes())

    async def health(self):
        return True


def client_for(tmp_path, fmt):
    settings = Settings(output_dir=tmp_path, db_path=tmp_path / "t.db", preset_seed_dir=None)
    tagger = lambda text, keep_alive: TagResult(request=text, tags={"subject": ["1girl"]})  # noqa: E731
    pipeline = Pipeline(PngBackend(), tagger, tmp_path, JobStore(settings.db_path), image_format=fmt)
    return TestClient(create_app(settings, pipeline))


def test_encode_to_webp_and_fallback():
    data, ext = encode(png_bytes(), "webp")
    assert ext == "webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    assert Image.open(io.BytesIO(data)).size == (64, 96)
    assert encode(b"not an image", "webp") == (b"not an image", "png")
    assert encode(png_bytes(), "png")[1] == "png"


def test_jobs_are_saved_and_served_as_webp(tmp_path):
    with client_for(tmp_path, "webp") as client:
        job = wait_done(client, client.post("/jobs", json={"prompt": "1girl", "seed": 1}).json()["id"])
        assert job["image_url"] == f"/images/{job['id']}.webp"
        res = client.get(job["image_url"])
        assert res.headers["content-type"] == "image/webp"
        assert res.content[8:12] == b"WEBP"
        assert not (tmp_path / f"{job['id']}.png").exists()
        assert client.get(f"/images/{job['id']}.gif").status_code == 404


def test_png_setting_keeps_original(tmp_path):
    with client_for(tmp_path, "png") as client:
        job = wait_done(client, client.post("/jobs", json={"prompt": "1girl"}).json()["id"])
        assert job["image_url"].endswith(".png")
        assert client.get(job["image_url"]).headers["content-type"] == "image/png"


def test_convert_script_updates_history(tmp_path):
    with client_for(tmp_path, "png") as client:
        job = wait_done(client, client.post("/jobs", json={"prompt": "1girl"}).json()["id"])
    (tmp_path / "first.png").write_bytes(png_bytes())  # 기록에 없는 파일은 그대로 둔다.

    stats = convert(tmp_path / "t.db", tmp_path, delete_png=True)
    assert stats["converted"] == 1
    assert (tmp_path / f"{job['id']}.webp").is_file() and not (tmp_path / f"{job['id']}.png").exists()
    assert (tmp_path / "first.png").is_file()

    with client_for(tmp_path, "webp") as client:
        again = client.get(f"/jobs/{job['id']}").json()
        assert again["image_url"].endswith(".webp")
        assert client.get(again["image_url"]).status_code == 200
    assert convert(tmp_path / "t.db", tmp_path)["converted"] == 0
