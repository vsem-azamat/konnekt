"""Response and request shapes for the mini app.

Two conventions worth stating once:

* **Data** is localised here; **chrome** is not. Names of subjects, faculties
  and service types arrive already in the caller's language, because those
  translations live in the database. Sentences the interface composes do not:
  they arrive as a `Phrase` — a code plus parameters — and the client renders
  them. Czech has four plural forms and Russian's are differently shaped; that
  belongs in the presentation layer, which has the rules, not in an API that
  would have to reimplement them.
* Screens are assembled server-side. `/home` returns the whole home screen in
  one response rather than making a phone on mobile data issue six requests.
"""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from students_cz.db.models.enums import (
    HIDE_NOTE_MAX,
    HideReason,
    PriceUnit,
    PublishStatus,
    ServiceForm,
    ServiceGroup,
    UiLang,
    WorkFormat,
)

# Matches ARRAY(String(8)) in the schema; a longer code cannot be stored, and a
# request carrying one should be told so rather than fail at the database.
LangCode = Annotated[str, StringConstraints(min_length=2, max_length=8)]


class Phrase(BaseModel):
    """A sentence for the client to render, not a sentence.

    `{"code": "reason.same_exam", "params": {"taught": 40, "passed": 38}}`
    becomes "Готовил к этому же экзамену 40 человек, сдали 38" — with correct
    plural agreement, which only the client can produce.
    """

    code: str
    params: dict[str, str | int] = Field(default_factory=dict)


class Price(BaseModel):
    amount: float | None = None
    currency: str = "CZK"
    unit: PriceUnit = PriceUnit.HOUR


class Avatar(BaseModel):
    """Enough to draw the little circle without fetching anything.

    Telegram avatar URLs expire, so a monogram is the fallback rather than a
    broken image. The colour is derived from the user id, which keeps the same
    person the same colour across screens.
    """

    # Carried so the client has a stable key for a list of faces. Two people
    # with the same initials and the same tone are not rare.
    id: int
    initials: str
    tone: int = Field(ge=0, le=5)
    # Nullable, but not optional: the key is always in the response, and a
    # default would tell the generated client otherwise. See `HomeSection`.
    photo_url: str | None


# ── taxonomy ────────────────────────────────────────────────────────────


class ServiceOptionOut(BaseModel):
    """One line of what a kind of help covers, in the caller's language."""

    id: int
    code: str
    label: str


class ServiceTypeOut(BaseModel):
    id: int
    code: str
    # The enum, not `str`: this is what puts `"enum": [...]` in the OpenAPI
    # document, so the generated client gets a union of three literals instead
    # of `string` and a typo becomes a type error. The client translates it —
    # see docs/data-model.md for why this one is not in the database's own
    # i18n tables.
    group: ServiceGroup
    # Which questions to ask, as against which shelf to draw it on. The two are
    # different axes; see docs/data-model.md.
    form_shape: ServiceForm
    name: str
    hint: str | None = None
    requires_subject: bool
    requires_institution: bool
    # Which of the six tile colours, picked here so a category wears the same
    # one on the home screen and on the screen where it is offered. Derived
    # from position in the same order both endpoints return.
    tone: int = Field(ge=0, le=5)
    # What the price is per, unless the person says otherwise. Tutoring is by
    # the hour and a thesis is by the job; without this the form has to guess,
    # and a guess here is a price that reads as ten times too much.
    default_price_unit: PriceUnit | None
    # What this kind of help can cover. Empty for the shapes that describe
    # themselves through a subject and a price — but always present, because a
    # default here makes the field optional in OpenAPI and the generated client
    # then types it `| undefined` for a key every response carries. See
    # `Avatar.photo_url`.
    options: list[ServiceOptionOut]


class SubjectOut(BaseModel):
    id: int
    slug: str
    name: str
    parent_id: int | None = None
    has_children: bool = False
    external_code: str | None = None
    offers_count: int = 0


class InstitutionOut(BaseModel):
    id: int
    code: str
    name: str
    short_name: str | None = None
    city: str | None = None
    parent_id: int | None = None
    faculties: list["InstitutionOut"] = Field(default_factory=list)


class LanguageOut(BaseModel):
    code: str
    name: str


# ── catalog ─────────────────────────────────────────────────────────────


