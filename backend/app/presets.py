"""캐릭터·스타일 키워드 프리셋과 결정적 병합.

프리셋은 Danbooru 태그 목록을 담은 JSON이다. 생성할 때 아래 규칙으로 합친다.
- 순서: 캐릭터 프리셋 → 요청(또는 직접 입력) 태그 → 스타일 프리셋
- 품질 태그(masterpiece 등)는 어디서 왔든 맨 앞으로 모은다.
- 같은 태그는 처음 나온 것만 남긴다. 표기(대소문자, 밑줄, 가중치)가 달라도 같은 태그로 본다.
- 프리셋의 negative 에 있는 태그는 positive 에서 빼고 제외 프롬프트로 보낸다.
  예: 캐릭터가 negative 에 "short hair" 를 두면 요청에서 나온 "short hair" 는 버려진다.

같은 입력이면 항상 같은 결과가 나온다. LLM 보정은 이 결과 위에 얹을 예정이다.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import re
import sqlite3
import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .tagging.ollama_tagger import QUALITY_TAGS

PresetType = Literal["character", "style"]

_WEIGHTED = re.compile(r"^\((.+):[0-9]*\.?[0-9]+\)$")
_BARE_PAREN = re.compile(r"(?<!\\)([()])")


def normalize(tag: str) -> str:
    """표기를 정리한다. 앞뒤 공백 제거, 밑줄 → 공백, 연속 공백 정리, 소문자.

    가중치 문법 "(tag:1.2)" 은 그대로 두고, 그 밖의 괄호는 ComfyUI 에서 가중치로
    읽히지 않도록 이스케이프한다: "bow (weapon)" -> "bow \\(weapon\\)".
    """
    tag = re.sub(r"\s+", " ", tag.strip().replace("_", " ")).lower()
    if _WEIGHTED.match(tag):
        return tag
    return _BARE_PAREN.sub(r"\\\1", tag)


def tag_key(tag: str) -> str:
    """중복 비교용 키. 가중치와 이스케이프를 벗긴다: "(Long_Hair:1.2)" -> "long hair"."""
    tag = normalize(tag)
    match = _WEIGHTED.match(tag)
    if match:
        tag = match.group(1).strip()
    return tag.replace("\\(", "(").replace("\\)", ")")


def split_tags(text: str | None) -> list[str]:
    """쉼표로 구분된 프롬프트를 태그 목록으로 나눈다."""
    return [t for t in (normalize(part) for part in (text or "").split(",")) if t]


def dedupe(tags: list[str]) -> list[str]:
    seen, out = set(), []
    for tag in tags:
        tag = normalize(tag)
        key = tag_key(tag)
        if tag and key not in seen:
            seen.add(key)
            out.append(tag)
    return out


class PresetIn(BaseModel):
    type: PresetType
    name: str = Field(min_length=1, max_length=50)
    positive: list[str] = Field(min_length=1)
    negative: list[str] = Field(default_factory=list)
    lora: list[dict] = Field(default_factory=list, description="예약 필드. 아직 생성에 쓰지 않는다.")

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("positive", "negative")
    @classmethod
    def _clean_tags(cls, value: list[str]) -> list[str]:
        return dedupe(value)

    @field_validator("positive")
    @classmethod
    def _positive_not_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("positive needs at least one tag")
        return value


class Preset(PresetIn):
    id: str
    created_at: str
    updated_at: str


class Composed(BaseModel):
    positive: str
    negative_tags: list[str]


def compose(character: Preset | None, style: Preset | None, tags: list[str]) -> Composed:
    """프리셋과 태그를 합쳐 최종 positive 와, 제외 프롬프트에 더할 태그를 만든다."""
    presets = [p for p in (character, style) if p]
    banned = {tag_key(t) for p in presets for t in p.negative}
    quality = {tag_key(t) for t in QUALITY_TAGS}

    front, rest = [], []
    for tag in dedupe([*(character.positive if character else []), *tags, *(style.positive if style else [])]):
        key = tag_key(tag)
        if key in banned:
            continue
        (front if key in quality else rest).append(tag)

    return Composed(
        positive=", ".join(front + rest),
        negative_tags=dedupe([t for p in presets for t in p.negative]),
    )


def merge_negative(negative: str, extra: list[str]) -> str:
    """기존 제외 프롬프트 뒤에 없는 태그만 덧붙인다. 기존 문자열은 건드리지 않는다."""
    have = {tag_key(t) for t in negative.split(",") if t.strip()}
    added = [t for t in extra if tag_key(t) not in have]
    return ", ".join([negative, *added]) if added else negative


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


class PresetConflict(ValueError):
    """같은 종류에 같은 이름의 프리셋이 이미 있다."""


class PresetStore:
    """프리셋 저장소 (SQLite). 생성 기록과 같은 DB 파일의 presets 테이블을 쓴다."""

    def __init__(self, path: pathlib.Path | str):
        if str(path) != ":memory:":
            pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS presets (
                id         TEXT PRIMARY KEY,
                type       TEXT NOT NULL,
                name       TEXT NOT NULL,
                data       TEXT NOT NULL,
                UNIQUE (type, name)
            )
            """
        )

    def list(self, type: PresetType | None = None) -> list[Preset]:
        where, args = ("WHERE type = ?", [type]) if type else ("", [])
        rows = self._db.execute(f"SELECT data FROM presets {where} ORDER BY type, name", args).fetchall()
        return [Preset.model_validate_json(r[0]) for r in rows]

    def get(self, preset_id: str) -> Preset | None:
        row = self._db.execute("SELECT data FROM presets WHERE id = ?", (preset_id,)).fetchone()
        return Preset.model_validate_json(row[0]) if row else None

    def create(self, data: PresetIn, preset_id: str | None = None) -> Preset:
        now = _now()
        preset = Preset(id=preset_id or uuid.uuid4().hex[:12], created_at=now, updated_at=now, **data.model_dump())
        self._write("INSERT INTO presets (id, type, name, data) VALUES (?, ?, ?, ?)", preset)
        return preset

    def update(self, preset_id: str, data: PresetIn) -> Preset | None:
        old = self.get(preset_id)
        if not old:
            return None
        preset = Preset(id=old.id, created_at=old.created_at, updated_at=_now(), **data.model_dump())
        self._write("UPDATE presets SET type = ?, name = ?, data = ? WHERE id = ?", preset, update=True)
        return preset

    def delete(self, preset_id: str) -> bool:
        return self._db.execute("DELETE FROM presets WHERE id = ?", (preset_id,)).rowcount > 0

    def count(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM presets").fetchone()[0]

    def seed(self, directory: pathlib.Path | None) -> int:
        """저장소가 비어 있을 때만 directory 의 *.json 프리셋을 넣는다. 넣은 개수를 돌려준다.

        파일 하나에 프리셋 하나(객체) 또는 여러 개(배열)를 둘 수 있고, "id" 를 주면 그 값을 쓴다.
        """
        if directory is None or not directory.is_dir() or self.count() > 0:
            return 0
        added = 0
        for path in sorted(directory.glob("*.json")):
            items = json.loads(path.read_text(encoding="utf-8"))
            for item in items if isinstance(items, list) else [items]:
                self.create(PresetIn.model_validate(item), preset_id=item.get("id"))
                added += 1
        return added

    def close(self) -> None:
        self._db.close()

    def _write(self, sql: str, preset: Preset, update: bool = False) -> None:
        row = (preset.type, preset.name, preset.model_dump_json(), preset.id)
        args = row if update else (preset.id, preset.type, preset.name, preset.model_dump_json())
        try:
            self._db.execute(sql, args)
        except sqlite3.IntegrityError:
            raise PresetConflict(f"a {preset.type} preset named {preset.name!r} already exists") from None
