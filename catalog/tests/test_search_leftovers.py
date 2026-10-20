"""What #252 left open, each found on the deployed parser (#257).

Small things, each a query people type that came back as something else.
"""

from datetime import date

import pytest
from sqlalchemy import select

from students_cz.db.models import Subject
from students_cz.services.parser import parse

pytestmark = pytest.mark.asyncio

TODAY = date(2026, 1, 20)


async def _id(session, slug: str) -> int:
    subject_id = await session.scalar(select(Subject.id).where(Subject.slug == slug))
    assert subject_id is not None, f"seed missing subject {slug}"
    return subject_id


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        # "exam prep" was checked before "entrance", and took the query.
        ("entrance exam preparation", "en"),
        ("entrance exam prep", "en"),
        # «тесты» only restate the kind of help, like «экзамены».
        ("вступительные тесты", "ru"),
        ("přijímací testy", "cs"),
    ],
)
async def test_entrance_exams_named_in_other_words(session, text, lang) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.service_type == "entrance_prep"
    assert parsed.subject is None, parsed.subject


async def test_a_number_in_a_synonym_ends_there(session) -> None:
    """«физика 11 класс» matched the synonym «физика 1» by its first digit."""
    parsed = await parse(session, "физика 11 класс", "ru", today=TODAY)
    assert parsed.subject is not None
    assert parsed.subject.id != await _id(session, "fyzika-1"), parsed.subject


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("matematika na Univerzitě Karlově", "cs"),
        ("matematika na Masarykově univerzitě", "cs"),
    ],
)
async def test_a_czech_locative_school_is_the_school(session, text, lang) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.institution is not None, "no school"
    assert parsed.subject is not None
    assert parsed.subject.id == await _id(session, "math"), parsed.subject


@pytest.mark.parametrize(
    ("text", "lang", "shelf"),
    [
        # A person, a treatment and a classic are not the shelf.
        ("химиотерапия", "ru", "chemistry"),
        ("chemist", "en", "chemistry"),
        ("třídění matematika", "cs", "math"),
    ],
)
async def test_a_stem_stops_at_the_word_it_means(session, text, lang, shelf) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.subject is None or parsed.subject.id != await _id(session, shelf), (
        parsed.subject
    )


@pytest.mark.parametrize(
    ("text", "lang", "shelf"),
    [
        # The forms the narrower words must still reach.
        ("химия", "ru", "chemistry"),
        ("помощь по химии", "ru", "chemistry"),
        ("репетитор по химии", "ru", "chemistry"),
        ("хімія", "uk", "chemistry"),
        ("з хімії", "uk", "chemistry"),
        ("chemie", "cs", "chemistry"),
        ("doučování chemii", "cs", "chemistry"),
        ("chemistry", "en", "chemistry"),
        # The person, like «математик» for maths. Not "chemist", a pharmacy.
        ("репетитор химик", "ru", "chemistry"),
        ("нужен химик", "ru", "chemistry"),
        ("хімік", "uk", "chemistry"),
        ("chemik", "cs", "chemistry"),
        ("информатик", "ru", "it-programming"),
        ("інформатик", "uk", "it-programming"),
        ("informatik", "cs", "it-programming"),
        ("информатика", "ru", "it-programming"),
        ("по информатике", "ru", "it-programming"),
        ("физика 9 класс", "ru", "physics"),
        ("fyzika 9. třída", "cs", "physics"),
        ("učitel matematiky", "cs", "math"),
    ],
)
async def test_the_narrower_words_still_name_the_shelf(
    session, text, lang, shelf
) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.subject is not None, "no subject at all"
    assert parsed.subject.id == await _id(session, shelf), parsed.subject


async def test_rizeni_restates_only_entrance_exams(session) -> None:
    """«přijímací řízení» is the admission procedure; beside tutoring the word
    is control, so the query is not bare and the embedder may answer it."""
    from students_cz.db.embed import rebuild
    from students_cz.services import embedding

    from .test_embedding import PointedEmbedder

    query = "doučování řízení"
    pointed = PointedEmbedder({query: "Automatizace a teorie řízení"})
    await rebuild(session, embedder=pointed)
    embedding.set_embedder(pointed)
    try:
        parsed = await parse(session, query, "cs", today=TODAY)
    finally:
        embedding.set_embedder(None)

    assert parsed.service_type == "tutoring"
    assert parsed.vector is not None, "the embedder was not asked"