class OfferOut(BaseModel):
    id: int
    service_type: str
    service_type_name: str
    subject: str | None = None
    institution: str | None = None
    price: Price
    langs: list[str]
    work_format: WorkFormat
    # Already translated, because they are names we author. The person's own
    # words are `note`, which is theirs and stays in the language they wrote it.
    # Neither carries a default, for the reason `ServiceTypeOut.options` gives.
    options: list[str]
    note: str | None
    # Only a written work has one; the rest send `null`, which reads as "we
    # will agree" there and as "nobody asked" everywhere else.
    turnaround_days: int | None


class HelperCardOut(BaseModel):
    """One row in the results list."""

    user_id: int
    name: str
    avatar: Avatar
    affiliation: str | None = None
    # The service this card was found for, by name. Drawn where the line under
    # the name is empty: somebody who published without one is otherwise a
    # name and nothing else.
    service: str | None = None
    # The subject of the offer the card stands for, when it has one: the line
    # that comes next when there is no headline.
    subject: str | None = None
    price: Price | None = None
    # The line under the name explaining why this person is in the list at all.
    # Sometimes it says the match is weak; that is the point.
    reason: Phrase | None = None
    availability: Phrase | None = None
    rating: float | None = None
    deals_count: int = 0
    langs: list[str] = Field(default_factory=list)


class Stat(BaseModel):
    code: str
    value: str


class ReviewOut(BaseModel):
    author: str
    created_on: date
    text: str


class HelperDetailOut(BaseModel):
    user_id: int
    name: str
    avatar: Avatar
    affiliation: str | None = None
    about: str | None = None
    headline: str | None = None
    stats: list[Stat]
    offers: list[OfferOut]
    langs: list[str]
    work_format: WorkFormat
    place_note: str | None = None
    free_slots: list[datetime] = Field(default_factory=list)
    reviews: list[ReviewOut] = Field(default_factory=list)
    # Everything the client needs to compose the prefilled first message. The
    # wording is the client's; the facts are ours.
    intro_context: dict[str, str | int] = Field(default_factory=dict)
    telegram_url: str | None = None


class ContactOut(BaseModel):
    """Where to continue the conversation."""

    telegram_url: str


# ── search ──────────────────────────────────────────────────────────────


class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class Chip(BaseModel):
    """One piece of what we understood, shown back for correction."""

    kind: str  # subject | institution | service_type | deadline | budget | lang
    label: str
    value: str | int | None = None
    confidence: float = 1.0


class ClarifyOption(BaseModel):
    code: str
    tone: int = 0


class Clarify(BaseModel):
    """One question, asked only when the answer changes the result set.

    Never a wall of filters — if we cannot justify asking, we do not ask.
    """

    code: str
    options: list[ClarifyOption]


class AlsoSubject(BaseModel):
    """A subject the parser guessed at but would not search by."""

    subject_id: int
    label: str


class ParseOut(BaseModel):
    chips: list[Chip]
    clarify: Clarify | None = None
    matches: int
    # What the embedder proposed and was not sure enough to filter by. The
    # screen shows it as its own section, named — a guess that narrows a search
    # shows nobody, and a guess that says it is one costs the reader nothing.
    also: AlsoSubject | None
    # Set when nothing was recognised, so the screen can say so plainly
    # instead of showing an empty list and looking broken.
    note: Phrase | None = None


class SearchFilters(BaseModel):
    subject_id: int | None = None
    institution_id: int | None = None
    service_type_id: int | None = None
    max_price: float | None = None
    langs: list[str] = Field(default_factory=list)
    work_format: WorkFormat | None = None


class SearchOut(BaseModel):
    total: int
    filters: SearchFilters
    chips: list[Chip]
    results: list[HelperCardOut]


# ── home ────────────────────────────────────────────────────────────────


class HomeSection(BaseModel):
    kind: str  # service_type | item_category
    code: str
    # Sections arrive in group order, so the client draws a heading whenever
    # this changes. Typed as the enum for the same reason as `ServiceTypeOut`.
    group: ServiceGroup
    name: str
    hint: str | None = None
    tone: int
    count: int
    live_count: int | None = None
    # No default. A default makes the field optional in the OpenAPI document,
    # and the generated client then types it `Avatar[] | undefined` — which is
    # a lie about a response that always carries the key, and one every call
    # site has to apologise for. An empty list is passed explicitly instead.
    avatars: list[Avatar]


