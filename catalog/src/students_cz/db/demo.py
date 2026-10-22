"""Plausible content for developing against.

Not fixtures and not tests — this exists so the screens can be judged with
something in them. An empty catalog hides every layout problem worth finding:
a card with no price, a reason line that wraps to three lines, a section with
one avatar instead of three.

    uv run python -m students_cz.db.demo

Idempotent, and it only ever touches rows it created: the exact Telegram ids
listed in PEOPLE, and partner codes prefixed `demo_`.

    uv run python -m students_cz.db.demo --clear
"""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.db.models import (
    AvailabilitySlot,
    HelperProfile,
    Institution,
    Offer,
    Partner,
    PartnerOffer,
    PartnerOfferI18n,
    Placement,
    PlacementEvent,
    ServiceType,
    Subject,
    User,
)
from students_cz.db.models.enums import (
    PayoutModel,
    PlacementSlot,
    PriceUnit,
    PublishStatus,
    UiLang,
    WorkFormat,
)
from students_cz.db.session import dispose_engine, get_sessionmaker

# Demo accounts are numbered from this base. It is a namespace, not a fence:
# real Telegram ids passed 900 million long ago and are well into the billions,
# so deleting "everything at or above the base" would delete the entire user
# table. clear() works from the exact list below and nothing else.
DEMO_TG_BASE = 900_000_000

PEOPLE: list[dict] = [
    {
        "tg": 1,
        "first": "Marek",
        "last": "Novák",
        "username": "marek_teaches",
        "headline": "ČVUT FEL · magistr, 2. ročník",
        "about": (
            "Разбираем твои задачи, не абстрактную теорию. Первые 20 минут "
            "бесплатно — смотрим, где дыра. Онлайн или в Дейвице."
        ),
        "langs": ["cs", "ru", "en"],
        "deals": 38,
        "rating": 4.9,
        "response": 10,
        "place": "Dejvice, u metra",
        "offers": [
            ("tutoring", "matematicka-analyza", "cvut", 600, PriceUnit.HOUR),
            ("tutoring", "linearni-algebra", "cvut", 600, PriceUnit.HOUR),
            ("exam_live_help", None, "cvut", 1500, PriceUnit.HOUR),
            ("entrance_prep", "prijimacky-technicke-vs", "cvut", 700, PriceUnit.HOUR),
        ],
        "free": [(12, 10, 14), (13, 16, 20)],
    },
    {
        "tg": 2,
        "first": "Kateřina",
        "last": "Veselá",
        "username": "katka_fit",
        "headline": "ČVUT FIT · doktorandka",
        "about": "Vedu semináře z matematické analýzy na této katedře.",
        "langs": ["cs", "en"],
        "deals": 21,
        "rating": 5.0,
        "response": 8,
        "offers": [
            ("tutoring", "matematicka-analyza", "cvut", 750, PriceUnit.HOUR),
            ("tutoring", "diskretni-matematika", "cvut", 750, PriceUnit.HOUR),
            ("writing", None, None, 4500, PriceUnit.WORK),
        ],
        "free": [(14, 9, 12)],
    },
    {
        "tg": 3,
        "first": "Ярослав",
        "last": "Панов",
        "username": "yaroslav_mff",
        "headline": "MFF UK · выпускник",
        "about": "Дешевле остальных, потому что набираю отзывы. Математика и физика.",
        "langs": ["ru", "uk", "cs"],
        "deals": 3,
        "rating": None,
        "response": 45,
        "offers": [
            ("tutoring", "matematicka-analyza", None, 450, PriceUnit.HOUR),
            ("tutoring", "fyzika-1", None, 450, PriceUnit.HOUR),
        ],
        "free": [],
    },
    {
        "tg": 4,
        "first": "Ольга",
        "last": "Романюк",
        "username": "olga_nostri",
        "headline": "Прошла нострификацию сама, Praha 6",
        "about": (
            "Знаю список предметов по краям и как выглядят вопросы. "
            "Готовлю к досдаче и к чешскому B2."
        ),
        "langs": ["ru", "uk", "cs"],
        "deals": 14,
        "rating": 4.8,
        "response": 25,
        "offers": [
            ("nostrification", "nostrifikacni-zkousky", None, 550, PriceUnit.HOUR),
            ("language_tutoring", "cestina-b2", None, 500, PriceUnit.HOUR),
        ],
        "free": [(11, 17, 20), (12, 17, 20)],
    },
    {
        "tg": 5,
        "first": "Данияр",
        "last": "Касымов",
        "username": "daniyar_cz",
        "headline": "Čeština B1–C1, готовлю к CCE",
        "about": "14 человек сдали B2 с первого раза. Занимаемся по материалам UJOP.",
        "langs": ["ru", "cs"],
        "deals": 27,
        "rating": 4.9,
        "response": 15,
        "offers": [
            ("language_tutoring", "cestina-b2", None, 400, PriceUnit.HOUR),
            ("language_tutoring", "cestina-b1", None, 400, PriceUnit.HOUR),
            ("language_tutoring", "cestina-konverzace", None, 350, PriceUnit.HOUR),
        ],
        "free": [(10, 18, 21)],
    },
    {
        "tg": 6,
        "first": "Petra",
        "last": "Dvořáková",
        "username": "petra_vse",
        "headline": "VŠE · Finance a účetnictví",
        "about": "Mikro, makro, účetnictví. Připravím na zkoušku za dva týdny.",
        "langs": ["cs", "en", "ru"],
        "deals": 9,
        "rating": 4.7,
        "response": 30,
        "offers": [
            ("tutoring", "mikroekonomie", "vse", 550, PriceUnit.HOUR),
            ("tutoring", "makroekonomie", "vse", 550, PriceUnit.HOUR),
            ("tutoring", "ucetnictvi", "vse", 600, PriceUnit.HOUR),
            ("entrance_prep", "prijimacky-ekonomicke-vs", "vse", 650, PriceUnit.HOUR),
        ],
        "free": [(13, 14, 18)],
    },
]

