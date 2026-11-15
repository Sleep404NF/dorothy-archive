"""키워드 프리셋: 정규화, 결정적 병합, CRUD API, 생성 작업과의 결합을 검증한다."""

import json

from test_pipeline import make_client, wait_done

from app.presets import Preset, PresetIn, PresetStore, compose, merge_negative, normalize, tag_key

NOW = "2026-01-01T00:00:00.000+00:00"


def preset(type, positive, negative=(), name="p"):
    return Preset(id=name, type=type, name=name, positive=list(positive), negative=list(negative),
                  created_at=NOW, updated_at=NOW)


# --- 정규화 / 병합 ---------------------------------------------------------

def test_normalize_keeps_weights_and_escapes_bare_parens():
    assert normalize("  Long_Hair ") == "long hair"
    assert normalize("(Hair_Ribbon:1.1)") == "(hair ribbon:1.1)"
    assert normalize("bow (weapon)") == r"bow \(weapon\)"
    assert normalize(r"bow \(weapon\)") == r"bow \(weapon\)"
    assert tag_key("(Long_Hair:1.2)") == tag_key("long hair") == "long hair"
    assert tag_key("bow (weapon)") == "bow (weapon)"


def test_compose_orders_character_then_tags_then_style_with_quality_first():
    character = preset("character", ["1girl", "silver hair", "long hair"])
    style = preset("style", ["masterpiece", "watercolor (medium)", "night"])
    result = compose(character, style, ["Long_Hair", "smile", "night"])
    assert result.positive == r"masterpiece, 1girl, silver hair, long hair, smile, night, watercolor \(medium\)"


def test_compose_drops_tags_banned_by_preset_negative():
    character = preset("character", ["1girl", "long hair"], negative=["short hair"])
    result = compose(character, None, ["short_hair", "smile"])
    assert result.positive == "1girl, long hair, smile"
    assert result.negative_tags == ["short hair"]


def test_compose_without_presets_is_just_cleaned_tags():
    assert compose(None, None, ["1girl", "1girl", "Solo"]).positive == "1girl, solo"


def test_merge_negative_appends_only_missing_tags():
    assert merge_negative("nsfw, lowres", ["lowres", "short hair"]) == "nsfw, lowres, short hair"
    assert merge_negative("nsfw", []) == "nsfw"


def test_preset_input_is_cleaned_and_needs_a_positive_tag():
    data = PresetIn(type="style", name="  수채화 ", positive=["Watercolor_(medium)", "watercolor (medium)", " "])
    assert data.name == "수채화"
    assert data.positive == [r"watercolor \(medium\)"]


# --- API -------------------------------------------------------------------

BODY = {"type": "character", "name": "은발 소녀", "positive": ["1girl", "silver hair"], "negative": ["short hair"]}


def test_preset_crud(tmp_path):
    with make_client(tmp_path) as (client, _):
        created = client.post("/presets", json=BODY)
        assert created.status_code == 201
        pid = created.json()["id"]

        assert client.get(f"/presets/{pid}").json()["positive"] == ["1girl", "silver hair"]
        assert [p["id"] for p in client.get("/presets", params={"type": "character"}).json()] == [pid]
        assert client.get("/presets", params={"type": "style"}).json() == []

        updated = client.put(f"/presets/{pid}", json={**BODY, "positive": ["1girl", "white hair"]}).json()
        assert updated["positive"] == ["1girl", "white hair"]
        assert updated["created_at"] == created.json()["created_at"]

        assert client.delete(f"/presets/{pid}").status_code == 204
        assert client.get(f"/presets/{pid}").status_code == 404
        assert client.delete(f"/presets/{pid}").status_code == 404


def test_preset_validation_and_name_conflict(tmp_path):
    with make_client(tmp_path) as (client, _):
        assert client.post("/presets", json={**BODY, "positive": []}).status_code == 422
        assert client.post("/presets", json={**BODY, "type": "pose"}).status_code == 422
        assert client.post("/presets", json=BODY).status_code == 201
        assert client.post("/presets", json=BODY).status_code == 409
        # 종류가 다르면 같은 이름도 된다.
        assert client.post("/presets", json={**BODY, "type": "style"}).status_code == 201


def test_compose_preview_endpoint(tmp_path):
    with make_client(tmp_path) as (client, _):
        cid = client.post("/presets", json=BODY).json()["id"]
        res = client.post("/presets/compose", json={"character_preset_id": cid, "prompt": "short hair, smile"})
        assert res.json() == {"positive": "1girl, silver hair, smile", "negative_tags": ["short hair"]}