class HomeOut(BaseModel):
    people: list[HomeSection]
    things: list[HomeSection]


# ── partners ────────────────────────────────────────────────────────────


class PlacementOut(BaseModel):
    id: int
    title: str
    subtitle: str | None = None
    price_text: str | None = None
    context_note: str | None = None
    logo_text: str | None = None
    logo_bg: str | None = None
    url: str


# ── user ────────────────────────────────────────────────────────────────


class MeOut(BaseModel):
    id: int
    tg_id: int
    name: str
    username: str | None = None
    avatar: Avatar
    ui_lang: UiLang
    spoken_langs: list[str]
    city: str | None = None
    institution: InstitutionOut | None = None
    is_helper: bool
    helper_status: str | None = None
    # One of the console's operators. See docs/architecture.md.
    is_admin: bool


class MeUpdate(BaseModel):
    ui_lang: UiLang | None = None
    # Bounds mirror the columns: an over-long value would otherwise reach
    # Postgres and come back as a 500 rather than a validation error.
    spoken_langs: list[LangCode] | None = Field(default=None, max_length=12)
    city: str | None = Field(default=None, max_length=96)
    institution_id: int | None = None


# ── becoming a helper ───────────────────────────────────────────────────


class OfferIn(BaseModel):
    service_type_id: int
    subject_id: int | None = None
    institution_id: int | None = None
    price_amount: float | None = Field(default=None, ge=0, le=1_000_000)
    price_unit: PriceUnit = PriceUnit.HOUR
    langs: list[LangCode] = Field(default_factory=list, max_length=12)
    # Which lines of this service type's checklist. Ids the client read from
    # `/taxonomy/service-types`; anything not belonging to this service type is
    # dropped rather than stored, so a stale client cannot attach one kind of
    # help's checklist to another.
    option_ids: list[int] = Field(default_factory=list, max_length=32)
    note: str | None = Field(default=None, max_length=600)
    # A year is the outer bound of anything a student would wait for, and the
    # form offers five presets well inside it. `None` is an answer: the two of
    # them will agree.
    turnaround_days: int | None = Field(default=None, ge=1, le=365)
    # Kept out of the catalog without being removed. Left out, a row keeps
    # what it had: a form that does not know about pausing must not resume.
    paused: bool = False


class HelperUpsert(BaseModel):
    headline: str | None = Field(default=None, max_length=160)
    about: str | None = Field(default=None, max_length=4000)
    raw_intro: str | None = Field(default=None, max_length=4000)
    work_format: WorkFormat = WorkFormat.BOTH
    city: str | None = Field(default=None, max_length=96)
    place_note: str | None = Field(default=None, max_length=240)
    # A person offers a handful of things, not a catalogue. The cap keeps one
    # request from writing tens of thousands of rows in a single transaction.
    offers: list[OfferIn] = Field(default_factory=list, max_length=60)
    publish: bool = False
    # Whether the bot writes about new requests this profile could answer.
    # Left alone when absent, like every field here.
    new_request_alerts: bool = True


class MyOfferOut(BaseModel):
    """One row of the caller's own offers, ready to be edited and sent back.

    Both the id and the name of every axis: the id is what `HelperUpsert`
    wants, the name is what the person reads. `OfferOut` carries only the
    names, which is right for a card and useless for a form.
    """

    id: int
    service_type_id: int
    service_type: str
    service_type_name: str
    subject_id: int | None = None
    subject_name: str | None = None
    institution_id: int | None = None
    institution_name: str | None = None
    price_amount: float | None = None
    price_unit: PriceUnit = PriceUnit.HOUR
    langs: list[str] = Field(default_factory=list)
    option_ids: list[int]
    note: str | None
    turnaround_days: int | None
    paused: bool = False


class OfferPause(BaseModel):
    paused: bool


# Where the offer screen was opened from: the app's own ways in, and `link`
# for a bot or chat button that opens it directly. Named, not free text, so
# the log holds a short list somebody can count rather than whatever was sent.
OfferEntry = Literal["home", "tab", "profile", "results", "my-helper", "link", "other"]


class OfferOpened(BaseModel):
    source: OfferEntry


