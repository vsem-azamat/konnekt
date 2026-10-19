"""The agreed description of a project chat.

Approved by the owner on 2026-10-19 (#155). University chats share one
description; other project chats keep their own text minus the links that no
longer lead anywhere useful.
"""

from __future__ import annotations

import pytest
from app.chats import template
from app.db.models import Chat

pytestmark = pytest.mark.unit

BOT = "konnekt_moder_bot"
VUT = Chat(id=-10, title="VUT | ВУТ в Брно", institution_code="vut", public_link="https://t.me/vut_chat")


def _university(title: str, current: str, *, parent: Chat | None = VUT) -> str:
    return template.expected_description(title=title, current=current, bot=BOT, university=True, parent=parent)


def _other(current: str) -> str:
    return template.expected_description(title="Strahov", current=current, bot=BOT, university=False)


def _utf16(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def test_a_faculty_points_at_its_main_chat_and_the_bot() -> None:
    text = _university("VUT FIT", "👨‍💻Чат для студентов VUT FIT\n\n📢 Канал сети: @konnekt_cz")

    assert text == (
        "👨‍💻 Чат студентов и абитуриентов VUT FIT\n"
        "Главный чат VUT: @vut_chat\n"
        "Все чаты и помощь с учёбой: @konnekt_moder_bot"
    )


def test_a_main_chat_names_itself_by_its_short_name() -> None:
    text = _university("VUT | ВУТ в Брно", "📍Общий чат для студентов VUT v Brně", parent=None)

    assert text.splitlines()[0] == "📍 Чат студентов и абитуриентов VUT"
    assert "Главный чат" not in text


def test_a_chat_under_a_main_chat_keeps_its_whole_title() -> None:
    text = _university("ČVUT | Fakulta Strojní | 3 kurz", "")

    assert text.splitlines()[0].endswith("абитуриентов ČVUT | Fakulta Strojní | 3 kurz")


@pytest.mark.parametrize(
    "current",
    [
        "Общий чат для студентов MUNI",
        "🎓\n\n📢 Канал сети: @konnekt_cz",
        "«Чат студентов»",
        "📍 — Общий чат",
        "📢 Канал сети: @konnekt_cz",
        "🦁" * 20 + " чат",
    ],
)
def test_only_a_plain_leading_emoji_is_kept(current: str) -> None:
    first = _university("MUNI FI", current).splitlines()[0]

    assert first.split(" ", 1)[0] in {template.DEFAULT_EMOJI, "📍"}
    assert first.endswith(" Чат студентов и абитуриентов MUNI FI")


def test_a_flag_is_a_single_emoji() -> None:
    assert _university("ČVUT 🇺🇦", "🇺🇦 Открытый чат").startswith("🇺🇦 Чат студентов")


def test_other_project_chats_only_lose_the_retired_links() -> None:
    current = (
        "Независимый чат Страхова\n\nЧат для живущих в ареале Strahov\n\n"
        "📢 Канал сети: @konnekt_cz\n📩 Администрация: @work_azamat"
    )

    assert _other(current) == "Независимый чат Страхова\n\nЧат для живущих в ареале Strahov"


def test_text_without_a_retired_link_is_left_exactly_as_it_is() -> None:
    current = "Чат по физике   \n\n\n\nК прочтению: t.me/fyzika_cz/2"

    assert _other(current) == current


@pytest.mark.parametrize(
    "line",
    ["Ещё: @konnekt_cz", "Канал: https://t.me/Konnekt_net", "@Czech_Media", "t.me/czechopen", "📩 @WORK_AZAMAT"],
)
def test_every_retired_link_goes_in_any_form(line: str) -> None:
    assert _other(f"Чат по физике\n{line}") == "Чат по физике"


@pytest.mark.parametrize("line", ["Бот: @konnekt_cz_bot", "@konnekt_network"])
def test_a_longer_handle_that_starts_the_same_stays(line: str) -> None:
    assert _other(f"Чат по физике\n{line}") == f"Чат по физике\n{line}"


@pytest.mark.parametrize(
    ("title", "parent_title"),
    [("VŠCHT " + "X" * 300, "VUT"), ("😀" * 200, "VUT"), ("FIT", "P" * 300)],
)
def test_the_description_fits_telegram(title: str, parent_title: str) -> None:
    parent = Chat(id=-10, title=parent_title, institution_code="vut", public_link="https://t.me/vut_chat")

    assert _utf16(_university(title, "", parent=parent)) <= template.DESCRIPTION_LIMIT


def test_the_main_chat_is_the_only_holder_or_the_one_with_chats_under_it() -> None:
    approved = Chat.STATUS_APPROVED
    cvut = Chat(id=-1, title="ČVUT | ЧВУТ", institution_code="cvut", resource_status=approved)
    strahov = Chat(id=-2, title="Strahov", institution_code="cvut", resource_status=approved)
    fit = Chat(id=-3, title="ČVUT FIT", parent_chat_id=-1, resource_status=approved)
    vse = Chat(id=-4, title="VŠE", institution_code="vse", resource_status=approved)
    stale = Chat(id=-6, title="VŠE old", institution_code="vse")
    fyzika = Chat(id=-5, title="Fyzika v ČR", resource_status=approved)

    assert template.main_chats([cvut, strahov, fit, vse, stale, fyzika]) == {-1, -4}
