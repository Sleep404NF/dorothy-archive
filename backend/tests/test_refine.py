"""태그 검증: 사전(별칭 정리, 없는 태그 제거) + 한국어 용어집(힌트, 정답 태그 넣기, 틀린 태그 빼기)."""

import gzip
import pathlib

import pytest
from test_pipeline import make_client, wait_done

from app.tagging.refine import Glossary, GlossaryEntry, TagDictionary, TagRefiner, load_refiner

PROMPTS = pathlib.Path(__file__).resolve().parents[2] / "prompts"


@pytest.fixture
def dictionary(tmp_path):
    path = tmp_path / "tags.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(
            "1girl,0,100,\"1girls\"\n"
            "long_hair,0,100,\n"
            "pointy_ears,0,100,\"elf_ears\"\n"
            "fox_ears,0,100,\n"
            "maid,0,100,\"maid_outfit\"\n"
            "bow_(weapon),0,100,\n"
            "lake,0,100,\n"
            "moonlight,0,100,\n"
        )
    extra = tmp_path / "extra.txt"
    extra.write_text("# 주석\nsilver_hair\n", encoding="utf-8")
    return TagDictionary.load(path, extra)


GLOSSARY = Glossary([
    GlossaryEntry("여우 귀", "appearance", ["fox ears"], ["pointy ears"]),
    GlossaryEntry("엘프", "appearance", ["pointy ears"]),
    GlossaryEntry("엘프 귀", "appearance", ["pointy ears"]),
    GlossaryEntry("호숫가", "background", ["lake"]),
])


def test_dictionary_resolves_aliases_extras_and_escapes(dictionary):
    assert dictionary.resolve("Maid_Outfit") == "maid"
    assert dictionary.resolve("elf ears") == "pointy ears"
    assert dictionary.resolve("silver hair") == "silver hair"
    assert dictionary.resolve(r"bow \(weapon\)") == "bow (weapon)"
    assert dictionary.resolve("looking at moon") is None


def test_glossary_prefers_longer_terms_and_ignores_spacing():
    assert [e.term for e in GLOSSARY.match("엘프 귀 소녀")] == ["엘프 귀"]
    assert [e.term for e in GLOSSARY.match("여우귀 소녀가 호숫가에")] == ["여우 귀", "호숫가"]
    assert GLOSSARY.match("고양이") == []


def test_fox_ears_request_is_fixed(dictionary):
    refiner = TagRefiner(dictionary, GLOSSARY)
    tags, report = refiner.refine(
        "달빛 아래 호숫가에 앉아 있는 여우 귀 소녀",
        {
            "subject": ["1girl"],
            "appearance": ["long hair", "elf ears"],
            "clothing": ["maid outfit"],
            "pose_expression": ["looking at moon"],
            "background": ["lake", "moonlight"],
        },
    )
    assert tags == {
        "subject": ["1girl"],
        "appearance": ["long hair", "fox ears"],
        "clothing": ["maid"],
        "pose_expression": [],
        "background": ["lake", "moonlight"],
    }
    assert report == {
        "glossary": [{"term": "여우 귀", "added": ["fox ears"], "removed": ["pointy ears"]}],
        "aliased": [{"from": "elf ears", "to": "pointy ears"}, {"from": "maid outfit", "to": "maid"}],
        "dropped": ["looking at moon"],
    }


def test_nothing_to_report_returns_none(dictionary):
    tags, report = TagRefiner(dictionary, GLOSSARY).refine("소녀", {"subject": ["1girl"], "appearance": ["long hair"]})
    assert tags == {"subject": ["1girl"], "appearance": ["long hair"]}
    assert report is None


def test_glossary_tag_goes_into_missing_field_and_escapes(dictionary):
    refiner = TagRefiner(dictionary, Glossary([GlossaryEntry("활", "clothing", ["bow (weapon)"])]))
    tags, _ = refiner.refine("활을 든 소녀", {"subject": ["1girl"]})
    assert tags == {"subject": ["1girl"], "clothing": [r"bow \(weapon\)"]}


def test_hint_lists_matched_terms():
    refiner = TagRefiner(None, GLOSSARY)
    assert refiner.hint("고양이") == ""
    assert '"여우 귀" -> fox ears' in refiner.hint("여우 귀 소녀")


def test_bundled_glossary_only_uses_dictionary_tags():
    refiner = load_refiner(
        PROMPTS / "tags" / "danbooru_tags.csv.gz", PROMPTS / "tags" / "extra_tags.txt", PROMPTS / "glossary.ko.json"
    )
    assert len(refiner.dictionary) > 50_000
    fields = {"subject", "character", "appearance", "clothing", "pose_expression", "composition", "background"}
    for entry in refiner.glossary.entries:
        assert entry.field in fields, entry.term
        for tag in entry.tags + entry.avoid:
            assert tag in refiner.dictionary, (entry.term, tag)


def test_missing_files_disable_refiner(tmp_path):
    assert load_refiner(tmp_path / "x.gz", None, tmp_path / "y.json") is None


def test_pipeline_sends_hint_and_stores_report(tmp_path, dictionary):
    raw = {"subject": ["1girl", "solo"], "appearance": ["elf ears"], "background": ["lake"]}
    with make_client(tmp_path, refiner=TagRefiner(dictionary, GLOSSARY), tags=raw) as (client, events):
        job = wait_done(client, client.post("/jobs", json={"request": "호숫가의 여우 귀 소녀", "seed": 1}).json()["id"])

        sent = events[0][1]
        assert sent.startswith("호숫가의 여우 귀 소녀") and "fox ears" in sent
        assert job["request"] == "호숫가의 여우 귀 소녀"
        assert job["tags"]["appearance"] == ["fox ears"]
        assert "pointy ears" not in job["positive"] and "fox ears" in job["positive"]
        assert job["tag_report"]["dropped"] == ["solo"]  # 테스트용 사전에 solo 가 없다.
        assert job["tag_report"]["glossary"][0]["removed"] == ["pointy ears"]

        again = wait_done(client, client.post(f"/jobs/{job['id']}/rerun").json()["id"])
        assert again["tag_report"] == job["tag_report"]