PARTNERS: list[dict] = [
    {
        "code": "demo_insurance",
        "name": "Demo Insurance",
        "logo_text": "PV",
        "logo_bg": "#dff0e4",
        "url": "https://example.com/insurance",
        "texts": {
            "ru": (
                "Комплексная страховка на 12 месяцев",
                "подходит для продления ВНЖ",
                "от 8 900",
                "Для ВНЖ нужна на весь срок пребывания. Продлевать заранее — "
                "при подаче смотрят дату окончания.",
            ),
            "cs": (
                "Komplexní pojištění na 12 měsíců",
                "vhodné pro prodloužení pobytu",
                "od 8 900",
                "Pojištění musí pokrývat celou dobu pobytu.",
            ),
            "en": (
                "Comprehensive health insurance, 12 months",
                "accepted for residence permit renewal",
                "from 8,900",
                "It has to cover your whole stay; renew before you apply.",
            ),
            "uk": (
                "Комплексна страховка на 12 місяців",
                "підходить для продовження ВНП",
                "від 8 900",
                "Потрібна на весь строк перебування.",
            ),
        },
        "placements": [
            (PlacementSlot.SCREEN_LIFE, {}, 10),
            (PlacementSlot.PROFILE_FOOTER, {"month": [8, 9]}, 5),
        ],
    },
    {
        "code": "demo_translation",
        "name": "Demo Sworn Translation",
        "logo_text": "SP",
        "logo_bg": "#e4e1f6",
        "url": "https://example.com/translation",
        "texts": {
            "ru": (
                "Судебный перевод аттестата",
                "soudní překladatel · 2 рабочих дня",
                "450 Kč",
                "Нострификация почти всегда упирается в перевод документов.",
            ),
            "cs": (
                "Soudní překlad vysvědčení",
                "soudní překladatel · 2 pracovní dny",
                "450 Kč",
                "Nostrifikace se skoro vždy zasekne na překladu.",
            ),
            "en": (
                "Sworn translation of your certificate",
                "court translator · 2 working days",
                "450 Kč",
                "Nostrification almost always stalls on document translation.",
            ),
            "uk": (
                "Судовий переклад атестата",
                "soudní překladatel · 2 робочі дні",
                "450 Kč",
                "Нострифікація майже завжди впирається у переклад.",
            ),
        },
        "placements": [
            (
                PlacementSlot.SCREEN_NOSTRIFICATION,
                {"service_type": "nostrification"},
                20,
            ),
            (PlacementSlot.SCREEN_LIFE, {}, 8),
        ],
    },
    {
        "code": "demo_language_visa",
        "name": "Demo Language School",
        "logo_text": "JK",
        "logo_bg": "#fde8da",
        "url": "https://example.com/course",
        "texts": {
            "ru": (
                "Годовой курс чешского с визой",
                "набор до 15 сентября · Прага, Брно",
                "от 74 000",
                "Вылетел из вуза — основание для пребывания пропадает вместе "
                "со студенческим статусом.",
            ),
            "cs": (
                "Roční kurz češtiny s vízem",
                "zápis do 15. září · Praha, Brno",
                "od 74 000",
                "Ukončené studium znamená ztrátu účelu pobytu.",
            ),
            "en": (
                "One-year Czech course with a visa",
                "enrolment until 15 September · Prague, Brno",
                "from 74,000",
                "Dropping out of university ends your grounds for staying.",
            ),
            "uk": (
                "Річний курс чеської з візою",
                "набір до 15 вересня · Прага, Брно",
                "від 74 000",
                "Відрахування забирає підставу для перебування.",
            ),
        },
        "placements": [
            (PlacementSlot.SCREEN_LIFE, {}, 9),
            (PlacementSlot.SCREEN_LANGUAGES, {}, 15),
        ],
    },
]


