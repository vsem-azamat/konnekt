"""The paid places on home, and the API the operator runs them through.

See services/showcase.py and docs/showcase-api.md.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.core.config import Settings, get_settings
from students_cz.db.models import Placement, PlacementEvent
from students_cz.db.models.enums import PlacementEventKind

from .conftest import app_for, auth_header

pytestmark = pytest.mark.asyncio

OPERATOR = 97301
STUDENT = 97302

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _client(session: AsyncSession) -> AsyncClient:
    app = app_for(session)
    configured = Settings(_env_file=None, admin_tg_ids=[OPERATOR])
    app.dependency_overrides[get_settings] = lambda: configured
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _card(**change) -> dict:
    return {
        "service": "bank_letter",
        "partner": "Lumen Výpis",
        "title": "Выписка для ВНЖ за день",
        "line": "Справка из банка на чешском и английском",
        "text": "Готовим выписку за один рабочий день.",
        "price_from": 290,
        "write_to": "@lumen_vypis",
        "until": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        **change,
    }


ADMIN = auth_header(OPERATOR)
CARDS = "/api/v1/admin/showcase/cards"


async def _draft(http: AsyncClient, **change) -> dict:
    response = await http.post(CARDS, headers=ADMIN, json=_card(**change))
    assert response.status_code == 201, response.text
    return response.json()


async def _live(http: AsyncClient, **change) -> dict:
    card = await _draft(http, **change)
    photo = await http.put(
        f"{CARDS}/{card['id']}/photo",
        headers={**ADMIN, "Content-Type": "image/png"},
        content=PNG,
    )
    assert photo.status_code == 200, photo.text
    published = await http.post(f"{CARDS}/{card['id']}/publish", headers=ADMIN)
    assert published.status_code == 200, published.text
    return published.json()


async def _home(http: AsyncClient) -> dict[str, Any]:
    body = (await http.get("/api/v1/home", headers=auth_header(STUDENT))).json()
    return {slot["service"]: slot["card"] for slot in body["showcase"]}


async def test_home_has_the_three_places_in_order_and_empty(
    session: AsyncSession,
) -> None:
    async with _client(session) as http:
        body = (await http.get("/api/v1/home", headers=auth_header(STUDENT))).json()

    assert [slot["service"] for slot in body["showcase"]] == [
        "bank_letter",
        "insurance",
        "residence",
    ]
    assert all(slot["card"] is None for slot in body["showcase"])


async def test_a_draft_is_shown_to_nobody(session: AsyncSession) -> None:
    async with _client(session) as http:
        card = await _draft(http)
        places = await _home(http)
        page = await http.get(
            f"/api/v1/showcase/{card['id']}", headers=auth_header(STUDENT)
        )

    assert card["status"] == "draft"
    assert card["write_to"] == "https://t.me/lumen_vypis"
    assert places["bank_letter"] is None
    assert page.status_code == 404


async def test_the_preview_is_what_a_student_will_read(session: AsyncSession) -> None:
    async with _client(session) as http:
        card = await _draft(http)
        preview = (await http.get(f"{CARDS}/{card['id']}/preview", headers=ADMIN)).json()
        events = await session.scalar(
            select(func.count()).where(PlacementEvent.placement_id == card["id"])
        )
        live = await _live(http, partner="Other Bank")
        page = (
            await http.get(f"/api/v1/showcase/{live['id']}", headers=auth_header(STUDENT))
        ).json()

    assert preview["title"] == "Выписка для ВНЖ за день"
    assert preview["price_from"] == 290
    assert set(preview) == set(page), "the same shape the Mini App reads"
    assert events == 0, "a preview is nobody seeing the card"


async def test_a_published_card_is_on_home_and_counted_as_seen(
    session: AsyncSession,
) -> None:
    async with _client(session) as http:
        card = await _live(http)
        places = await _home(http)

    shown = places["bank_letter"]
    assert card["status"] == "published"
    assert card["published_at"] is not None
    assert shown is not None
    assert shown["id"] == card["id"]
    assert shown["partner"] == "Lumen Výpis"
    assert shown["photo"] == card["photo"]
    impressions = await session.scalar(
        select(func.count()).where(
            PlacementEvent.placement_id == card["id"],
            PlacementEvent.kind == PlacementEventKind.IMPRESSION,
        )
    )
    assert impressions == 1


async def test_a_card_is_not_published_without_a_photo(session: AsyncSession) -> None:
    async with _client(session) as http:
        card = await _draft(http)
        response = await http.post(f"{CARDS}/{card['id']}/publish", headers=ADMIN)

    assert response.status_code == 422
    assert "photo" in response.text


async def test_one_live_card_to_a_place(session: AsyncSession) -> None:
    async with _client(session) as http:
        first = await _live(http)
        second = await _draft(http, partner="Second Bank")
        await http.put(
            f"{CARDS}/{second['id']}/photo",
            headers={**ADMIN, "Content-Type": "image/jpeg"},
            content=JPEG,
        )
        taken = await http.post(f"{CARDS}/{second['id']}/publish", headers=ADMIN)
        other_place = await _live(http, service="insurance", partner="Pojišťovna")
        down = await http.post(f"{CARDS}/{first['id']}/unpublish", headers=ADMIN)
        free = await http.post(f"{CARDS}/{second['id']}/publish", headers=ADMIN)
        places = await _home(http)

    assert taken.status_code == 409
    assert str(first["id"]) in taken.text
    assert other_place["status"] == "published", "another service is another place"
    assert down.json()["status"] == "unpublished"
    assert free.status_code == 200
    assert places["bank_letter"]["id"] == second["id"]
    assert places["insurance"]["id"] == other_place["id"]


async def test_a_card_past_its_until_frees_the_place(session: AsyncSession) -> None:
    async with _client(session) as http:
        old = await _live(http)
        placement = await session.get(Placement, old["id"])
        assert placement is not None
        await session.refresh(placement, ["offer"])
        placement.offer.valid_to = datetime.now(UTC) - timedelta(minutes=1)
        await session.flush()
        places = await _home(http)
        listed = (await http.get(f"{CARDS}/{old['id']}", headers=ADMIN)).json()
        new = await _live(http, partner="Next Bank")

    assert places["bank_letter"] is None
    assert listed["status"] == "expired"
    assert new["status"] == "published", "nobody had to take the old one down"


async def test_nothing_is_deleted(session: AsyncSession) -> None:
    async with _client(session) as http:
        card = await _live(http)
        await http.post(f"{CARDS}/{card['id']}/unpublish", headers=ADMIN)
        listed = (await http.get(CARDS, headers=ADMIN)).json()
        back = await http.post(f"{CARDS}/{card['id']}/publish", headers=ADMIN)

    assert any(row["id"] == card["id"] for row in listed)
    assert back.json()["status"] == "published"
    assert back.json()["published_at"] == card["published_at"], "first went live"


async def test_the_photo_is_served_by_its_hash_and_cached_for_ever(
    session: AsyncSession,
) -> None:
    async with _client(session) as http:
        card = await _live(http)
        photo = await http.get(f"/api/v1/showcase/photos/{card['photo']}")
        unknown = await http.get("/api/v1/showcase/photos/" + "0" * 64)

    assert photo.status_code == 200
    assert photo.content == PNG
    assert photo.headers["content-type"] == "image/png"
    assert "immutable" in photo.headers["cache-control"]
    assert unknown.status_code == 404


@pytest.mark.parametrize(
    ("mime", "content"),
    [
        pytest.param("image/png", JPEG, id="jpeg-bytes-called-png"),
        pytest.param("image/gif", b"GIF89a" + b"\x00" * 16, id="gif"),
        pytest.param("image/png", b"", id="empty"),
        pytest.param("image/png", PNG + b"\x00" * (2 * 1024 * 1024), id="over-2mb"),
    ],
)
async def test_a_photo_is_an_image_it_says_it_is(
    session: AsyncSession, mime: str, content: bytes
) -> None:
    async with _client(session) as http:
        card = await _draft(http)
        response = await http.put(
            f"{CARDS}/{card['id']}/photo",
            headers={**ADMIN, "Content-Type": mime},
            content=content,
        )

    assert response.status_code in (413, 422)


@pytest.mark.parametrize(
    "change",
    [
        {"title": "т" * 33},
        {"line": "с" * 71},
        {"text": "т" * 601},
        {"write_to": "http://example.test"},
        {"price_from": -1},
        {"service": "tutoring"},
    ],
)
async def test_a_card_keeps_to_its_limits(session: AsyncSession, change: dict) -> None:
    async with _client(session) as http:
        response = await http.post(CARDS, headers=ADMIN, json=_card(**change))

    assert response.status_code == 422


async def test_a_card_at_its_limits_is_saved(session: AsyncSession) -> None:
    async with _client(session) as http:
        card = await _draft(http, title="т" * 32, line="с" * 70, text="т" * 600)

    assert len(card["title"]) == 32
    assert len(card["line"]) == 70


async def test_an_edit_changes_only_what_is_sent(session: AsyncSession) -> None:
    async with _client(session) as http:
        card = await _draft(http)
        edited = await http.patch(
            f"{CARDS}/{card['id']}", headers=ADMIN, json={"line": None, "price_from": 350}
        )
        untitled = await http.patch(
            f"{CARDS}/{card['id']}", headers=ADMIN, json={"title": None}
        )

    assert edited.status_code == 200
    assert edited.json()["line"] is None
    assert edited.json()["price_from"] == 350
    assert edited.json()["title"] == card["title"]
    assert untitled.status_code == 422


async def test_the_old_switch_cannot_put_up_a_showcase_card(
    session: AsyncSession,
) -> None:
    async with _client(session) as http:
        card = await _draft(http)
        response = await http.patch(
            f"/api/v1/admin/placements/{card['id']}",
            headers=ADMIN,
            json={"is_active": True},
        )

    assert response.status_code == 409


async def test_a_student_cannot_run_the_showcase(session: AsyncSession) -> None:
    async with _client(session) as http:
        response = await http.post(CARDS, headers=auth_header(STUDENT), json=_card())

    assert response.status_code == 403
