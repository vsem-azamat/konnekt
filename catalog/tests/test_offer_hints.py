"""One-tap suggestions on the prices screen: a few prices and a few subjects.

Ours until there are enough real prices to take them from, and none for the
«Документы и жизнь» group, whose listing is going paid.
"""

import pytest

from students_cz.services.offer_hints import from_prices

from .conftest import auth_header


def test_too_few_prices_give_our_own_numbers() -> None:
    assert from_prices([500, 600, 700, 800], "lesson") == [300, 400, 500]
    assert from_prices([], "work") == [1500, 3000, 5000]
    assert from_prices([], "errand") == [300, 500, 1000]


def test_enough_prices_give_their_quartiles_rounded() -> None:
    # Five priced offers are enough to stop guessing: the middle half of what
    # people actually ask, rounded to 50 so a chip reads like a price.
    hints = from_prices([400, 450, 500, 600, 800], "lesson")
    assert hints == [450, 500, 600]


def test_equal_quartiles_collapse_to_distinct_chips() -> None:
    assert from_prices([500, 500, 500, 500, 500], "lesson") == [500]


@pytest.mark.asyncio
async def test_service_types_carry_price_and_subject_hints(client) -> None:
    body = (
        await client.get("/api/v1/taxonomy/service-types", headers=auth_header(90190))
    ).json()
    by_code = {s["code"]: s for s in body}

    assert len(by_code["writing"]["price_hints"]) >= 1
    # Going paid: no anchor offered until Azamat says how they are listed.
    assert by_code["insurance"]["price_hints"] == []
    assert by_code["insurance"]["subject_hints"] == []

    tutoring = [hint["slug"] for hint in by_code["tutoring"]["subject_hints"]]
    assert tutoring[:2] == ["matematicka-analyza", "linearni-algebra"]
    names = {hint["slug"]: hint["name"] for hint in by_code["tutoring"]["subject_hints"]}
    assert names["matematicka-analyza"] == "Математический анализ"
    languages = [hint["slug"] for hint in by_code["language_tutoring"]["subject_hints"]]
    assert languages[0] == "cestina-b1"