def demo_tg_ids() -> list[int]:
    """Exactly the accounts this script creates, and no others."""
    return [DEMO_TG_BASE + spec["tg"] for spec in PEOPLE]


async def clear(session: AsyncSession) -> None:
    users = (
        await session.scalars(select(User).where(User.tg_id.in_(demo_tg_ids())))
    ).all()
    ids = [u.id for u in users]
    if ids:
        await session.execute(delete(Offer).where(Offer.helper_id.in_(ids)))
        await session.execute(
            delete(AvailabilitySlot).where(AvailabilitySlot.helper_id.in_(ids))
        )
        await session.execute(delete(HelperProfile).where(HelperProfile.user_id.in_(ids)))
        await session.execute(delete(User).where(User.id.in_(ids)))

    partners = (
        await session.scalars(select(Partner).where(Partner.code.like("demo_%")))
    ).all()
    for partner in partners:
        offer_ids = (
            await session.scalars(
                select(PartnerOffer.id).where(PartnerOffer.partner_id == partner.id)
            )
        ).all()
        if offer_ids:
            placement_ids = (
                await session.scalars(
                    select(Placement.id).where(Placement.offer_id.in_(offer_ids))
                )
            ).all()
            if placement_ids:
                await session.execute(
                    delete(PlacementEvent).where(
                        PlacementEvent.placement_id.in_(placement_ids)
                    )
                )
        await session.delete(partner)
    await session.commit()


