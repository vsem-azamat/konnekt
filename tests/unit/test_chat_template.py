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


def _chat(title: str, *, institution: str | None = None, link: str | None = None) -> Chat:
    return Chat(id=-1, title=title, institution_code=institution, public_link=link)


VUT = _chat("VUT | ВУТ в Брно", institution="vut", link="https://t.me/vut_chat")


def test_a_faculty_points_at_its_main_chat_and_the_bot() -> None:
    fit = _chat("VUT FIT")

    text = template.expected_description(
        fit, parent=VUT, current="👨‍💻Чат для студентов VUT FIT\n\n📢 Канал сети: @konnekt_cz", bot=BOT
    )

    assert text == (
        "👨‍💻 Чат студентов и абитуриентов VUT FIT\n"
        "Главный чат VUT: @vut_chat\n"
        "Все чаты и помощь с учёбой: @konnekt_moder_bot"
    )


def test_a_university_root_names_itself_by_its_short_name() -> None:
    text = template.expected_description(
        VUT, current="📍Общий чат для студентов VUT v Brně", bot=BOT, is_main=True
    )

    assert text.splitlines()[0] == "📍 Чат студентов и абитуриентов VUT"
    assert "Главный чат" not in text


def test_without_an_emoji_the_description_gets_a_default() -> None:
    muni = _chat("MUNI | Университет Масарика", institution="muni", link="https://t.me/masaryk_chat")
    fi = _chat("MUNI FI")

    text = template.expected_description(fi, parent=muni, current="Общий чат для студентов MUNI", bot=BOT)

    assert text.startswith(f"{template.DEFAULT_EMOJI} Чат студентов и абитуриентов MUNI FI\n")


def test_a_chat_under_a_university_keeps_its_whole_title() -> None:
    cvut = _chat("ČVUT | ЧВУТ", institution="cvut", link="https://t.me/cvut_chat")
    year = _chat("ČVUT | Fakulta Strojní | 3 kurz")

    text = template.expected_description(year, parent=cvut, current="", bot=BOT)

    assert text.splitlines()[0].endswith("абитуриентов ČVUT | Fakulta Strojní | 3 kurz")


def test_a_dormitory_with_an_institution_is_not_a_university_chat() -> None:
    hvezda = _chat("Kolej Hvězda", institution="cvut")

    text = template.expected_description(hvezda, current="Чат для живущих в общежитии Hvězda.", bot=BOT)

    assert text == "Чат для живущих в общежитии Hvězda."


def test_other_project_chats_only_lose_the_retired_links() -> None:
    strahov = _chat("Strahov")
    current = (
        "Независимый чат Страхова\n\nЧат для живущих в ареале Strahov\n\n"
        "📢 Канал сети: @konnekt_cz\n📩 Администрация: @work_azamat"
    )

    text = template.expected_description(strahov, current=current, bot=BOT)

    assert text == "Независимый чат Страхова\n\nЧат для живущих в ареале Strahov"


@pytest.mark.parametrize("handle", ["@konnekt_cz", "@konnekt_net", "@Czech_Media", "@czechopen", "@work_azamat"])
def test_every_retired_link_goes(handle: str) -> None:
    text = template.expected_description(_chat("Fyzika v ČR"), current=f"Чат по физике\n💬 Ещё: {handle}", bot=BOT)

    assert handle.casefold() not in text.casefold()


def test_the_description_fits_telegram() -> None:
    long_title = "VŠCHT " + "X" * 200
    text = template.expected_description(_chat(long_title), parent=VUT, current="", bot=BOT)

    assert len(text) <= template.DESCRIPTION_LIMIT


def test_the_main_chat_is_the_only_holder_or_the_one_with_chats_under_it() -> None:
    cvut = Chat(id=-1, title="ČVUT | ЧВУТ", institution_code="cvut")
    strahov = Chat(id=-2, title="Strahov", institution_code="cvut")
    fit = Chat(id=-3, title="ČVUT FIT", parent_chat_id=-1)
    vse = Chat(id=-4, title="VŠE", institution_code="vse")
    fyzika = Chat(id=-5, title="Fyzika v ČR")

    assert template.main_chats([cvut, strahov, fit, vse, fyzika]) == {-1, -4}
