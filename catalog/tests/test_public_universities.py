"""The universities as the public site names them.

The site's catalog pages are rendered for people outside Telegram and for
search engines, so this list is read with no init data and no service token.
It is reference data, the same rows every app user reads already: nothing here
belongs to a person.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.db.models import Institution
from students_cz.db.models.enums import InstitutionKind

pytestmark = pytest.mark.asyncio


async def test_anyone_may_read_them(client: AsyncClient) -> None:
    response = await client.get("/api/v1/universities")

    assert response.status_code == 200
    assert "Authorization" not in response.request.headers


async def test_a_university_carries_what_its_page_shows(client: AsyncClient) -> None:
    response = await client.get("/api/v1/universities", params={"lang": "cs"})

    cvut = next(row for row in response.json() if row["code"] == "cvut")
    faculties = cvut.pop("faculties")
    assert cvut == {
        "code": "cvut",
        "name": "České vysoké učení technické v Praze",
        "short_name": "ČVUT",
        "city": "Praha",
        "site_url": "https://www.cvut.cz",
    }
    assert faculties[0] == {
        "code": "cvut_fsv",
        "name": "Fakulta stavební",
        "short_name": "FSv",
    }


async def test_faculties_are_not_universities(client: AsyncClient) -> None:
    """A faculty has no page of its own: its chats are on its university's."""
    response = await client.get("/api/v1/universities")

    codes = {row["code"] for row in response.json()}
    assert "cvut" in codes
    assert "cvut_fit" not in codes


async def test_a_university_lists_its_faculties_in_order(client: AsyncClient) -> None:
    """Its page lists every faculty, the ones without a text of the site's too."""
    response = await client.get("/api/v1/universities")

    cvut = next(row for row in response.json() if row["code"] == "cvut")
    assert [f["code"] for f in cvut["faculties"]] == [
        "cvut_fsv",
        "cvut_fs",
        "cvut_fel",
        "cvut_fjfi",
        "cvut_fa",
        "cvut_fd",
        "cvut_fbmi",
        "cvut_fit",
    ]
    assert cvut["faculties"][-1]["name"] == "Факультет информационных технологий"


async def test_a_retired_faculty_is_not_listed(
    client: AsyncClient, session: AsyncSession
) -> None:
    await session.execute(
        update(Institution).where(Institution.code == "cvut_fit").values(is_active=False)
    )

    response = await client.get("/api/v1/universities")

    cvut = next(row for row in response.json() if row["code"] == "cvut")
    assert "cvut_fit" not in {f["code"] for f in cvut["faculties"]}


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


async def test_a_retired_university_is_not_listed(
    client: AsyncClient, session: AsyncSession
) -> None:
    await session.execute(
        update(Institution).where(Institution.code == "cvut").values(is_active=False)
    )

    response = await client.get("/api/v1/universities")

    assert "cvut" not in {row["code"] for row in response.json()}


async def test_only_a_university_is_one(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A school or an exam body at the top of the tree has no catalog page."""
    await session.execute(
        update(Institution)
        .where(Institution.code == "vse")
        .values(kind=InstitutionKind.SCHOOL)
    )

    response = await client.get("/api/v1/universities")

    assert "vse" not in {row["code"] for row in response.json()}