async def populate(session: AsyncSession) -> tuple[int, int]:
    subjects = {s.slug: s.id for s in (await session.scalars(select(Subject))).all()}
    services = {s.code: s.id for s in (await session.scalars(select(ServiceType))).all()}
    institutions = {
        i.code: i.id for i in (await session.scalars(select(Institution))).all()
    }
    if not services:
        raise SystemExit(
            "reference data missing — run `python -m students_cz.db.seed` first"
        )

    # Anchored to a fixed month so "free on the 12th" stays in the future
    # rather than drifting into the past a week after seeding.
    base = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    base = (base.replace(day=1) + timedelta(days=32)).replace(day=1)

    made = 0
    for spec in PEOPLE:
        tg_id = DEMO_TG_BASE + spec["tg"]
        user = await session.scalar(select(User).where(User.tg_id == tg_id))
        if user is None:
            user = User(tg_id=tg_id, first_name=spec["first"])
            session.add(user)
        user.last_name = spec["last"]
        user.tg_username = spec["username"]
        user.ui_lang = UiLang.CS if spec["langs"][0] == "cs" else UiLang.RU
        user.spoken_langs = spec["langs"]
        await session.flush()

        helper = await session.get(HelperProfile, user.id)
        if helper is None:
            helper = HelperProfile(user_id=user.id)
            session.add(helper)
        helper.status = PublishStatus.PUBLISHED
        helper.published_at = helper.published_at or datetime.now(UTC) - timedelta(
            days=400
        )
        helper.headline = spec["headline"]
        helper.about = spec["about"]
        helper.deals_count = spec["deals"]
        helper.rating = spec["rating"]
        helper.response_minutes_avg = spec["response"]
        helper.place_note = spec.get("place")
        helper.work_format = WorkFormat.BOTH
        await session.flush()

        await session.execute(delete(Offer).where(Offer.helper_id == user.id))
        for service_code, subject_slug, inst_code, price, unit in spec["offers"]:
            # Silently dropping an unknown code produced demo helpers with no
            # institution, which then made every "same faculty" reason on the
            # results screen quietly wrong. A missing reference is a broken
            # seed, so say so.
            if subject_slug and subject_slug not in subjects:
                raise SystemExit(f"demo references unknown subject {subject_slug!r}")
            if inst_code and inst_code not in institutions:
                raise SystemExit(f"demo references unknown institution {inst_code!r}")
            session.add(
                Offer(
                    helper_id=user.id,
                    service_type_id=services[service_code],
                    subject_id=subjects.get(subject_slug) if subject_slug else None,
                    institution_id=institutions.get(inst_code) if inst_code else None,
                    price_amount=price,
                    price_unit=unit,
                    langs=spec["langs"],
                )
            )

        await session.execute(
            delete(AvailabilitySlot).where(AvailabilitySlot.helper_id == user.id)
        )
        for day, start, end in spec["free"]:
            session.add(
                AvailabilitySlot(
                    helper_id=user.id,
                    period=Range(
                        base.replace(day=day, hour=start),
                        base.replace(day=day, hour=end),
                        bounds="[)",
                    ),
                )
            )
        made += 1

    placements = 0
    for spec in PARTNERS:
        partner = await session.scalar(
            select(Partner).where(Partner.code == spec["code"])
        )
        if partner is None:
            partner = Partner(code=spec["code"], payout_model=PayoutModel.CPC)
            session.add(partner)
        partner.name = spec["name"]
        partner.is_active = True
        await session.flush()

        offer = await session.scalar(
            select(PartnerOffer).where(PartnerOffer.partner_id == partner.id)
        )
        if offer is None:
            offer = PartnerOffer(partner_id=partner.id, url=spec["url"])
            session.add(offer)
        offer.url = spec["url"]
        offer.logo_text = spec["logo_text"]
        offer.logo_bg = spec["logo_bg"]
        offer.is_active = True
        await session.flush()

        for lang, (title, subtitle, price, note) in spec["texts"].items():
            existing = await session.scalar(
                select(PartnerOfferI18n).where(
                    PartnerOfferI18n.offer_id == offer.id,
                    PartnerOfferI18n.lang == UiLang(lang),
                )
            )
            if existing is None:
                existing = PartnerOfferI18n(offer_id=offer.id, lang=UiLang(lang))
                session.add(existing)
            existing.title = title
            existing.subtitle = subtitle
            existing.price_text = price
            existing.context_note = note

        await session.execute(delete(Placement).where(Placement.offer_id == offer.id))
        for slot, conditions, priority in spec["placements"]:
            session.add(
                Placement(
                    offer_id=offer.id,
                    slot=slot,
                    conditions=conditions,
                    priority=priority,
                )
            )
            placements += 1

    await session.commit()
    return made, placements


async def run(reset: bool) -> None:
    async with get_sessionmaker()() as session:
        if reset:
            await clear(session)
            print("demo data cleared")
        else:
            people, placements = await populate(session)
            print(f"helpers    : {people}")
            print(f"placements : {placements}")
    await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clear", action="store_true", help="remove demo rows")
    asyncio.run(run(parser.parse_args().clear))
