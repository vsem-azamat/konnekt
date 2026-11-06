"""The helpers konnekt.cz may show, as it shows them.

The site's pages are open to anybody and to search engines, which is a
different audience from the app's: listing a profile in the app is consent to
people in the app. So a helper is on the site only when all of these hold:

- they turned «показывать на konnekt.cz» on themselves (`show_on_site`);
- the profile is listed, and an operator has looked at it since the switch
  went on: turning it on sends the profile back to «Новые анкеты», which says
  so (helpers.py, admin.py). The app goes on listing it meanwhile. An edit
  after that look goes out as it does in the app, unreviewed, until Azamat
  rules otherwise (agora 11910);
- the account is not blocked;
- they offer something now: a name and nothing else is not worth a page.

What leaves here is only what a stranger needs to choose someone. Contact goes
through the app (`/open?start=helper-<id>`), where it is counted and can be
refused, so nothing on a page reaches the person around it.
"""

import re
import unicodedata
from collections.abc import Sequence

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from students_cz.db.models import HelperProfile, Offer, ServiceType, Subject, User
from students_cz.db.models.enums import PublishStatus, UiLang
from students_cz.schemas import Price, PublicHelperCard, PublicHelperPage
from students_cz.services.catalog import avatar_for, display_name, helper_detail
from students_cz.services.naming import names_by_id

# Letters as they read in Latin ones on Czech and English pages: Cyrillic as
# Russian, Ukrainian, Belarusian, Kyrgyz and Kazakh write it, and the Latin
# letters that have no plain letter under a diacritic for NFKD to find.
_LATIN = str.maketrans(
    {
        "ў": "u", "ү": "u", "ұ": "u", "ө": "o", "ң": "ng", "қ": "k", "ғ": "g",
        "ә": "a", "һ": "h",
        "ł": "l", "ß": "ss", "ø": "o", "đ": "d", "æ": "ae", "œ": "oe", "þ": "th",
        "а": "a", "б": "b", "в": "v", "г": "g", "ґ": "g", "д": "d", "е": "e",
        "ё": "e", "є": "ye", "ж": "zh", "з": "z", "и": "i", "і": "i", "ї": "yi",
        "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
        "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
        "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e",
        "ю": "yu", "я": "ya",
    }
)  # fmt: skip
_NOT_A_WORD = re.compile(r"[^a-z0-9]+")


def helper_slug(name: str, user_id: int) -> str:
    """`Анна К.` and 123 read as `anna-k-123`.

    The id is what finds the row; the name is there for a person reading the
    link, and the site redirects to this one when the name part it was asked
    for has gone stale. A name with no letters to spell leaves the id alone.
    """
    latin = name.lower().translate(_LATIN)
    # Czech and the rest: the letter without its diacritic.
    ascii_only = (
        unicodedata.normalize("NFKD", latin).encode("ascii", "ignore").decode("ascii")
    )
    words = _NOT_A_WORD.sub("-", ascii_only).strip("-")
    return f"{words}-{user_id}" if words else str(user_id)


def _on_site() -> Select[tuple[HelperProfile]]:
    has_offer = (
        select(Offer.id)
        .where(Offer.helper_id == HelperProfile.user_id, Offer.is_active.is_(True))
        .exists()
    )
    return (
        select(HelperProfile)
        .join(User, User.id == HelperProfile.user_id)
        .where(
            HelperProfile.show_on_site.is_(True),
            HelperProfile.status == PublishStatus.PUBLISHED,
            HelperProfile.reviewed_at.is_not(None),
            User.is_blocked.is_(False),
            has_offer,
        )
    )


async def is_on_site(session: AsyncSession, user_id: int) -> bool:
    """Whether the site has a page for this helper."""
    found = await session.scalar(
        _on_site()
        .where(HelperProfile.user_id == user_id)
        .with_only_columns(HelperProfile.user_id)
    )
    return found is not None


async def site_helpers(session: AsyncSession, lang: UiLang) -> list[PublicHelperCard]:
    """Everybody on the site, the most proven first."""
    helpers = (
        await session.scalars(
            _on_site()
            .options(selectinload(HelperProfile.user), selectinload(HelperProfile.offers))
            .order_by(
                HelperProfile.deals_count.desc(),
                HelperProfile.rating.desc().nulls_last(),
                HelperProfile.published_at,
                HelperProfile.user_id,
            )
        )
    ).all()
    offers = [o for h in helpers for o in _active(h.offers)]
    services = await names_by_id(
        session, ServiceType, {o.service_type_id for o in offers}, lang
    )
    subjects = await names_by_id(session, Subject, {o.subject_id for o in offers}, lang)
    return [_card(helper, services, subjects) for helper in helpers]


async def site_helper(
    session: AsyncSession, user_id: int, lang: UiLang
) -> PublicHelperPage | None:
    """One helper's page, or `None` when the site has none for them."""
    helper = await session.scalar(
        _on_site()
        .where(HelperProfile.user_id == user_id)
        .options(selectinload(HelperProfile.user))
    )
    if helper is None:
        return None
    # The app's page for the rest, offers and stats as the app words them.
    detail = await helper_detail(session, user_id, lang)
    if detail is None:  # pragma: no cover — listed, as the query above checked
        return None
    avatar = avatar_for(helper.user)
    return PublicHelperPage(
        user_id=user_id,
        slug=helper_slug(detail.name, user_id),
        name=detail.name,
        initials=avatar.initials,
        tone=avatar.tone,
        headline=helper.headline,
        about=helper.about,
        offers=detail.offers,
        stats=detail.stats,
        langs=detail.langs,
        work_format=helper.work_format,
        city=helper.city,
        place_note=helper.place_note,
        rating=float(helper.rating) if helper.rating is not None else None,
        deals_count=helper.deals_count,
    )


def _active(offers: Sequence[Offer]) -> list[Offer]:
    return sorted((o for o in offers if o.is_active), key=lambda o: o.id)


def _card(
    helper: HelperProfile, services: dict[int, str], subjects: dict[int, str]
) -> PublicHelperCard:
    user = helper.user
    offers = _active(helper.offers)
    avatar = avatar_for(user)
    name = display_name(user)
    priced = [o for o in offers if o.price_amount is not None]
    cheapest = min(priced, key=lambda o: o.price_amount) if priced else None
    return PublicHelperCard(
        user_id=user.id,
        slug=helper_slug(name, user.id),
        name=name,
        initials=avatar.initials,
        tone=avatar.tone,
        headline=helper.headline,
        services=_once(services.get(o.service_type_id) for o in offers),
        subjects=_once(subjects.get(o.subject_id) for o in offers if o.subject_id),
        price_from=Price(
            amount=float(cheapest.price_amount),
            currency=cheapest.price_currency,
            unit=cheapest.price_unit,
        )
        if cheapest is not None and cheapest.price_amount is not None
        else None,
        langs=sorted({code for o in offers for code in o.langs}),
        work_format=helper.work_format,
        city=helper.city,
        rating=float(helper.rating) if helper.rating is not None else None,
        deals_count=helper.deals_count,
    )


def _once(names) -> list[str]:
    """Each name once, in the order first met; an untranslated one left out."""
    return list(dict.fromkeys(name for name in names if name))
