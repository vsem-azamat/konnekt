"""An external chat known only by its invite link (`t.me/+hash`).

The bot is not there and Telegram tells only a member the id, so the row gets
an id of ours and is kept from the link's public page. Nothing about it may
reach the Bot API: not the console, not the hourly loop, not the audit.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.chats import previews
from app.chats.previews import Photo, Preview
from app.chats.snapshots import snapshot_once
from app.db.models import Chat, ChatAvatar, ChatMemberSnapshot
from sqlalchemy import select

from tests.webapi.test_external_chats import client_factory  # noqa: F401

pytestmark = pytest.mark.asyncio

INVITE = "5byLmmR3YvIyYWFi"
LINK = f"https://t.me/+{INVITE}"
JPEG = b"\xff\xd8\xff" + b"0" * 100

PAGE = """
<div class="tgme_page_photo"><a href="tg://join?invite=x"><img class="tgme_page_photo_image" src="https://cdn4.telesco.pe/file/abc.jpg"></a></div>
<div class="tgme_page_title" dir="auto">
  <span dir="auto">UPOL Студенты &amp; Оломоуц</span>
</div>
<div class="tgme_page_extra">1 090 members, 34 online</div>
"""


@pytest.fixture
def page(monkeypatch):
    """What t.me answers, without the network: the preview, then the picture."""
    answer: dict[str, Preview | None] = {
        "preview": Preview(
            title="UPOL Студенты Оломоуц", member_count=90, is_channel=False, photo_url="https://x/a.jpg"
        )
    }
    fetch = AsyncMock(side_effect=lambda _http, _link: answer["preview"])
    monkeypatch.setattr(previews, "fetch", fetch)
    monkeypatch.setattr(previews, "fetch_photo", AsyncMock(return_value=Photo(unique_id="tme-abc", content=JPEG)))
    return answer, fetch


class TestThePage:
    def test_a_group_s_page_is_read(self) -> None:
        assert previews.parse(PAGE) == Preview(
            title="UPOL Студенты & Оломоуц",
            member_count=1090,
            is_channel=False,
            photo_url="https://cdn4.telesco.pe/file/abc.jpg",
        )

    def test_a_channel_counts_subscribers(self) -> None:
        page = PAGE.replace("1 090 members, 34 online", "717 subscribers")
        assert previews.parse(page) == Preview(
            title="UPOL Студенты & Оломоуц", member_count=717, is_channel=True, photo_url=previews.parse(PAGE).photo_url
        )

    def test_a_dead_link_names_no_chat(self) -> None:
        assert previews.parse('<div class="tgme_page_description">If you have Telegram…</div>') is None

    @pytest.mark.parametrize(
        "link", [LINK, f"t.me/+{INVITE}", f"https://t.me/joinchat/{INVITE}", f"https://telegram.me/+{INVITE}/"]
    )
    def test_an_invite_is_taken_in_its_usual_spellings(self, link) -> None:
        assert previews.invite_hash_of(link) == INVITE

    @pytest.mark.parametrize("link", ["https://t.me/cvut_fjfi", "https://example.com/+abcdefgh", "+abcdefgh"])
    def test_anything_else_is_not_an_invite(self, link) -> None:
        assert previews.invite_hash_of(link) is None


class TestTheId:
    def test_it_is_no_telegram_id_and_still_exact_in_a_browser(self) -> None:
        chat_id = Chat.preview_id_for(INVITE)
        assert -(2**53) < chat_id < Chat.PREVIEW_ID_CEILING
        assert Chat(id=chat_id).is_preview_only
        assert not Chat(id=-1001852850466).is_preview_only

    def test_the_same_link_gives_the_same_id(self) -> None:
        assert Chat.preview_id_for(INVITE) == Chat.preview_id_for(INVITE)
        assert Chat.preview_id_for(INVITE) != Chat.preview_id_for("anotherHash12")


class TestAdding:
    async def test_it_is_listed_from_its_page(self, client_factory, db_session_maker, page) -> None:  # noqa: F811
        make, holder = client_factory

        async with make() as client:
            resp = await client.post("/api/chats/external", json={"public_link": f"t.me/+{INVITE}"})

        assert resp.status_code == 201
        body = resp.json()
        assert (body["id"], body["title"], body["resource_status"], body["member_count"]) == (
            Chat.preview_id_for(INVITE),
            "UPOL Студенты Оломоуц",
            "external",
            90,
        )
        holder["bot"].get_chat.assert_not_called()
        async with db_session_maker() as s:
            chat = await s.get(Chat, Chat.preview_id_for(INVITE))
            avatar = await s.get(ChatAvatar, Chat.preview_id_for(INVITE))
            counts = (await s.execute(select(ChatMemberSnapshot.member_count))).scalars().all()
        assert chat is not None
        assert chat.public_link == LINK
        assert avatar is not None
        assert avatar.unique_id == "tme-abc"
        assert counts == [90]

    async def test_it_shows_up_in_the_public_catalogue(self, client_factory, page) -> None:  # noqa: F811
        make, _ = client_factory

        async with make() as client:
            await client.post("/api/chats/external", json={"public_link": LINK})
            rows = (await client.get("/api/public/catalog")).json()

        assert [(row["title"], row["link"], row["external"], row["member_count"]) for row in rows] == [
            ("UPOL Студенты Оломоуц", LINK, True, 90)
        ]
        assert rows[0]["avatar"].endswith("/tme-abc")

    async def test_a_link_twice_is_refused(self, client_factory, page) -> None:  # noqa: F811
        make, _ = client_factory

        async with make() as client:
            await client.post("/api/chats/external", json={"public_link": LINK})
            resp = await client.post("/api/chats/external", json={"public_link": f"https://t.me/joinchat/{INVITE}"})

        assert (resp.status_code, resp.json()["detail"]) == (409, "already_known")

    async def test_a_dead_link_is_refused(self, client_factory, db_session_maker, page) -> None:  # noqa: F811
        make, _ = client_factory
        page[0]["preview"] = None

        async with make() as client:
            resp = await client.post("/api/chats/external", json={"public_link": LINK})

        assert (resp.status_code, resp.json()["detail"]) == (422, "not_found")
        async with db_session_maker() as s:
            assert (await s.execute(select(Chat))).scalars().all() == []

    async def test_it_can_never_be_moderated(self, client_factory, page) -> None:  # noqa: F811
        make, _ = client_factory

        async with make() as client:
            await client.post("/api/chats/external", json={"public_link": LINK})
            resp = await client.patch(f"/api/chats/{Chat.preview_id_for(INVITE)}", json={"resource_status": "approved"})

        assert resp.status_code == 409

    async def test_refresh_reads_the_page_not_the_bot(self, client_factory, page) -> None:  # noqa: F811
        make, holder = client_factory

        async with make() as client:
            await client.post("/api/chats/external", json={"public_link": LINK})
            page[0]["preview"] = Preview(title="UPOL", member_count=95, is_channel=False, photo_url=None)
            resp = await client.post(f"/api/chats/{Chat.preview_id_for(INVITE)}/refresh")

        assert resp.status_code == 200
        assert (resp.json()["title"], resp.json()["member_count"]) == ("UPOL", 95)
        holder["bot"].get_chat.assert_not_called()


class TestTheLoops:
    async def test_the_hourly_loop_reads_the_page_and_never_asks_the_bot(self, db_session_maker, page) -> None:
        chat_id = Chat.preview_id_for(INVITE)
        async with db_session_maker() as s:
            s.add(Chat(id=chat_id, title="UPOL", resource_status=Chat.STATUS_EXTERNAL, public_link=LINK))
            await s.commit()
        bot = MagicMock()
        bot.get_chat = AsyncMock()
        bot.get_chat_member_count = AsyncMock()

        written = await snapshot_once(session_maker=db_session_maker, bot=bot)
        again = await snapshot_once(session_maker=db_session_maker, bot=bot)

        bot.get_chat.assert_not_called()
        bot.get_chat_member_count.assert_not_called()
        # Read once, then not again until a day has passed.
        assert (written, again) == (1, 0)
        assert page[1].await_count == 1
        async with db_session_maker() as s:
            chat = await s.get(Chat, chat_id)
        assert chat is not None
        assert chat.title == "UPOL Студенты Оломоуц"