class MyHelperOut(BaseModel):
    """The caller's own profile, draft or hidden included.

    `/helpers/{id}` deliberately refuses anything unpublished, which is
    correct for the catalog and leaves someone with a draft unable to read
    back what they wrote. This is the other door.
    """

    exists: bool
    status: str | None = None
    headline: str | None = None
    about: str | None = None
    work_format: WorkFormat = WorkFormat.BOTH
    city: str | None = None
    place_note: str | None = None
    offers: list[MyOfferOut] = Field(default_factory=list)
    # Listed, or hidden by an operator, and not looked at since it last
    # changed: «на проверке». Listing does not wait for it.
    under_review: bool = False
    # Only while an operator keeps it hidden.
    hidden_reason: HideReason | None = None
    hidden_note: str | None = None
    # The bot writes about new requests the profile could answer.
    new_request_alerts: bool = True


# ── requests ────────────────────────────────────────────────────────────


class RequestCreate(BaseModel):
    text: str = Field(min_length=3, max_length=2000)
    subject_id: int | None = None
    institution_id: int | None = None
    service_type_id: int | None = None
    deadline_on: date | None = None
    budget_max: float | None = Field(default=None, ge=0, le=1_000_000)
    langs: list[LangCode] = Field(default_factory=list, max_length=12)
    # What the feed's «Онлайн», «Офлайн» and city chips narrow by. `null`, a
    # chip taken off, is either; a city is dropped for help given online.
    work_format: WorkFormat | None = None
    city: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=96)
    ] = None


class RequestBase(BaseModel):
    """What a request is, to anyone looking at it."""

    id: int
    text: str
    subject: str | None = None
    institution: str | None = None
    service_type: str | None = None
    deadline_on: date | None = None
    status: str
    created_at: datetime


class RequestOut(RequestBase):
    """Your own request. Who answered is the whole point of the screen."""

    # The ids beside the names in RequestBase: what the catalog's /search
    # takes to show who else could help.
    subject_id: int | None = None
    service_type_id: int | None = None
    responses_count: int = 0
    responders: list[Avatar] = Field(default_factory=list)
    # How many people /search lists on subject_id and service_type_id, the
    # author aside. Counted only while it is open; 0 after.
    helpers_seeing: int = 0
    work_format: WorkFormat = WorkFormat.BOTH
    city: str | None = None
    expires_at: datetime | None = None
    closed_at: datetime | None = None


class FeedRequestOut(RequestBase):
    """A request as a helper sees it.

    Deliberately not a subclass of RequestOut: how many people have already
    answered, and who they are, is the competition's business and not this
    reader's. A helper who can see "3 answers already" simply skips those,
    which is the opposite of what the feed is for — and inheriting the fields
    to blank them would still leave them in the schema.
    """

    author: Avatar
    author_name: str
    budget: Price | None = None
    langs: list[str] = Field(default_factory=list)
    # Why this request surfaced: the same subject you teach, your faculty, or
    # simply that it is new. Rendered by the client, like every other Phrase.
    reason: Phrase | None = None
    # The reader's own price for an offer of theirs fitting the request, to
    # start an answer from. None when none fits, or those that do are priced
    # in different units.
    suggested_price: Price | None = None
    # «По твоим услугам» rather than «Остальные»: on a subject or a kind of
    # help the reader offers. Their school alone does not make it theirs.
    on_my_services: bool = False
    # Already answered by the reader: «Отклик отправлен».
    responded: bool = False
    work_format: WorkFormat = WorkFormat.BOTH
    city: str | None = None


class FacetOut(BaseModel):
    id: int
    name: str
    count: int


class FormatCounts(BaseModel):
    """`both` counts under each."""

    online: int
    offline: int


class CityCount(BaseModel):
    name: str
    count: int


class BudgetCount(BaseModel):
    """Requests whose budget is at most `amount`; none named is in no step."""

    amount: int
    count: int


class FeedFacetsOut(BaseModel):
    """The numbers on the chips over the feed, each over the whole feed.

    `subjects` are shelves («Математика»), which `subject_id` on the feed
    takes as everything they hold.
    """

    all: int
    mine: int
    subjects: list[FacetOut]
    service_types: list[FacetOut]
    formats: FormatCounts
    cities: list[CityCount]
    budget_upto: list[BudgetCount]


