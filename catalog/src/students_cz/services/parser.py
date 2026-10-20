"""Free text in, structured query out.

This is the piece that lets the interface have one input field instead of a
tree of categories. "нужен человек помочь с матаном на ČVUT, экзамен 14 февраля"
has to become a subject, an institution, a kind of help and a date.

Deliberately rule-based for now. The rules are cheap, they run in milliseconds,
they never invent a subject that does not exist, and every failure is visible in
`search_queries`. A model can replace `parse()` later without anything upstream
changing — the seam is the `ParsedQuery` it returns, not how it got there.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.db.models import Subject
from students_cz.db.models.enums import NodeKind
from students_cz.services.lookup import (
    VECTOR_FLOOR,
    VECTOR_LEAD,
    Match,
    find_by_meaning,
    find_institutions,
    find_subjects,
    normalise,
    transliterate,
)

_NON_WORD = re.compile(r"[^a-z0-9\u0400-\u04ff]+")


def tokenise(value: str) -> str:
    """Reduce text to " token token " with single spaces."""
    return f" {_NON_WORD.sub(' ', normalise(value)).strip()} "


def is_whole_word(haystack: str, needle: str) -> bool:
    """Does `needle` appear in `haystack` as a word of its own?

    For keywords that are words rather than stems. "визу" is the accusative of
    "виза" and also the first four letters of "визуализация", and
    `starts_a_word` deliberately lets a match run into the middle of a word —
    which read "визуализация данных" as a residence-permit question.
    """
    return tokenise(needle) in haystack


def starts_a_word(haystack: str, needle: str) -> bool:
    """Does `needle` begin at a word boundary in `haystack`?

    The keywords are stems, not words — "нострифик" has to reach
    "нострификация", "написа" has to reach "написать". So the match may run
    into the middle of a word, but it may not *start* there: otherwise "osp"
    fires on "gospodarka" and every short keyword becomes a trap.
    """
    return tokenise(needle).rstrip() in haystack


class Word(str):
    """A keyword that has to match a whole word rather than a stem.

    Every other entry below may run into the middle of a word, which is what
    lets "нострифик" reach "нострификации". For a short ordinary word that is a
    trap: "визу" is the accusative of "виза" and the first four letters of
    "визуализация". Written here rather than in a parallel set of strings, so
    adding a form cannot quietly make it a stem again.
    """

    __slots__ = ()


# Keywords that name a kind of help, across the four interface languages plus
# the transliterations students actually type. These are matching rules, not
# display text, so they live in code rather than in the translation catalogue.
SERVICE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "exam_live_help": (
        "на экзамене",
        "u zkousky",
        "во время экзамена",
        "в день экзамена",
        "подстрахов",
        "помощь на экза",
        "na zkousce",
        "behem zkousky",
        "during the exam",
        "на іспиті",
        "під час іспиту",
        "spisyvan",
        "списыв",
    ),
    "exam_prep": (
        "к экзамену",
        "подготовиться к экза",
        "сдать экзамен",
        "зачет",
        "zapocet",
        "na zkousku",
        "priprava na zkousku",
        "exam prep",
        "до іспиту",
        "перескладання",
        "пересдач",
        "opravny termin",
    ),
    "entrance_prep": (
        "вступительн",
        "поступлен",
        "prijimack",
        "přijímačk",
        "prijimaci",
        "entrance",
        "вступн",
        # The Ukrainian spelling, which used to reach `entrance_prep` only
        # because it was a synonym of one subject on this shelf.
        "приймач",
        "tsp",
        "osp",
        "nastupni",
    ),
    # Above the study kinds, unlike the rest of the non-study block below.
    # "присяжный перевод диплома" was answered as thesis writing on the strength
    # of the word "диплом", and "перевод аттестата" as nostrification, and the
    # only thing that fixes those is order.
    "translation": (
        # Stems for the noun in each language, because a multi-word keyword
        # tolerates inflection only on its last word — so "присяжного перевода
        # диплома", the commonest way to ask, reached none of the phrases that
        # used to be listed here and fell through to thesis writing on "диплом".
        # No subject in the catalog is named after translation, in any language,
        # so the stems cost nothing a phrase would have saved.
        "перевод",
        "переклад",
        "preklad",
        # The English four are what make this block reach past documents:
        # "translation studies tutor" reads as a document translation. Taken
        # deliberately — a foreign student in Czechia asking about "translation"
        # wants a stamped paper far more often than a seminar on translation
        # theory, and that field is not in the catalog at all.
        Word("translation"),
        Word("translations"),
        "translate",
        "translating",
    ),
    "nostrification": (
        "нострифик",
        "nostrifik",
        # The English spells it with a c — "nostrification" — so the stem above
        # misses it entirely, and the word that names this kind of help in
        # English reached nothing at all.
        "nostrific",
        "аттестат",
        "признание диплома",
        "uznani",
        "нострифік",
        "атестат",
    ),
    "writing": (
        "написать",
        "написа",
        "курсов",
        "семестров",
        "диплом",
        "бакалавр",
        "реферат",
        "эссе",
        "seminarn",
        "bakalars",
        "diplomov",
        "napsat",
        "write",
        "essay",
        "thesis",
        "написати",
        "курсову",
    ),
    "tutoring": (
        "репетитор",
        "объяснить",
        "разобрать",
        "подтянуть",
        "позанимат",
        "doucovani",
        "doucit",
        "vysvetlit",
        "tutor",
        "explain",
        "репетитора",
        "пояснити",
        "підтягнути",
        *(),  # weak verbs follow, see WEAK_HELP
    ),
    # Help that is not about studying. Last, and after tutoring: an incidental
    # mention of where somebody lives must not outrank an explicit study word,
    # and "нужен репетитор, живу в общежитии" did become housing when these sat
    # first. They still come before the weak verbs below, which is what makes
    # "помочь снять квартиру" housing rather than tutoring.
    "insurance": (
        "страховк",
        # Words, not stems: the genitive "страхования" belongs to a subject —
        # "экономика страхования" — and "pojistna matematika" is actuarial
        # mathematics, which the stem "pojist" read as somebody wanting a policy.
        Word("страхование"),
        Word("страхування"),
        "pojisten",
        "pojistk",
        "insurance",
        # The names people actually say. Words and not stems, for the reason
        # above and one more: "vzp" begins "vzpomínky", "vzpoura" and "vzpírání".
        # Only the health insurers a student meets, and only the names that are
        # nothing else in the catalog — "maxima" is a maths word, so it is not
        # here.
        Word("vzp"),
        Word("pvzp"),
        Word("slavia"),
        Word("uniqa"),
    ),
    "bank_letter": (
        "справка из банк",
        "справку из банк",
        "выписка со счет",
        "выписку со счет",
        "из банка",
        "довідка з банк",
        "довідку з банк",
        "з банку",
        "vypis z ban",
        "vypis z uct",
        "zustatek",
        "potvrzeni z ban",
        "potvrzeni o vedeni",
        "zustatku",
        "bank statement",
        "bank letter",
        "proof of funds",
    ),
    "residence": (
        "внж",
        # A stem, so the genitive "вида на жительство" is reached too.
        "жительств",
        # Words for the visa, and a stem for the stay. A multi-word keyword
        # tolerates inflection only on its last word, so the three phrases that
        # used to be here reached none of "prodlouzeni dlouhodobeho pobytu" —
        # the standard Czech phrasing — which "pobyt" does.
        Word("виза"),
        Word("визы"),
        Word("визу"),
        Word("визой"),
        Word("візу"),
        Word("візи"),
        Word("віза"),
        "посвідк",
        Word("vizum"),
        Word("viza"),
        "pobyt",
        "residence permit",
        Word("visa"),
        Word("visas"),
    ),
    "housing": (
        "жиль",
        "квартир",
        "общежит",
        "переезд",
        "житло",
        "гуртожит",
        "bydlen",
        "ubytovan",
        "na koleji",
        "housing",
        "dormitory",
    ),
}

# The kinds of help in the `life` group — the ones that are not about studying
# and carry no subject at all. Not "requires_subject is false", which is also
# true of exam help and nostrification and would be the wrong set: it is the
# group. Written out because the parser reads no tables, and pinned to the seed
# by test_subjectless_is_exactly_the_life_group so a sixth one cannot be added
# without this list noticing.
SUBJECTLESS = frozenset(
    {"insurance", "bank_letter", "translation", "residence", "housing"}
)

# The four of those whose keywords are ordinary words that turn up as asides —
# where somebody lives, what they are insured for. A subject named beside one of
# these is the question, and the aside is not. `translation` is deliberately not
# here: "присяжный перевод диплома" is not something anybody writes in passing,
# so when it appears the document is the request and a subject beside it is not
# one this kind of help can be filtered by.
ASIDES = SUBJECTLESS - {"translation"}

# "помочь с X" is the commonest phrasing there is, but on its own it says
# nothing about *which* kind of help. It counts as tutoring only when the text
# gives no other clue — see _match_service.
WEAK_HELP: tuple[str, ...] = ("помо", "pomo", "help", "допомо", "нужен", "потрібн")

# The languages people learn, for the one case the subject cannot settle: a
# query that says which language but not which level — "репетитор по чешскому" —
# resolves no subject at all, because a bare «чешский» names five of them and
# belongs to none.
#
# Used only there. High in the keyword table these words took «нужна чешская
# виза» and «zdravotní pojištění pro cizince» with them, because a language also
# says whose bank and whose visa.
LANGUAGE_WORDS: tuple[str, ...] = (
    "чешск",
    "чеськ",
    "cestin",
    # The adjective as well as the noun: "doucovani ceskeho jazyka" is how it is
    # said in Czech, and the Russian and Ukrainian entries already carry both
    # forms because their adjective is the stem.
    "cesk",
    "anglick",
    "nemeck",
    "английск",
    "англійськ",
    "anglict",
    "немецк",
    "німецьк",
    "nemcin",
    Word("czech"),
    Word("english"),
    Word("german"),
)

# A course, in any of the forms these decline into: both halves are matched
# independently, so "курсы чешского", "kurzu cestiny" and "czech language
# course" all reach the same place, which a multi-word keyword cannot do —
# it tolerates inflection only on its last word.
COURSE_WORDS: tuple[str, ...] = ("курс", "курси", "kurz", "course", "kurs")

# Words that put an exam in the picture without saying whether the help is
# wanted before it or during it. When one of these appears next to nothing but
# a weak verb, the honest move is to ask rather than to pick.
EXAM_MENTION: tuple[str, ...] = (
    "экзамен",
    "экза",
    "zkous",
    "іспит",
    "exam",
    "termin",
)

# Words that only restate a kind of help once its keyword has named it: the
# exam in «вступительные экзамены», the preparing in «подготовка к ...». A
# query made of a keyword and these names no subject, and the scorer guessing
# one answered the catalog's own name for entrance exams with «Чешский язык
# B1», because a synonym of that course mentions an exam.
RESTATING: tuple[str, ...] = (
    "экзамен",
    "екзамен",
    "испытани",
    "іспит",
    "zkous",
    "exam",
    "подготов",
    "підготов",
    "priprav",
    # Words, not stems: "prep" begins "přepis" and "přeprava" once unaccented.
    Word("prep"),
    Word("preparation"),
)

# Month names, unaccented and lowercased, in the order the client will have
# typed them. Czech has both nominative and genitive forms in circulation.
MONTHS: dict[str, int] = {}
for _idx, _names in enumerate(
    (
        ("янв", "leden", "ledna", "jan", "січ"),
        ("фев", "unor", "unora", "feb", "лют"),
        ("мар", "brezen", "brezna", "mar", "берез"),
        ("апр", "duben", "dubna", "apr", "квіт"),
        ("мая", "мае", "май", "kveten", "kvetna", "may", "трав"),
        ("июн", "cerven", "cervna", "jun", "черв"),
        ("июл", "cervenec", "cervence", "jul", "лип"),
        ("авг", "srpen", "srpna", "aug", "серп"),
        ("сен", "zari", "sep", "верес"),
        ("окт", "rijen", "rijna", "oct", "жовт"),
        ("ноя", "listopad", "listopadu", "nov", "листоп"),
        ("дек", "prosinec", "prosince", "dec", "груд"),
    ),
    start=1,
):
    for _name in _names:
        MONTHS[_name] = _idx

# Czech writes an ordinal day with a full stop: "3. brezna".
_DAY_MONTH_WORD = re.compile(r"\b(\d{1,2})[\s.]*([a-zа-яіїєґ]{3,10})")
_DAY_MONTH_NUM = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b")
_BUDGET = re.compile(
    r"(?:до|max|maximalne|not more than|не более|не більше)?\s*"
    r"(\d{2,5})\s*(?:kc|kč|czk|крон|korun)?\b"
)


@dataclass
class ParsedQuery:
    raw: str
    subject: Match | None = None
    institution: Match | None = None
    service_type: str | None = None
    deadline: date | None = None
    budget_max: float | None = None
    unmatched: bool = False
    alternatives: dict[str, list[Match]] = field(default_factory=dict)
    # What the embedder proposed and by how much it led the next subject —
    # recorded whether or not it was believed, so the two thresholds it is
    # judged by can be set from data instead of by eye. Logged into
    # `search_queries.parsed`; see `api/v1/search`.
    vector: tuple[Match, float] | None = None
    # Set when the proposal cannot go with the kind of help at all — one that
    # carries no subject — whether it was believed and then removed or never
    # reached the bar. Anything downstream that would show the guess has to know
    # the difference: "we were not sure" is worth showing, "this cannot go with
    # what you asked for" is not, because the list behind it is empty by
    # construction.
    vector_conflicted: bool = False


async def parse(
    session: AsyncSession, text: str, lang: str, *, today: date | None = None
) -> ParsedQuery:
    norm = normalise(text)
    result = ParsedQuery(raw=text)

    result.service_type, keyword = _match_service(norm)

    institutions = await find_institutions(session, text, lang, limit=3)
    if institutions:
        result.institution = institutions[0]
        result.alternatives["institution"] = institutions[1:]

    result.deadline = _match_deadline(norm, today or date.today())
    result.budget_max = _match_budget(norm)

    subjects = await find_subjects(session, text, lang, limit=4)
    # A word for a whole shelf — «математика», "maths" — names the shelf, and the
    # search reads a shelf as what it holds (`lookup.held_by`). Answered with the
    # leaf the scorer liked best it narrowed the search to «Математика для
    # экономистов».
    #
    # Only when the maths word is all the query says about a subject, and only
    # through a shelf's synonyms, which are written down for exactly this. Never
    # over a leaf the query named — «матан» is more than maths — nor beside
    # anything else that could say which corner: «matematiky pro ekonomy» is
    # the economists' leaf, inflected. And not with a kind of help whose offers
    # sit on another shelf: entrance exams and nostrification beside the maths
    # shelf would match nobody, where the leaf «Přijímací zkouška z matematiky»
    # matches them.
    if not (subjects and _is_named(subjects[0])) and result.service_type in SHELF_KINDS:
        shelves = await find_subjects(session, text, lang, limit=1, kind=NodeKind.GROUP)
        # The synonyms themselves, not the match's kind: the query has to hold a
        # word starting with one of them, which a hit on the name alone cannot
        # give — that is what keeps a group's name from making it the answer.
        stems = (
            await session.scalar(
                select(Subject.synonyms).where(Subject.id == shelves[0].id)
            )
            if shelves
            else None
        )
        if stems and _only_names_shelf(result, norm, keyword, stems):
            subjects = [shelves[0], *subjects[:3]]
    # When the words naming the kind of help were the whole query, there is no
    # subject in it to find, and a trigram guess is the scorer answering a
    # question nobody asked: "bank statement" came back as Probability and
    # Statistics at 0.61. A synonym hit survives, because that is not a guess —
    # "курсовая" and "нострификация" are curated names for real subjects, and
    # dropping them would lose a certainty to protect against a maybe.
    #
    # "The whole query" counts the words that only restate the kind of help
    # (RESTATING) and prepositions: «вступительные экзамены» and «příprava na
    # přijímací zkoušky» are that kind of help named in full.
    #
    # A subject whose own name is nothing but those words survives too: it is
    # the kind of help by the same name, not a guess at something unsaid —
    # «нострификационный экзамен» is «Нострификационные экзамены» inflected.
    bare = keyword is not None and _only_restates(norm, keyword)
    if bare:
        subjects = [
            match
            for match in subjects
            if _is_named(match) or _only_restates(normalise(match.label), keyword)
        ]

    # The third mechanism, and the last asked. Only where the first two found
    # nothing: a synonym or an exact name is curated and scores 1.00, and the
    # embedder loses to both on slang — it answers «Математика для экономистов»
    # to «матан». What it proposes is logged either way, because the two numbers
    # it is judged by were set by eye and `search_queries` is where the ones to
    # replace them will come from.
    #
    # Before the reconciliation below and not after, so its answer is subject to
    # the same rules: it is a guess by construction, and «нужна чешская виза»
    # proposed «Чешский язык B2» at 0.50 — a subject beside a kind of help that
    # has none, which the rule below is exactly for.
    #
    # And only when the query says something nothing else has accounted for.
    # Silence has two meanings: "the rules could not read this" and "there is
    # nothing here to read". A bare «přijímačky» is the second — the word is the
    # whole query and it names a kind of help — and asking anyway answered
    # «Поступление в экономические вузы» at 0.53, the very mistake the synonym
    # was taken off that subject to stop. So is «репетитор ČVUT», where the
    # school is already a field and what is left is a word for teaching: the
    # embedder answered «Поступление в технические вузы» at 0.45 and narrowed a
    # list of tutors to the people who prepare for entrance exams.
    if not subjects and not bare and not _accounted_for(result, norm, keyword):
        proposed, runner_up = await find_by_meaning(session, text, lang)
        if proposed:
            lead = proposed.score - (runner_up.score if runner_up else 0.0)
            result.vector = (proposed, lead)
            if proposed.score >= VECTOR_FLOOR and lead >= VECTOR_LEAD:
                subjects = [proposed]

    # A kind of help that never carries a subject cannot be the answer to a
    # query that *names* one. `catalog.search` ANDs the two, and no offer in the
    # non-study group has a subject, so the pair matches nobody: "нужен матан,
    # живу в общежитии" is a question about calculus with an aside in it, and
    # reading it as housing turned a list of tutors into an empty screen. Read
    # again as if those kinds did not exist.
    #
    # Which of the two gives way depends on whether the subject was named, and on
    # whether the kind of help could have been an aside. A named subject beside
    # an aside wins: read the kind of help again as if the
    # non-study ones did not exist. A trigram score is a guess, and a guess
    # cannot narrow a kind of help that has no subjects to narrow by — so the
    # guess goes instead. Keeping both was a guaranteed empty screen, and
    # keeping the subject over the service undid the reason translation sits
    # above the study kinds: "присяжный перевод диплома" scores «Академическое
    # письмо» at 0.55.
    if subjects and result.service_type in SUBJECTLESS:
        if _is_named(subjects[0]) and result.service_type in ASIDES:
            result.service_type, _ = _match_service(norm, ignore=SUBJECTLESS)
        else:
            subjects = []

    # A kind of help that carries no subject cannot be shown beside one either.
    # Whether the proposal was believed and then dropped above, or never reached
    # the bar at all, a second list filtered by it is guaranteed to be empty —
    # the search ANDs the two and no offer in that group has a subject.
    if result.vector and result.service_type in SUBJECTLESS:
        result.vector_conflicted = True

    if subjects:
        result.subject = subjects[0]
        # Keep the runners-up so the chip can offer "did you mean" instead of
        # silently committing to a 0.52-confidence guess.
        result.alternatives["subject"] = subjects[1:]

    # A language lesson is a lesson whose request is the language, and nothing
    # else. "репетитор по химии на чешском" names the medium of instruction,
    # "репетитор по чешской литературе" a nationality, and "репетитор по матану
    # на чешском" both — each leaves a subject named once the asking and the
    # language are taken out, which is the same test the subject filter above
    # makes of a keyword that was the whole query. Read as language lessons they
    # would carry a subject no language offer has, and `catalog.search` ANDs the
    # two: an empty screen for a query that worked.
    #
    # Last, because "what is left" has to mean *left over from everything the
    # query said*: a budget, a date and a school are all already fields by now,
    # and counting their words would have made "doucovani cestiny na ČVUT" plain
    # tutoring.
    #
    # Lexical, and not a question about the resolved subject, for two reasons.
    # The commonest phrasing resolves none — "репетитор по чешскому" says which
    # language and not which level, and a bare «чешский» names five subjects and
    # belongs to none of them. And where one does resolve it is as often the
    # wrong one: "chemistry tutor in czech" scores Czech C1 at 0.69 against
    # chemistry at 0.55, by name in both cases, so neither the score nor how it
    # matched separates the two.
    if result.service_type == "tutoring" or (
        result.service_type is None and _mentions(norm, COURSE_WORDS)
    ):
        language = _first(norm, LANGUAGE_WORDS)
        if language and _accounted_for(result, norm, keyword, language):
            result.service_type = "language_tutoring"

    result.unmatched = not any((result.subject, result.institution, result.service_type))
    return result


# The words that ask rather than name: verbs of searching, prepositions,
# articles, the word "language" itself and the word "course". What is left after
# these and after the words a rule already accounted for is the part of the
# query that names something else — see the language refinement in `parse`.
FILLER: tuple[str, ...] = (
    *WEAK_HELP,
    # WEAK_HELP carries "нужен" and "потрібн", which between them miss "нужна",
    # "нужно" and "потрібен" — forms that matter here, where what is left over
    # is the whole question.
    "нужн",
    "потріб",
    "ищу",
    "найти",
    "хочу",
    "подскаж",
    "посовет",
    "шукаю",
    "знайти",
    "hledam",
    "potrebuj",
    "looking",
    "need",
    "want",
    "язык",
    "мова",
    "мови",
    "мову",
    "jazyk",
    "language",
    *COURSE_WORDS,
    # A shade of the language rather than another subject.
    "разговорн",
    "розмовн",
    "konverzac",
    "conversational",
    # And any *other* language: "репетитор по чешскому и английскому" asks for
    # two of these and for nothing else.
    *LANGUAGE_WORDS,
)

# Single letters and prepositions, which a stem list cannot hold: "по" would
# match "поступление" and "s" would match every Czech word beginning with it.
FILLER_WORDS: frozenset[str] = frozenset(
    (
        # ru
        "по",
        "на",
        "с",
        "у",
        "для",
        "в",
        "о",
        "от",
        "из",
        "и",
        "к",
        "мне",
        # uk
        "і",
        "з",
        "до",
        "та",
        "мені",
        # cs
        "z",
        "s",
        "v",
        "k",
        "na",
        "pro",
        "si",
        # "do 600 korun" — the Czech limit word, which `_BUDGET` does not
        # consume the way it consumes the Russian "до".
        "do",
        # The level, which says which row of the same language and never
        # another subject.
        "a1",
        "a2",
        "b1",
        "b2",
        "c1",
        "c2",
        # How something is done rather than what it is about. The catalog
        # stores this per offer and the query has nowhere to put it, so a word
        # nobody reads is not a subject nobody named: "doucovani online"
        # answered «Компьютерные сети» at 0.46.
        "online",
        "онлайн",
        "оффлайн",
        "офлайн",
        "очно",
        "дистанционно",
        "osobne",
        "prezencne",
        "remote",
        "offline",
        # en
        "for",
        "at",
        "on",
        "by",
        "from",
        "about",
        "please",
        "a",
        "an",
        "the",
        "in",
        "with",
        "and",
        "i",
        "am",
        "is",
        "are",
        "to",
        "of",
        "my",
        "me",
    )
)


def _accounted_for(
    result: "ParsedQuery", norm: str, keyword: str | None, *also: str
) -> bool:
    """Has everything in the query already been read by something else?

    The question both derived rules ask, and they have to ask it the same way:
    the kind of help's own words, the school, the date and the price are fields
    by now, and what is left over is the part nobody has explained.

    The date and the price come out by the spans that produced them and not by
    words that look like them — "мар" is March and the first three letters of
    "маркетингу".
    """
    accounted = [keyword or "", *also]
    if result.institution:
        accounted.append(result.institution.label)
    return not _left_over(_spoken(result, norm), *accounted)


def _spoken(result: "ParsedQuery", norm: str) -> str:
    """The query without the spans the date and the price were read from."""
    spoken = norm
    if result.deadline:
        spoken = _DAY_MONTH_WORD.sub(" ", _DAY_MONTH_NUM.sub(" ", spoken))
    if result.budget_max is not None:
        spoken = _BUDGET.sub(" ", spoken)
    return spoken


def _left_over(norm: str, *accounted: str) -> str:
    """What the query still names once these words and the filler are gone.

    An accounted word is removed as it stands and, failing that, by its
    transliteration: a school resolves through its code or through the
    transliterated query, so "на чвуте" carries none of the label's characters
    and would otherwise be left over as a word that names something.
    """
    text_left = norm
    for word in accounted:
        if word:
            text_left = _without(text_left, word)
    tokens = [
        token
        for token in tokenise(text_left).split()
        if not any(
            word and transliterate(token).startswith(transliterate(normalise(word)))
            for word in accounted
        )
    ]
    rest = [
        token
        for token in tokens
        # A bare number names nothing: whatever it was — a price, a page count,
        # a year — it is not a subject. What the date and the price matchers
        # consumed is already gone; see the caller.
        if not token.isdigit()
        and token not in FILLER_WORDS
        and not any(token.startswith(normalise(word)) for word in FILLER)
    ]
    return " ".join(rest)


def _first(norm: str, words: tuple[str, ...]) -> str | None:
    """The first of `words` the text contains, or None."""
    tokens = tokenise(norm)
    for word in words:
        match = is_whole_word if isinstance(word, Word) else starts_a_word
        if match(tokens, word):
            return word
    return None


def _mentions(norm: str, words: tuple[str, ...]) -> bool:
    return _first(norm, words) is not None


def _match_service(
    norm: str, *, ignore: frozenset[str] = frozenset()
) -> tuple[str | None, str | None]:
    """The kind of help, and the keyword that decided it.

    First keyword wins, and the dictionary is ordered by specificity. "помощь на
    экзамене" must not be read as plain exam preparation, so exam_live_help is
    checked before exam_prep and generic tutoring last. Weak verbs are
    considered only after every specific rule has passed.

    The keyword comes back so the caller can ask whether anything else was in the
    query at all. A weak verb yields none: "помоги" names no kind of help by
    itself, so there is nothing to say it took the whole sentence.

    `ignore` re-reads the same text as if some kinds did not exist — see
    SUBJECTLESS at the call site.
    """
    tokens = tokenise(norm)
    for code, keywords in SERVICE_KEYWORDS.items():
        if code in ignore:
            continue
        for keyword in keywords:
            match = is_whole_word if isinstance(keyword, Word) else starts_a_word
            if match(tokens, keyword):
                return code, keyword

    if any(starts_a_word(tokens, verb) for verb in WEAK_HELP):
        if any(starts_a_word(tokens, word) for word in EXAM_MENTION):
            return None, None  # an exam is mentioned but not placed in time
        return "tutoring", None
    return None, None


def _is_named(match: Match) -> bool:
    """Did the query name this subject, rather than score against it?

    A 1.0 is either a curated synonym or a name the query reproduced exactly.
    Everything below it is the trigram scorer's opinion — the external-code
    branch stops at 0.95 and the synonym-similarity branch at 0.92, so the line
    is exactly where certainty is.

    `matched_on == "synonym"` was the first spelling of this and it was too
    narrow: "Чешский язык B1, нужна виза" names the subject in full, scores 1.0,
    and reports `name` — so the subject the person typed out was thrown away as
    a guess.

    A vector match is never named, whatever it scores: its number is a cosine
    and not a claim that the query said the words. The two happen to share a
    scale and mean nothing alike.
    """
    return match.matched_on != "vector" and match.score >= 1.0


# The kinds of help a shelf can go with: their offers sit on the shelf's own
# leaves. None is the commonest — a bare «математика».
SHELF_KINDS: frozenset[str | None] = frozenset(
    {None, "tutoring", "exam_prep", "exam_live_help"}
)


# Which school's maths, not which maths: «высшая математика» is the whole shelf
# taught at a university, and the leaf the scorer liked found nobody.
LEVEL_OF_SCHOOL: tuple[str, ...] = ("высш", "вищ", "vyss", "higher")


def _only_names_shelf(
    result: "ParsedQuery", norm: str, keyword: str | None, stems: list[str]
) -> bool:
    """Is a word for the shelf all the query says about a subject?

    Besides the keyword's own words and what is already a field — the school,
    the date, the price — what may remain is the shelf's word, the words of
    asking, the words that restate the kind of help, and prepositions; not a
    level, which says which language. «репетитор по математике на ČVUT» is the
    shelf; «репетитор по математике для экономистов» is not.
    """
    spoken = _spoken(result, norm)
    tokens = tokenise(_without(spoken, keyword) if keyword else spoken).split()
    school = (
        transliterate(normalise(result.institution.label)) if result.institution else None
    )
    named = [
        token
        for token in tokens
        if any(token.startswith(normalise(stem)) for stem in stems)
    ]
    return bool(named) and all(
        token in named
        or token.isdigit()
        or any(token.startswith(word) for word in LEVEL_OF_SCHOOL)
        or (school is not None and transliterate(token).startswith(school))
        or (token in FILLER_WORDS and not _LEVEL.fullmatch(token))
        or any(token.startswith(word) for word in ASKING)
        or any(
            token == word if isinstance(word, Word) else token.startswith(word)
            for word in RESTATING
        )
        for token in tokens
    )


def _only_restates(norm: str, keyword: str) -> bool:
    """Is the query its keyword and nothing that could name a subject?

    Besides the keyword's own words, only RESTATING words, words of asking and
    prepositions may remain. A language level may not, although FILLER_WORDS
    lists them: «B2» beside an exam is which Czech exam, and that is a subject.
    Nor may the rest of FILLER — the names of languages and the word "course" —
    since those are how people name subjects.
    """
    return all(
        (token in FILLER_WORDS and not _LEVEL.fullmatch(token))
        or any(token.startswith(word) for word in ASKING)
        or any(
            token == word if isinstance(word, Word) else token.startswith(word)
            for word in RESTATING
        )
        for token in tokenise(_without(norm, keyword)).split()
    )


# How people ask for a kind of help around its name: «нужна подготовка к
# вступительным», "help with entrance exams". The asking part of FILLER.
ASKING: tuple[str, ...] = (
    *WEAK_HELP,
    "нужн",
    "потріб",
    "ищу",
    "найти",
    "хочу",
    "шукаю",
    "знайти",
    "hledam",
    "potrebuj",
    "looking",
    "need",
    "want",
)


_LEVEL = re.compile(r"[abc][12]")


def _without(norm: str, keyword: str) -> str:
    """`norm` minus the words the keyword touched.

    Whole words, not the keyword's characters: the keywords are stems, so
    removing "нострифик" from "нострификация" would leave "ация", and the caller
    is asking whether anything is left — a fragment would answer yes.
    """
    tokens = tokenise(norm)
    needle = tokenise(keyword).rstrip()
    at = tokens.find(needle)
    if at < 0:
        return norm
    end = tokens.find(" ", at + len(needle))
    return (tokens[:at] + (tokens[end:] if end >= 0 else " ")).strip()


def _match_deadline(norm: str, today: date) -> date | None:
    match = _DAY_MONTH_WORD.search(norm)
    if match:
        day, word = int(match.group(1)), match.group(2)
        month = next((m for name, m in MONTHS.items() if word.startswith(name)), None)
        if month and 1 <= day <= 31:
            return _next_occurrence(day, month, today)

    match = _DAY_MONTH_NUM.search(norm)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        year = match.group(3)
        if 1 <= day <= 31 and 1 <= month <= 12:
            if year:
                y = int(year)
                return _safe_date(y + 2000 if y < 100 else y, month, day)
            return _next_occurrence(day, month, today)
    return None


def _next_occurrence(day: int, month: int, today: date) -> date | None:
    """Bare "14 February" means the next one, not one in the past.

    Exams cluster in January–February and May–June, so a date typed in
    December almost always means next year.
    """
    candidate = _safe_date(today.year, month, day)
    if candidate is None:
        return None
    if candidate < today:
        return _safe_date(today.year + 1, month, day)
    return candidate


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _match_budget(norm: str) -> float | None:
    """Only read a number as money when it is marked as money.

    Otherwise "14 февраля" becomes a budget of 14 crowns, and "физика 2"
    becomes a budget of 2.
    """
    for match in _BUDGET.finditer(norm):
        whole = match.group(0)
        has_currency = re.search(r"kc|kč|czk|крон|korun", whole)
        has_limit_word = re.match(
            r"\s*(до|max|maximalne|not more than|не более|не більше)", whole
        )
        if has_currency or has_limit_word:
            value = float(match.group(1))
            if 50 <= value <= 100_000:
                return value
    return None
