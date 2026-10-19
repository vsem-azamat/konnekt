"""Words the bot does not say to people, though people say them to it.

Students write «матан» and «přijímačky», and the catalog's search keeps
understanding them. The bot's own texts use the plain names instead. The same
list guards the catalog (`catalog/tests/test_plain_language.py`) and the Mini
App (`web/tests/plainLanguage.test.ts`); it is the words that have actually
shipped and their obvious neighbours, not a dictionary of slang.
"""

import re

# Matched at the start of a word, so every case ending is caught. Python's `\b`
# is Unicode-aware, which is what lets it work on Cyrillic and on Czech.
SLANG = re.compile(
    r"\b("
    r"матан|матеш|линал|англ\b|шари(шь|т|те)\b|теорвер|дискретк|сопромат|общаг"
    r"|приемк|приёмк|приймачк|přijímačk|matan|matik[aouy]\b|sopromat|vejšk"
    r")",
    re.IGNORECASE,
)


def slang(text: str) -> list[str]:
    return [match.group(0) for match in SLANG.finditer(text)]