class ResponseCreate(BaseModel):
    # Validated after stripping, below: min_length alone sees the raw string,
    # so "   " passes it and lands in the database as "".
    message: str = Field(max_length=1000)
    price_amount: float | None = Field(default=None, ge=0, le=1_000_000)
    price_unit: PriceUnit | None = None

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("write at least a few words")
        return stripped


class ResponseOut(BaseModel):
    id: int
    request_id: int
    helper_id: int
    name: str
    avatar: Avatar
    username: str | None = None
    affiliation: str | None = None
    rating: float | None = None
    deals_count: int = 0
    message: str
    price: Price | None = None
    status: str
    created_at: datetime


class AdsInfo(BaseModel):
    """What the ads page needs from us: who a business writes to, if anyone."""

    contact_url: str | None


# ── the console ─────────────────────────────────────────────────────────


class AdminProfile(BaseModel):
    user_id: int
    name: str
    # «Новые анкеты» holds hidden ones too, once their owner has changed them.
    status: PublishStatus
    services: list[str]
    published_at: datetime


class AdminRequest(BaseModel):
    id: int
    text: str
    created_at: datetime


class AdminSearch(BaseModel):
    text: str
    times: int
    last_at: datetime


class AdminCounts(BaseModel):
    profiles_week: int
    # Listed profiles no operator has kept or hidden yet, however old.
    profiles_to_review: int
    hidden: int
    requests_week: int
    unanswered: int
    failed_searches: int


class AdminCatalog(BaseModel):
    """The catalog as the operator reads it. See docs/architecture.md."""

    # Listed profiles waiting for an operator, newest first; `hidden` are the
    # ones an operator took out.
    profiles: list[AdminProfile]
    hidden: list[AdminProfile]
    unanswered: list[AdminRequest]
    failed_searches: list[AdminSearch]
    counts: AdminCounts


class AdminProfileDetail(BaseModel):
    """One profile as the operator moderates it. Named as the catalog names
    people, with nothing to reach them by: the console does not contact."""

    user_id: int
    name: str
    status: PublishStatus
    headline: str | None
    about: str | None
    services: list[str]
    institution: str | None
    published_at: datetime | None
    reviewed_at: datetime | None
    # What the operator read, for `AdminDecision.seen`.
    updated_at: datetime
    hidden_reason: HideReason | None
    hidden_note: str | None


class AdminPlacement(BaseModel):
    placement_id: int
    partner: str
    title: str
    slot: str
    is_active: bool
    impressions: int
    clicks: int


def _https_link(value: str) -> str:
    """A card's link leaves the app for the partner's site; only https does."""
    from urllib.parse import urlsplit

    link = value.strip()
    parts = urlsplit(link)
    if parts.scheme != "https" or not parts.netloc or any(c.isspace() for c in link):
        raise ValueError("The link must start with https://")
    return link


Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class AdminPlacementIn(BaseModel):
    """A new partner card on the Life screen. See docs/architecture.md."""

    partner: Annotated[Line, StringConstraints(max_length=200)]
    url: Annotated[str, StringConstraints(max_length=1024)]
    title: Annotated[Line, StringConstraints(max_length=200)]
    subtitle: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=240)
    ] = None
    price_text: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=64)
    ] = None
    context_note: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=600)
    ] = None
    logo_text: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=4)
    ] = None

    @field_validator("url")
    @classmethod
    def _url_is_https(cls, value: str) -> str:
        return _https_link(value)


class AdminDecision(BaseModel):
    """Keeping or restoring approves the profile as the operator read it. With
    `seen`, its `updated_at` then, an owner's save in between is a 409 rather
    than an edit approved unread."""

    seen: datetime | None = None


class AdminHide(BaseModel):
    """Why, from the list, or in words for «Другое» and only for it: the owner
    is shown the reason, and a note beside a listed reason would be shown to
    nobody."""

    reason: HideReason
    note: Annotated[str | None, StringConstraints(strip_whitespace=True)] = None

    @model_validator(mode="after")
    def _note_for_other_only(self) -> "AdminHide":
        self.note = self.note or None
        if self.reason is HideReason.OTHER:
            if self.note is None:
                raise ValueError("say why in a note")
            if len(self.note) > HIDE_NOTE_MAX:
                raise ValueError(f"at most {HIDE_NOTE_MAX} characters")
        elif self.note is not None:
            raise ValueError("a note goes only with «other»")
        return self


class AdminPlacementSwitch(BaseModel):
    is_active: bool