# --- 생성 작업과의 결합 ------------------------------------------------------

def make_presets(client):
    cid = client.post("/presets", json=BODY).json()["id"]
    sid = client.post("/presets", json={"type": "style", "name": "밤", "positive": ["masterpiece", "night"]}).json()["id"]
    return cid, sid


def test_prompt_job_composes_presets_without_llm(tmp_path):
    with make_client(tmp_path) as (client, events):
        cid, sid = make_presets(client)
        res = client.post("/jobs", json={"prompt": "smile, short hair", "character_preset_id": cid,
                                         "style_preset_id": sid, "seed": 3})
        job = wait_done(client, res.json()["id"])

        assert job["positive"] == "masterpiece, 1girl, silver hair, smile, night"
        assert job["negative"].endswith(", short hair")
        assert events == [("generate", job["positive"], 3)]
        assert job["presets"]["character"]["name"] == "은발 소녀"
        assert job["presets"]["style"]["name"] == "밤"


def test_presets_alone_are_enough_to_generate(tmp_path):
    with make_client(tmp_path) as (client, events):
        cid, _ = make_presets(client)
        job = wait_done(client, client.post("/jobs", json={"character_preset_id": cid, "seed": 1}).json()["id"])
        assert job["positive"] == "1girl, silver hair"
        assert events == [("generate", "1girl, silver hair", 1)]


def test_request_job_merges_presets_after_tagging(tmp_path):
    with make_client(tmp_path) as (client, events):
        cid, sid = make_presets(client)
        res = client.post("/jobs", json={"request": "웃는 소녀", "character_preset_id": cid, "style_preset_id": sid})
        job = wait_done(client, res.json()["id"])

        # 가짜 태거는 품질 태그 + "1girl, solo" 를 돌려준다.
        assert [e[0] for e in events] == ["tag", "generate"]
        assert job["positive"].startswith("masterpiece, best quality")
        assert job["positive"].endswith("1girl, silver hair, solo, night")
        assert job["tags"] == {"subject": ["1girl", "solo"]}


def test_unknown_or_wrong_type_preset_is_rejected(tmp_path):
    with make_client(tmp_path) as (client, events):
        cid, sid = make_presets(client)
        assert client.post("/jobs", json={"prompt": "1girl", "character_preset_id": "nope"}).status_code == 404
        assert client.post("/jobs", json={"prompt": "1girl", "character_preset_id": sid}).status_code == 422
        assert client.post("/jobs", json={"prompt": "1girl", "style_preset_id": cid}).status_code == 422
        assert client.get("/jobs").json()["total"] == 0
        assert events == []


def test_history_keeps_preset_snapshot_after_preset_changes(tmp_path):
    with make_client(tmp_path) as (client, events):
        cid, _ = make_presets(client)
        original = wait_done(client, client.post("/jobs", json={"character_preset_id": cid, "seed": 7}).json()["id"])

        client.put(f"/presets/{cid}", json={**BODY, "positive": ["1boy"]})
        client.delete(f"/presets/{cid}")
        events.clear()

        again = wait_done(client, client.post(f"/jobs/{original['id']}/rerun").json()["id"])
        assert events == [("generate", "1girl, silver hair", 7)]
        assert again["presets"] == original["presets"]
        assert client.get(f"/jobs/{original['id']}").json()["presets"]["character"]["positive"] == ["1girl", "silver hair"]


# --- 기본 프리셋 ------------------------------------------------------------

def test_seed_only_fills_an_empty_store(tmp_path):
    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    (seed_dir / "a.json").write_text(json.dumps(
        [{"id": "dorothy", "type": "character", "name": "도로시", "positive": ["1girl"]},
         {"type": "style", "name": "밤", "positive": ["night"]}]), encoding="utf-8")

    store = PresetStore(tmp_path / "p.db")
    assert store.seed(seed_dir) == 2
    assert store.get("dorothy").name == "도로시"
    assert store.seed(seed_dir) == 0
    assert store.seed(None) == 0 and store.seed(tmp_path / "missing") == 0
    assert store.count() == 2


def test_bundled_seed_presets_are_valid(tmp_path):
    import pathlib
    bundled = pathlib.Path(__file__).resolve().parents[2] / "prompts" / "presets"
    store = PresetStore(tmp_path / "p.db")
    assert store.seed(bundled) >= 2
    assert store.get("dorothy").type == "character"
