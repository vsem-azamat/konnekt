from enum import StrEnum

from sqlalchemy import Enum as SAEnum


def pg_enum(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """Native Postgres enum storing the member values, not the member names.

    ``values_callable`` is required: without it SQLAlchemy writes member NAMES
    (``RENT``) while the Python code compares against values (``rent``), so
    hand-written SQL stops matching what the ORM reads.
    """
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=True,
        values_callable=lambda e: [m.value for m in e],
        create_constraint=False,
    )


class UiLang(StrEnum):
    """Interface languages.

    Separate from the languages people teach in — there can be more of those.
    Note the standard codes: the legacy bot used ``cz``/``ua``, which have to be
    mapped to ``cs``/``uk`` during the data import.
    """

    RU = "ru"
    CS = "cs"
    EN = "en"
    UK = "uk"


class ContentLang(StrEnum):
    """Language a user-written text is in. ``xx`` covers mixed and undetected."""

    RU = "ru"
    CS = "cs"
    EN = "en"
    UK = "uk"
    OTHER = "xx"


class PublishStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    PUBLISHED = "published"
    HIDDEN = "hidden"
    BANNED = "banned"


class ServiceGroup(StrEnum):
    """Which shelf a kind of help sits on.

    Both screens that show these tiles — the catalog's front door and the
    screen where someone offers a service — render the same list grouped by
    this. ``life`` is the help that has no subject and no institution: the
    paperwork of staying in the country rather than of studying.

    Closed on purpose. Group names are translated on the client, the way
    ``work_format`` and ``price_unit`` are; see docs/data-model.md.
    """

    STUDY = "study"
    ENTRANCE = "entrance"
    LIFE = "life"


class ServiceForm(StrEnum):
    """The shape of the form that offers a kind of help.

    A different question from ``ServiceGroup``, and deliberately a separate
    column. The group is for the student browsing — *what do I need*. The shape
    is for the person offering — *what do we ask you*. They nearly coincide, and
    the places they do not are the ones that matter: help *during* an exam sits
    on the entrance shelf, where a student compares it with exam preparation,
    and its form has nothing to do with teaching.

    ``work`` is always remote, so its form does not ask how you work. Lessons
    and errands ask the same three answers under different words; see
    docs/data-model.md.
    """

    LESSON = "lesson"
    WORK = "work"
    ERRAND = "errand"


class NodeKind(StrEnum):
    """Position in a tree. Offers and pickers hold leaves; a group is reached
    only by the parser, through its synonyms, and searched as what it holds."""

    GROUP = "group"
    LEAF = "leaf"


class InstitutionKind(StrEnum):
    UNIVERSITY = "university"
    FACULTY = "faculty"
    SCHOOL = "school"
    EXAM_BODY = "exam_body"
    OTHER = "other"


class WorkFormat(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    BOTH = "both"


class PriceUnit(StrEnum):
    HOUR = "hour"
    LESSON = "lesson"
    WORK = "work"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    SEMESTER = "semester"
    ITEM = "item"
    NEGOTIABLE = "negotiable"


class RequestStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"
    EXPIRED = "expired"


class ResponseStatus(StrEnum):
    SENT = "sent"
    READ = "read"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class ItemKind(StrEnum):
    RENT = "rent"
    SALE = "sale"


class ItemCondition(StrEnum):
    NEW = "new"
    GOOD = "good"
    USED = "used"


class ItemStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RESERVED = "reserved"
    HIDDEN = "hidden"
    ARCHIVED = "archived"


class MaterialKind(StrEnum):
    NOTES = "notes"
    PAST_EXAMS = "past_exams"
    TEMPLATE = "template"
    COURSE = "course"
    OTHER = "other"


class MaterialAccess(StrEnum):
    """Payments are deferred, so only ``free`` and ``on_request`` are reachable
    today. ``paid`` exists so adding a provider later is not a schema change."""

    FREE = "free"
    ON_REQUEST = "on_request"
    PAID = "paid"


class PayoutModel(StrEnum):
    CPC = "cpc"
    CPL = "cpl"
    FIXED = "fixed"


class PlacementSlot(StrEnum):
    """Where a partner block may appear. Grows as screens are added."""

    SCREEN_LIFE = "screen_life"
    SCREEN_NOSTRIFICATION = "screen_nostrification"
    SCREEN_LANGUAGES = "screen_languages"
    SCREEN_SEARCH_EMPTY = "screen_search_empty"
    AFTER_REQUEST_CREATED = "after_request_created"
    PROFILE_FOOTER = "profile_footer"


class PlacementEventKind(StrEnum):
    IMPRESSION = "impression"
    CLICK = "click"


class ModerationVerdict(StrEnum):
    AUTO_OK = "auto_ok"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class ModeratedEntity(StrEnum):
    HELPER_PROFILE = "helper_profile"
    OFFER = "offer"
    REQUEST = "request"
    ITEM = "item"
    MATERIAL = "material"


class UserEventKind(StrEnum):
    """What someone did.

    Deliberately coarse. A log nobody can query is a log nobody reads, and the
    detail belongs in `payload` where it costs nothing to add a field later.
    """

    BOT_START = "bot_start"
    BOT_MESSAGE = "bot_message"
    BOT_BLOCKED = "bot_blocked"
    BOT_UNBLOCKED = "bot_unblocked"
    APP_OPEN = "app_open"
    SEARCH = "search"
    HELPER_VIEW = "helper_view"
    CONTACT = "contact"
    REQUEST_CREATED = "request_created"
    REQUEST_RESPONDED = "request_responded"
    RESPONSE_ACCEPTED = "response_accepted"
    PROFILE_PUBLISHED = "profile_published"
