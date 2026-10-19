"""What the catalog says to people is said in plain language.

Students write «матан» and «přijímačky» into the search, and the search has to
understand them — those words stay in `seeds/subjects.json` as synonyms and in
the parser's keyword table. What the catalog writes back is another matter: a
tile called «Přijímačky» or a hint reading «матан, физика» is the product
talking slang to someone who may not know it. So the names, hints and labels
people read are held to a short list of words that must not appear in them.

The list is not a dictionary of slang. It is the words this catalog has
actually shipped, and the obvious neighbours of them; add to it when another
one turns up.
"""

import ast
import json
import re
import unicodedata
from collections.abc import Iterator
from pathlib import Path

import pytest

from students_cz.db import demo
from students_cz.db.seed import SERVICE_OPTIONS, SERVICE_TYPES

SEEDS = Path(__file__).resolve().parents[1] / "seeds"

# Matched at the start of a word, so every case ending is caught: «матан»,
# «матану», «матанализ». Python's `\b` is Unicode-aware, which is what lets it
# work on Cyrillic and on Czech with diacritics.
SLANG = re.compile(
    r"\b("
    r"матан|матеш|линал|англ\b|шари(шь|т|те|ть)\b|теорвер|дискрет(к|ок)|сопромат|общаг"
    r"|при[её]м(к|ок)|приймач(к|ок)|přijímač(k|ek)|matan|matik(a|o|u|y|ou)\b|sopromat|vejš(k|c)"
    r")",
    re.IGNORECASE,
)


def _slang(text: str) -> list[str]:
    return [
        match.group(0) for match in SLANG.finditer(unicodedata.normalize("NFC", text))
    ]


@pytest.mark.parametrize(
    "text",
    [
        "матан",
        "Матану",
        "матанализ",
        "Přijímačky",
        "bez přijímaček",
        "приемка",
        "англ",
        "шаришь",
        "vejšku",
        "na vejšce",
        "matikou",
        "pr\u030cijímac\u030cky",
    ],
)
def test_the_list_catches_what_it_names(text: str) -> None:
    assert _slang(text), text


@pytest.mark.parametrize(
    "text",
    [
        "Математический анализ",
        "Přijímací zkoušky",
        "английский",
        "Informatika",
        "Matematika",
        "prijimacky-technicke-vs",
    ],
)
def test_the_list_leaves_plain_words_alone(text: str) -> None:
    assert not _slang(text), text


def test_service_types_are_named_plainly() -> None:
    found = {
        (spec["code"], lang): _slang(" ".join(filter(None, value)))
        for spec in SERVICE_TYPES
        for lang, value in spec["names"].items()
    }
    assert {key: words for key, words in found.items() if words} == {}


def test_what_an_errand_covers_is_said_plainly() -> None:
    found = {
        (code, row[0]): _slang(" ".join(row[1:]))
        for code, rows in SERVICE_OPTIONS.items()
        for row in rows
    }
    assert {key: words for key, words in found.items() if words} == {}


def _subject_names(nodes: list[dict]) -> Iterator[tuple[str, str, str]]:
    for node in nodes:
        for lang, name in node["names"].items():
            yield node["slug"], lang, name
        yield from _subject_names(node.get("children", []))


def test_subjects_are_named_plainly() -> None:
    """Names only. The synonyms are where the slang belongs."""
    data = json.loads((SEEDS / "subjects.json").read_text(encoding="utf-8"))
    found = {
        (slug, lang): _slang(name) for slug, lang, name in _subject_names(data["groups"])
    }
    assert {key: words for key, words in found.items() if words} == {}


def test_demo_people_talk_plainly() -> None:
    """The demo is what the screens are judged by, so it sets the tone.

    Every string literal in the module, read from its source: profiles, offers,
    partner cards. Docstrings are strings too, which is fine — the module has no
    reason to use slang in them either.
    """
    tree = ast.parse(Path(demo.__file__).read_text(encoding="utf-8"))
    found = [
        (node.lineno, word)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        for word in _slang(node.value)
    ]
    assert found == []
