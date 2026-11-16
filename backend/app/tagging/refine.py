"""LLM 태그 결과 다듬기: 한국어 용어집 + Danbooru 태그 사전.

작은 LLM은 두 가지를 자주 틀린다.
1. 없는 태그를 지어낸다 ("drinking coffee", "looking at moon")
   → 태그 사전으로 확인해서 별칭은 대표 태그로 바꾸고("maid outfit" → "maid"),
     사전에 없는 태그는 프롬프트에서 빼고 보고서에 남긴다.
2. 있는 태그지만 뜻이 다른 것을 고른다 ("여우 귀" → "elf ears")
   → 사전으로는 못 잡는다. 자주 틀리는 한국어 표현을 용어집으로 정리해 두고,
     LLM에 힌트로 준 뒤 결과에 정답 태그를 넣고 틀린 태그(avoid)를 뺀다.

순서: 사전 정리 → 용어집 적용 → 중복 제거. 용어집 태그는 사전에 있는 대표 태그만 쓴다(테스트로 보장).
"""

from __future__ import annotations

import csv
import gzip
import json
import pathlib
from dataclasses import dataclass, field

from ..presets import normalize, tag_key


def _space(name: str) -> str:
    return tag_key(name.replace("_", " "))


class TagDictionary:
    def __init__(self, canonical: dict[str, str], aliases: dict[str, str]):
        self._canonical = canonical  # 키 -> 대표 태그 (공백 표기)
        self._aliases = aliases  # 별칭 키 -> 대표 태그

    @classmethod
    def load(cls, path: pathlib.Path, extra: pathlib.Path | None = None) -> "TagDictionary":
        canonical: dict[str, str] = {}
        aliases: dict[str, str] = {}
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8", newline="") as f:
            for row in csv.reader(f):
                name = _space(row[0])
                canonical.setdefault(name, name)
                for alias in (row[3].split(",") if len(row) > 3 and row[3] else []):
                    aliases.setdefault(_space(alias), name)
        if extra and extra.is_file():
            for line in extra.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    canonical.setdefault(_space(line), _space(line))
        # 별칭이 실제 태그 이름과 겹치면 실제 태그를 우선한다.
        return cls(canonical, {k: v for k, v in aliases.items() if k not in canonical})

    def resolve(self, tag: str) -> str | None:
        """대표 태그(공백 표기)를 돌려준다. 사전에 없으면 None."""
        key = tag_key(tag)
        return self._canonical.get(key) or self._aliases.get(key)

    def __contains__(self, tag: str) -> bool:
        return tag_key(tag) in self._canonical

    def __len__(self) -> int:
        return len(self._canonical)


@dataclass
class GlossaryEntry:
    term: str
    field: str
    tags: list[str]
    avoid: list[str] = field(default_factory=list)


class Glossary:
    def __init__(self, entries: list[GlossaryEntry]):
        # 긴 표현부터 맞춰야 "엘프 귀"가 "엘프"보다 먼저 잡힌다.
        self.entries = sorted(entries, key=lambda e: len(e.term.replace(" ", "")), reverse=True)

    @classmethod
    def load(cls, path: pathlib.Path) -> "Glossary":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls([GlossaryEntry(**e) for e in data["entries"]])

    def match(self, request: str) -> list[GlossaryEntry]:
        """요청에 나온 표현을 찾는다. 띄어쓰기는 무시하고, 이미 잡힌 부분과 겹치면 건너뛴다."""
        text = request.replace(" ", "")
        taken = [False] * len(text)
        found = []
        for entry in self.entries:
            term = entry.term.replace(" ", "")
            start = text.find(term)
            while start != -1:
                span = range(start, start + len(term))
                if not any(taken[i] for i in span):
                    for i in span:
                        taken[i] = True
                    found.append(entry)
                    break
                start = text.find(term, start + 1)
        return found


class TagRefiner:
    def __init__(self, dictionary: TagDictionary | None = None, glossary: Glossary | None = None):
        self.dictionary = dictionary
        self.glossary = glossary

    def hint(self, request: str) -> str:
        """LLM에 덧붙일 힌트. 용어집에 걸리는 표현이 없으면 빈 문자열."""
        entries = self.glossary.match(request) if self.glossary else []
        if not entries:
            return ""
        lines = [f'- "{e.term}" -> {", ".join(e.tags)}' for e in entries]
        return "\n\nRequired tags for terms in this request (use these exact tags):\n" + "\n".join(lines)

    def refine(self, request: str, tags: dict[str, list[str]]) -> tuple[dict[str, list[str]], dict | None]:
        """정리된 태그와 보고서를 돌려준다. 바뀐 것이 없으면 보고서는 None."""
        aliased: list[dict] = []
        dropped: list[str] = []
        applied: list[dict] = []
        out: dict[str, list[str]] = {}

        for name, values in tags.items():
            out[name] = []
            for tag in values:
                if self.dictionary:
                    canonical = self.dictionary.resolve(tag)
                    if canonical is None:
                        dropped.append(tag)
                        continue
                    if canonical != tag_key(tag):
                        aliased.append({"from": tag, "to": canonical})
                    tag = normalize(canonical)
                out[name].append(tag)

        for entry in self.glossary.match(request) if self.glossary else []:
            avoid = {tag_key(t) for t in entry.avoid}
            removed = [t for values in out.values() for t in values if tag_key(t) in avoid]
            for name in out:
                out[name] = [t for t in out[name] if tag_key(t) not in avoid]
            present = {tag_key(t) for values in out.values() for t in values}
            added = [normalize(t) for t in entry.tags if tag_key(t) not in present]
            out.setdefault(entry.field, []).extend(added)
            if added or removed:
                applied.append({"term": entry.term, "added": added, "removed": removed})

        seen: set[str] = set()
        for name in out:
            unique = []
            for tag in out[name]:
                if tag_key(tag) not in seen:
                    seen.add(tag_key(tag))
                    unique.append(tag)
            out[name] = unique

        report = {k: v for k, v in {"glossary": applied, "aliased": aliased, "dropped": dropped}.items() if v}
        return out, report or None


def load_refiner(
    dictionary_path: pathlib.Path | None,
    extra_path: pathlib.Path | None,
    glossary_path: pathlib.Path | None,
) -> TagRefiner | None:
    """있는 파일만 써서 TagRefiner 를 만든다. 둘 다 없으면 None (검증 없이 동작)."""
    dictionary = TagDictionary.load(dictionary_path, extra_path) if dictionary_path and dictionary_path.is_file() else None
    glossary = Glossary.load(glossary_path) if glossary_path and glossary_path.is_file() else None
    return TagRefiner(dictionary, glossary) if dictionary or glossary else None
