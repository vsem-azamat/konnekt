"""The universities as the public site names them.

The site's catalog pages are rendered for people outside Telegram and for
search engines, so this list is read with no init data and no service token.
It is reference data, the same rows every app user reads already: nothing here
belongs to a person.
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_anyone_may_read_them(client: AsyncClient) -> None:
    response = await client.get("/api/v1/universities")

    assert response.status_code == 200
    assert "Authorization" not in response.request.headers


async def test_a_university_carries_what_its_page_shows(client: AsyncClient) -> None:
    response = await client.get("/api/v1/universities", params={"lang": "cs"})

    cvut = next(row for row in response.json() if row["code"] == "cvut")
    assert cvut == {
        "code": "cvut",
        "name": "České vysoké učení technické v Praze",
        "short_name": "ČVUT",
        "city": "Praha",
        "site_url": "https://www.cvut.cz",
    }


async def test_faculties_are_not_universities(client: AsyncClient) -> None:
    """A faculty has no page of its own: its chats are on its university's."""
    response = await client.get("/api/v1/universities")

    codes = {row["code"] for row in response.json()}
    assert "cvut" in codes
    assert "cvut_fit" not in codes


async def test_names_follow_the_asked_language(client: AsyncClient) -> None:
    english = await client.get("/api/v1/universities", params={"lang": "en"})
    russian = await client.get("/api/v1/universities")

    def name(response, code: str) -> str:
        return next(row["name"] for row in response.json() if row["code"] == code)

    assert name(english, "cvut") == "Czech Technical University in Prague"
    assert name(russian, "cvut") == "Чешский технический университет в Праге"


async def test_an_unknown_language_is_refused(client: AsyncClient) -> None:
    response = await client.get("/api/v1/universities", params={"lang": "xx"})

    assert response.status_code == 422