# Every form of the words said beside a shelf, each on its own: a form missing
# from the list sent «математика 5-6 классы» to a leaf that matched nobody.
ASIDE_FORMS = [
    (
        "математика 9 {}",
        "ru",
        "класс класса классу классом классе классы классов классам классами классах",
    ),
    (
        "математика 9 {}",
        "uk",
        "клас класу класом класі класи класів класам класами класах",
    ),
    ("matematika {}", "cs", "třída třídy třídě třídu třídou tříd třídám třídách třídami"),
    (
        "{} matematiky",
        "cs",
        "učitel učitele učiteli učitelem učitelů učitelům učitelích"
        " učitelka učitelky učitelce učitelku učitelkou učitelkám učitelkách učitelkami",
    ),
]


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        (template.format(form), lang)
        for template, lang, forms in ASIDE_FORMS
        for form in forms.split()
    ],
)
async def test_every_form_of_an_aside_is_aside(session, text, lang) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.subject is not None, "no subject at all"
    assert parsed.subject.id == await _id(session, "math"), parsed.subject


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        (f"вступительные {form}", "ru")
        for form in [
            "тест",
            "теста",
            "тесту",
            "тестом",
            "тесте",
            "тесты",
            "тестов",
            "тестам",
            "тестами",
            "тестах",
        ]
    ]
    + [
        (f"вступні {form}", "uk")
        for form in ["тест", "тесту", "тести", "тестів", "тестами"]
    ]
    + [(f"entrance {form}", "en") for form in ["test", "tests"]]
    + [
        (f"přijímací {form}", "cs")
        for form in ["test", "testy", "testu", "testů", "testem", "testech"]
    ],
)
async def test_every_form_of_a_test_restates_entrance_exams(session, text, lang) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.service_type == "entrance_prep"
    assert parsed.subject is None, parsed.subject


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("зачет по OSPF", "ru"),
        ("exam prep OSPF", "en"),
        ("příprava na zkoušku z OSPF", "cs"),
    ],
)
async def test_osp_is_a_word_not_the_start_of_ospf(session, text, lang) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.service_type == "exam_prep"


def _shelf_words(slug: str) -> list[str]:
    import json
    from pathlib import Path

    data = json.loads(
        (Path(__file__).resolve().parents[1] / "seeds/subjects.json").read_text()
    )
    [group] = [group for group in data["groups"] if group["slug"] == slug]
    return group["synonyms"]


@pytest.mark.parametrize(
    ("word", "shelf"),
    [(word, "chemistry") for word in _shelf_words("chemistry")]
    + [(word, "it-programming") for word in _shelf_words("it-programming")],
)
async def test_every_listed_form_names_its_shelf(session, word, shelf) -> None:
    """A form that does not reach the shelf is a form nobody will notice is gone."""
    parsed = await parse(session, word, "ru", today=TODAY)
    assert parsed.subject is not None, "no subject at all"
    assert parsed.subject.id == await _id(session, shelf), parsed.subject


@pytest.mark.parametrize(
    ("token", "names", "school"),
    [
        ("univerzite", {"univerzita"}, True),
        ("karlove", {"karlova"}, True),
        ("karlovom", {"karlov"}, True),
        # Short words only whole: «brna» is not «brno», «uka» not «uk».
        ("brna", {"brno"}, False),
        ("uka", {"uk"}, False),
        ("uk", {"uk"}, True),
        # One letter, not two: «univerzum» is not «univerzita».
        ("univerzum", {"univerzita"}, False),
    ],
)
async def test_a_school_word_may_change_its_last_letter_and_no_more(
    token, names, school
) -> None:
    from students_cz.services.parser import _is_school_word

    assert _is_school_word(token, names) is school


@pytest.mark.parametrize(
    ("text", "lang", "shelf"),
    [
        # Which kind of maths, like «высшая», not which corner.
        ("učitelství matematiky", "cs", "math"),
        ("učitelství fyziky", "cs", "physics"),
        ("классическая математика", "ru", "math"),
        ("классическая физика", "ru", "physics"),
        # A school's name that shares a shelf's word only by its stem still
        # counts as the school: «chemicko-technologická» is not «chemie».
        ("chemie Vysoká škola chemicko-technologická", "cs", "chemistry"),
        # Adjectives the shelves are named by.
        ("doučování informatický", "cs", "it-programming"),
        ("chemical", "en", "chemistry"),
    ],
)
async def test_more_that_names_a_shelf(session, text, lang, shelf) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.subject is not None, "no subject at all"
    assert parsed.subject.id == await _id(session, shelf), parsed.subject


