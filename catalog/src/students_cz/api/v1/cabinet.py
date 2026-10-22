"""A helper's own profile — reading it, and saving it.

The counterpart to `browse`: the same offers, seen from the side of the person
who owns them.
"""

from fastapi import APIRouter, BackgroundTasks
from sqlalchemy import select

from students_cz.api.deps import (
    IdPath,
    LangDep,
    NotifierDep,
    SessionDep,
    SettingsDep,
    UserDep,
)
from students_cz.api.v1.me import read_me
from students_cz.bot.texts import OWNER_NEW_HELPER, OWNER_NO_SERVICES
from students_cz.db.models import (
    HelperProfile,
    Institution,
    Offer,
    ServiceType,
    Subject,
)
from students_cz.db.models.enums import PublishStatus
from students_cz.schemas import (
    HelperUpsert,
    MeOut,
    MyHelperOut,
    MyOfferOut,
    OfferPause,
)
from students_cz.services import helpers
from students_cz.services.naming import names_by_id
from students_cz.services.notify import quote
from students_cz.services.people import full_name

router = APIRouter()


@router.get("/helper", response_model=MyHelperOut, tags=["helper"])
async def my_helper(session: SessionDep, lang: LangDep, user: UserDep) -> MyHelperOut:
    """Read back the caller's own profile, whatever state it is in.

    Answers with an empty shell rather than 404 when there is no profile yet:
    the screen behind this is a form, and a form that has to branch on a
    missing-resource error to decide whether to render is a form with two
    code paths where one will do.
    """
    helper = await session.get(HelperProfile, user.id)
    if helper is None:
        return MyHelperOut(exists=False)

    # Paused ones too: they are the owner's to switch back on.
    offers = list(
        (
            await session.scalars(
                select(Offer).where(Offer.helper_id == user.id).order_by(Offer.id)
            )
        ).all()
    )

    banned = helper.status == PublishStatus.BANNED
    return MyHelperOut(
        exists=True,
        status=helper.status.value,
        headline=helper.headline,
        about=helper.about,
        work_format=helper.work_format,
        city=helper.city,
        place_note=helper.place_note,
        under_review=helper.reviewed_at is None
        and helper.status in (PublishStatus.PUBLISHED, PublishStatus.BANNED),
        hidden_reason=helper.hidden_reason if banned else None,
        hidden_note=helper.hidden_note if banned else None,
        new_request_alerts=helper.new_request_alerts,
        offers=await _my_offers(session, lang, offers),
    )


@router.patch("/helper/offers/{offer_id}", response_model=MyOfferOut, tags=["helper"])
async def pause_offer(
    offer_id: IdPath,
    payload: OfferPause,
    session: SessionDep,
    lang: LangDep,
    user: UserDep,
) -> MyOfferOut:
    """Pause one offer, or resume it: out of the catalog, kept as it is."""
    offer = await helpers.pause_offer(
        session, user=user, offer_id=offer_id, paused=payload.paused
    )
    [out] = await _my_offers(session, lang, [offer])
    return out


async def _my_offers(session, lang, offers: list[Offer]) -> list[MyOfferOut]:
    # Names for every axis in one round trip each, rather than per offer.
    service_names = await names_by_id(
        session, ServiceType, [o.service_type_id for o in offers], lang
    )
    subject_names = await names_by_id(
        session, Subject, [o.subject_id for o in offers], lang
    )
    institution_names = await names_by_id(
        session, Institution, [o.institution_id for o in offers], lang
    )
    service_codes = {
        service_type_id: code
        for service_type_id, code in (
            await session.execute(
                select(ServiceType.id, ServiceType.code).where(
                    ServiceType.id.in_({o.service_type_id for o in offers} or {0})
                )
            )
        ).all()
    }

    return [
        MyOfferOut(
            id=offer.id,
            service_type_id=offer.service_type_id,
            service_type=service_codes.get(offer.service_type_id, ""),
            service_type_name=service_names.get(offer.service_type_id, ""),
            subject_id=offer.subject_id,
            subject_name=subject_names.get(offer.subject_id),
            institution_id=offer.institution_id,
            institution_name=institution_names.get(offer.institution_id),
            price_amount=float(offer.price_amount)
            if offer.price_amount is not None
            else None,
            price_unit=offer.price_unit,
            langs=list(offer.langs),
            option_ids=list(offer.option_ids),
            note=offer.note,
            turnaround_days=offer.turnaround_days,
            paused=not offer.is_active,
        )
        for offer in offers
    ]


@router.put("/helper", response_model=MeOut, tags=["helper"])
async def upsert_helper(
    payload: HelperUpsert,
    background: BackgroundTasks,
    notifier: NotifierDep,
    session: SessionDep,
    lang: LangDep,
    user: UserDep,
    settings: SettingsDep,
) -> MeOut:
    """Create or replace the caller's helper profile and its offers."""
    saved = await helpers.save_profile(session, user=user, spec=payload, lang=lang)
    if saved.published_now:
        # After the response, like every other message here: Telegram is a
        # third party in the middle of a request somebody is waiting on.
        background.add_task(
            notifier.tell_owner,
            OWNER_NEW_HELPER.format(
                name=quote(full_name(user), 64),
                services=quote(", ".join(saved.services) or OWNER_NO_SERVICES, 200),
            ),
        )
    return await read_me(user, session, lang, settings)