async def test_a_school_word_is_not_a_subject(session) -> None:
    """ "Faculty of Physical Education" is a school; "physical" in it is not
    physics, so the query names no physics course."""
    parsed = await parse(session, "Faculty of Physical Education", "en", today=TODAY)
    assert parsed.subject is None or parsed.subject.id != await _id(
        session, "fyzika-1"
    ), parsed.subject


@pytest.mark.parametrize("text", ["přijímací testy", "přijímací testech"])
async def test_czech_tests_ask_no_embedder(session, text) -> None:
    """Bare, so nothing is left for the embedder to explain."""
    from students_cz.db.embed import rebuild
    from students_cz.services import embedding

    from .test_embedding import PointedEmbedder

    pointed = PointedEmbedder({text: "OSP — тест Scio (общие способности)"})
    await rebuild(session, embedder=pointed)
    embedding.set_embedder(pointed)
    try:
        parsed = await parse(session, text, "cs", today=TODAY)
    finally:
        embedding.set_embedder(None)
    assert parsed.service_type == "entrance_prep"
    assert parsed.vector is None, "the embedder was asked"


@pytest.mark.parametrize("text", ["Právnická fakulta", "Filozofická fakulta"])
async def test_a_school_alone_names_no_subject(session, text) -> None:
    """Nothing is left once the school's words go, so nothing is guessed — and
    the embedder is not asked either: it answered «Přijímačky na medicínu»."""
    from students_cz.db.embed import rebuild
    from students_cz.services import embedding

    from .test_embedding import PointedEmbedder

    pointed = PointedEmbedder({text: "Přijímačky na medicínu (biologie + chemie)"})
    await rebuild(session, embedder=pointed)
    embedding.set_embedder(pointed)
    try:
        parsed = await parse(session, text, "cs", today=TODAY)
    finally:
        embedding.set_embedder(None)
    assert parsed.institution is not None
    assert parsed.subject is None, parsed.subject
    assert parsed.vector is None, "the embedder was asked"


async def test_for_entrance_exams_the_school_is_the_subject(session) -> None:
    """«přijímačky na VŠE» names the economics admissions by the school; without
    the school's words the guess went to the technical admissions."""
    parsed = await parse(session, "přijímačky na VŠE", "cs", today=TODAY)
    assert parsed.service_type == "entrance_prep"
    assert parsed.subject is not None
    assert parsed.subject.id == await _id(session, "prijimacky-ekonomicke-vs"), (
        parsed.subject
    )


@pytest.mark.parametrize(
    ("word", "stem", "shares"),
    [
        ("chemii", "chemie", True),
        ("chemie", "chemie", True),
        ("matematiky", "matematik", True),
        ("chemicko", "chemie", False),
        ("physical", "physics", False),
        # Too short for the last-letter rule.
        ("chem", "chemi", False),
    ],
)
async def test_a_shelf_word_differs_from_its_forms_in_the_last_letter_only(
    word, stem, shares
) -> None:
    from students_cz.services.parser import _shares_a_stem

    assert _shares_a_stem(word, stem) is shares


async def test_ukrainian_classical_is_the_kind(session) -> None:
    parsed = await parse(session, "класична фізика", "uk", today=TODAY)
    assert parsed.subject is not None
    assert parsed.subject.id == await _id(session, "physics"), parsed.subject


@pytest.mark.parametrize(
    ("text", "lang", "slug"),
    [
        # A school and a subject beside entrance exams (#259): the answer is on
        # the admissions shelf, where every entrance offer sits.
        ("поступление на ЧВУТ физика", "ru", "prijimacky-fyzika"),
        ("přijímačky na VŠE z matematiky", "cs", "prijimacky-matematika"),
        ("поступление в ВШЭ математика", "ru", "prijimacky-matematika"),
        # What already landed there stays.
        ("přijímačky na ČVUT", "cs", "prijimacky-technicke-vs"),
        ("přijímačky na VŠE", "cs", "prijimacky-ekonomicke-vs"),
        ("вступительные по физике", "ru", "prijimacky-fyzika"),
        # A shelf named beside them: the admissions leaf has to say its word.
        ("přijímací zkoušky z chemie", "cs", "prijimacky-medicina"),
    ],
)
async def test_entrance_exams_answer_from_the_admissions_shelf(
    session, text, lang, slug
) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.service_type == "entrance_prep"
    assert parsed.subject is not None
    assert parsed.subject.id == await _id(session, slug), parsed.subject
