from datetime import date

import pytest

from students_cz.services.lookup import normalise
from students_cz.services.parser import (
    SUBJECTLESS,
    _match_budget,
    _match_deadline,
    _match_service,
    _without,
    parse,
)

TODAY = date(2026, 1, 20)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("нужна нострификация аттестата", "nostrification"),
        ("надо написать курсовую до марта", "writing"),
        ("prijimacky na cvut", "entrance_prep"),
        ("помощь на экзамене 14 февраля", "exam_live_help"),
        ("ищу репетитора по матану", "tutoring"),
        ("треба підтягнути фізику", "tutoring"),
        ("pomoc u zkousky", "exam_live_help"),
        ("матан", None),
        # A weak verb alone means tutoring...
        ("помоги с матаном", "tutoring"),
        # ...but not when an exam is in the picture and its timing is not.
        ("нужна помощь, экзамен 14 февраля", None),
    ],
)
def test_service_keywords(text, expected):
    assert _match_service(normalise(text))[0] == expected


def test_keyword_must_start_a_word():
    """ "osp" is a Scio test; it is also inside "gospodarka"."""
    assert _match_service(normalise("gospodarka a osnovy"))[0] is None
    assert _match_service(normalise("готовлюсь к osp"))[0] == "entrance_prep"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("экзамен 14 февраля", date(2026, 2, 14)),
        ("zkouska 3. brezna", date(2026, 3, 3)),
        ("до 14.02", date(2026, 2, 14)),
        ("сдать 01.06.2027", date(2027, 6, 1)),
        ("exam on 5 june", date(2026, 6, 5)),
        ("без даты", None),
        ("32 февраля", None),
    ],
)
def test_deadlines(text, expected):
    assert _match_deadline(normalise(text), TODAY) == expected


def test_a_past_date_means_next_year():
    """Typed in December, "14 February" is not seven weeks ago."""
    assert _match_deadline(normalise("14 февраля"), date(2026, 12, 1)) == date(
        2027, 2, 14
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("до 700", 700.0),
        ("бюджет 500 kč", 500.0),
        ("max 1200 czk", 1200.0),
        ("экзамен 14 февраля", None),
        ("физика 2", None),
        ("до 5", None),
    ],
)
def test_budget_only_when_marked_as_money(text, expected):
    assert _match_budget(normalise(text)) == expected


@pytest.mark.asyncio
async def test_full_parse_of_a_realistic_query(session):
    parsed = await parse(
        session,
        "нужен человек помочь с матаном на ČVUT, экзамен 14 февраля, до 700 kč",
        "ru",
        today=TODAY,
    )
    assert parsed.subject is not None
    assert parsed.subject.label == "Математический анализ"
    assert parsed.deadline == date(2026, 2, 14)
    assert parsed.budget_max == 700.0
    assert parsed.unmatched is False
    # Mentioning an exam does not say whether the help is wanted before it or
    # during it. Guessing here would be worse than asking, and asking is what
    # the clarify step is for.
    assert parsed.service_type is None


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_inflected_slang_still_resolves(session):
    """Russian inflects; students type "с матаном", not "матан"."""
    parsed = await parse(session, "помоги с матаном", "ru", today=TODAY)
    assert parsed.subject is not None
    assert parsed.subject.label == "Математический анализ"
    assert parsed.service_type == "tutoring"


@pytest.mark.asyncio
async def test_saying_when_removes_the_ambiguity(session):
    parsed = await parse(session, "нужна помощь на экзамене по матану", "ru", today=TODAY)
    assert parsed.service_type == "exam_live_help"


async def test_unmatched_is_reported_not_guessed(session):
    parsed = await parse(session, "asdfgh qwerty", "ru", today=TODAY)
    assert parsed.unmatched is True
    assert parsed.subject is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Help that is not about studying. Offerable since PR #29 and, until
        # these keywords existed, unfindable in words — a listing nobody could
        # reach. One phrasing per language per kind, because the catalog is read
        # in four languages and the parser is not told which one was typed.
        ("нужна страховка для визы", "insurance"),
        ("pojisteni na rok", "insurance"),
        ("insurance for a visa", "insurance"),
        ("страховка на рік", "insurance"),
        ("справка из банка", "bank_letter"),
        ("vypis z banky", "bank_letter"),
        ("bank statement", "bank_letter"),
        ("довідка з банку", "bank_letter"),
        ("перевод документов с печатью", "translation"),
        ("soudni preklad", "translation"),
        ("sworn translation", "translation"),
        ("переклад документів", "translation"),
        ("продлить ВНЖ", "residence"),
        ("prodlouzeni pobytu", "residence"),
        ("residence permit", "residence"),
        ("продовження ВНЖ", "residence"),
        ("жильё в Праге", "housing"),
        ("hledam bydleni", "housing"),
        ("looking for housing", "housing"),
        ("житло у Празі", "housing"),
    ],
)
def test_help_that_is_not_about_studying_is_recognised(text, expected):
    assert _match_service(normalise(text))[0] == expected


@pytest.mark.asyncio
async def test_a_short_faculty_name_is_not_found_inside_a_word(session):
    """`FI` is a faculty. It is also the first two letters of "физике".

    Trigram similarity scored that at 0.67 — above the threshold — so a query
    about physics came back naming a faculty nobody had mentioned.
    """
    parsed = await parse(session, "репетитор по физике", "ru", today=TODAY)
    assert parsed.institution is None


@pytest.mark.asyncio
async def test_a_named_two_letter_faculty_is_still_found(session):
    """The rule above must not cost us the faculty when it really is named.

    Two letters, and no university beside it: "ČVUT FI" would pass through the
    institution-code branch whatever the short-name rule does, and a three-letter
    name goes back to trigram matching, so neither would test the rule.
    """
    parsed = await parse(session, "матан на FI", "ru", today=TODAY)
    assert parsed.institution is not None
    assert parsed.institution.label == "FI"


@pytest.mark.asyncio
async def test_an_inflected_three_letter_faculty_still_matches(session):
    """Czech declines the abbreviation itself: nobody writes "na FEL".

    The whole-word rule is deliberately two letters wide and not three. At three
    it took every inflected form off the 69 institutions whose short name is
    three characters, 60 of them faculties.
    """
    parsed = await parse(session, "doucovani matematiky na FELu", "cs", today=TODAY)
    assert parsed.institution is not None
    assert parsed.institution.label == "FEL"


def test_a_keyword_takes_whole_words_with_it():
    """What is left has to be words, or the caller cannot ask if anything is.

    The keywords are stems: taking the characters of "нострифик" out of
    "нострификация" leaves "ация", which is not nothing and is not a word either.
    """
    assert _without(normalise("нострификация"), "нострифик") == ""
    assert _without(normalise("нострификация аттестата"), "нострифик") == "аттестата"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "нужен матан, живу в общежитии",
        "матан, снимаю квартиру на Виноградах",
    ],
)
async def test_an_aside_about_life_does_not_replace_the_subject(session, text):
    """Both filters are applied together, and no such offer has a subject.

    Reading these as housing produced subject + housing, which `catalog.search`
    ANDs into a pair matching nobody — a list of calculus tutors became an empty
    screen.
    """
    parsed = await parse(session, text, "ru", today=TODAY)
    assert parsed.subject is not None
    assert parsed.subject.label == "Математический анализ"
    assert parsed.service_type not in SUBJECTLESS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Single-word study stems used to win these on dictionary order alone:
        # "диплом" made the first thesis writing, "аттестат" made the second
        # nostrification.
        ("присяжный перевод диплома", "translation"),
        ("нужен перевод аттестата", "translation"),
        ("нотариальный перевод диплома", "translation"),
        ("i need a bank statement", "bank_letter"),
        ("bank statement for the visa", "bank_letter"),
    ],
)
async def test_document_work_survives_the_whole_parse(session, text, expected):
    """Through `parse`, not through the matcher.

    The matcher had this right while `parse` did not: a 0.55 trigram guess at a
    subject sent the kind of help back to being thesis writing, and a test on
    the private function could not see it.
    """
    parsed = await parse(session, text, "ru", today=TODAY)
    assert parsed.service_type == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "нотариальный перевод диплома",
        "bank statement for the visa",
        "нужна страховка, учусь на физике",
    ],
)
async def test_a_guessed_subject_is_dropped_not_the_kind_of_help(session, text):
    """Both filters are applied together, and these offers have no subject.

    Keeping a 0.55 trigram guess beside the kind of help is a pair that matches
    nobody, so the count and the preview on the search screen are zero for
    exactly the queries this change exists to make findable. The guess goes; a
    named subject is the other rule, two tests up.
    """
    parsed = await parse(session, text, "ru", today=TODAY)
    assert parsed.service_type in SUBJECTLESS
    assert parsed.subject is None


@pytest.mark.asyncio
async def test_a_word_naming_both_the_service_and_the_subject_survives(session):
    """ "нострификация аттестата" names the kind of help in one word and the
    subject in the other, and the stem taken out is inside the first.

    Whole words, so what is left is "аттестата" rather than the fragment "ация".
    """
    parsed = await parse(session, "нострификация аттестата", "ru", today=TODAY)
    assert parsed.service_type == "nostrification"
    assert parsed.subject is not None
    assert parsed.subject.label == "Нострификационные экзамены"


@pytest.mark.asyncio
async def test_no_subject_is_guessed_when_the_service_was_the_whole_query(session):
    """Nothing is left to name a subject, so none is guessed at.

    "bank statement" came back as Probability and Statistics at 0.61 — a filter
    narrower than the question, on a subject nobody had named.
    """
    parsed = await parse(session, "bank statement", "en", today=TODAY)
    assert parsed.service_type == "bank_letter"
    assert parsed.subject is None
    assert parsed.unmatched is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("курсовая", "Академическое письмо и дипломная работа"),
        ("нострификация", "Нострификационные экзамены"),
    ],
)
async def test_a_certain_subject_survives_being_the_whole_query(session, text, expected):
    """The rule above drops guesses, not curated names.

    These words are synonyms somebody wrote down for exactly this subject, which
    is not the scorer finding something in noise. Dropping them too would lose a
    certainty in order to avoid a maybe.
    """
    parsed = await parse(session, text, "ru", today=TODAY)
    assert parsed.subject is not None
    assert parsed.subject.matched_on == "synonym"
    assert parsed.subject.label == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # A word, not a stem: "визу" is the accusative of "виза" and the first
        # four letters of "визуализация". Read as a stem it turned a question
        # about data visualisation into a residence-permit one, and since the
        # search applies both filters together the screen went empty.
        ("нужна виза в Чехию", "residence"),
        ("визуализация данных", None),
        ("визуальное программирование", None),
    ],
)
async def test_a_visa_is_a_word_and_not_a_beginning(session, text, expected):
    parsed = await parse(session, text, "ru", today=TODAY)
    assert parsed.service_type == expected


@pytest.mark.asyncio
async def test_a_stamped_bank_paper_is_not_a_translation(session):
    """The stamp is a modifier, not the kind of document.

    Translation is checked before the study kinds, and "s razitkem" sitting in
    it shadowed bank_letter's own phrases — so the standard stamped bank
    statement for a Czech visa came back as a document translation.
    """
    parsed = await parse(session, "vypis z banky s razitkem", "cs", today=TODAY)
    assert parsed.service_type == "bank_letter"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "Чешский язык B1, нужна виза",
        "Математический анализ, живу в общежитии",
    ],
)
async def test_a_subject_typed_out_in_full_is_named(session, text):
    """A name the query reproduces exactly scores 1.0 and reports "name".

    The first spelling of "was the subject named" asked for a *synonym*, so a
    subject somebody had typed out in full was thrown away as a guess and the
    search filtered by insurance or housing instead.
    """
    parsed = await parse(session, text, "ru", today=TODAY)
    assert parsed.subject is not None
    assert parsed.subject.score == 1.0
    assert parsed.service_type not in SUBJECTLESS


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Words rather than stems, because the stems reached into subjects:
        # "pojist" prefixes "pojistna matematika" (actuarial mathematics) and
        # "страхован" prefixes the genitive in "экономика страхования".
        ("нужно страхование", "insurance"),
        ("pojistna matematika", None),
        ("экономика страхования", None),
        # And "zustat" is "to stay", so the bank balance is spelled out.
        ("zustatek na ucte", "bank_letter"),
        ("chci zustat v Praze", None),
        # English could not say two of these five in the plainest way.
        ("i need a visa", "residence"),
        ("student visa", "residence"),
        ("visualisation of data", None),
        ("document translation", "translation"),
        ("translate my diploma", "translation"),
    ],
)
def test_the_plainest_phrasing_reaches_the_right_kind(text, expected):
    assert _match_service(normalise(text))[0] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "перевод диплома, матан",
        "присяжный перевод диплома по матану",
        "перевод аттестата, линал",
        "document translations",
    ],
)
async def test_a_document_phrase_is_the_request_even_beside_a_named_subject(
    session, text
):
    """Translation is not an aside, so a named subject does not displace it.

    The rule that lets a named subject win re-reads the text with the non-study
    kinds removed — and with translation among them the study stem it was
    ordered above won again, so "перевод диплома, матан" came back as thesis
    writing. Nobody writes "присяжный перевод диплома" in passing.
    """
    parsed = await parse(session, text, "ru", today=TODAY)
    assert parsed.service_type == "translation"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # The genitive is how these are actually asked, and a multi-word keyword
        # tolerates inflection only on its last word — so the phrases that used
        # to be here reached none of them, and the first fell through to thesis
        # writing on "диплом".
        ("присяжного перевода диплома", "translation"),
        ("нотариального перевода документов", "translation"),
        ("soudniho prekladu", "translation"),
        ("продление вида на жительство", "residence"),
        ("продовження посвідки на проживання", "residence"),
    ],
)
def test_the_genitive_reaches_the_same_kind_as_the_nominative(text, expected):
    assert _match_service(normalise(text))[0] == expected


# ── words that name a shelf, and words that name a brand ─────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["přijímačky", "prijimacky", "приймачки"])
async def test_a_bare_prijimacky_names_the_kind_of_help(session, text) -> None:
    """It is a category, and a category is not one of its members.

    Carried as a synonym of «Поступление в технические вузы» it scored 1.00, so
    a word that says nothing about a subject filtered the search by maths and
    physics.
    """
    parsed = await parse(session, text, "ru", today=TODAY)
    assert parsed.service_type == "entrance_prep"
    assert parsed.subject is None, f"answered with {parsed.subject}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("вступительные экзамены", "ru"),
        ("подготовка к вступительным экзаменам", "ru"),
        ("přijímací zkoušky", "cs"),
        ("příprava na přijímací zkoušky", "cs"),
        ("entrance exams", "en"),
        ("вступні іспити", "uk"),
        ("підготовка до вступних іспитів", "uk"),
        ("вступительные испытания", "ru"),
        ("вступні екзамени", "uk"),
        ("entrance exams prep", "en"),
        ("preparation for entrance exams", "en"),
        # The way people actually ask: a verb of asking around the name.
        ("помощь с вступительными экзаменами", "ru"),
        ("нужна подготовка к вступительным", "ru"),
        ("hledám přípravu na přijímací zkoušky", "cs"),
        ("help with entrance exams", "en"),
        ("потрібна допомога з вступними іспитами", "uk"),
    ],
)
async def test_the_plain_name_of_entrance_exams_is_the_whole_query(
    session, text, lang
) -> None:
    """The catalog's own name for the kind of help, typed back at it.

    The keyword is «вступительн», and «экзамены» was left over as if it named a
    subject: «вступительные экзамены» answered «Чешский язык B1» at 0.59,
    because a synonym of that course has the word «экзамен» in it, and the list
    was empty. «Экзамены» and «подготовка» only restate the kind of help.
    """
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.service_type == "entrance_prep"
    assert parsed.subject is None, f"answered with {parsed.subject}"


@pytest.mark.asyncio
async def test_the_plain_name_of_entrance_exams_asks_no_vector(session) -> None:
    """Nothing is left to explain, so the embedder is not asked either.

    It answered a bare «přijímačky» with «Поступление в экономические вузы» at
    0.53, above its floor, and it would answer the full name the same way.
    """
    from students_cz.db.embed import rebuild
    from students_cz.services import embedding

    from .test_embedding import PointedEmbedder

    query = "подготовка к вступительным экзаменам"
    pointed = PointedEmbedder({query: "Поступление в экономические вузы (VŠE)"})
    await rebuild(session, embedder=pointed)
    embedding.set_embedder(pointed)
    try:
        parsed = await parse(session, query, "ru", today=TODAY)
    finally:
        embedding.set_embedder(None)

    assert parsed.service_type == "entrance_prep"
    assert parsed.subject is None, f"answered {parsed.subject}"
    assert parsed.vector is None, "the embedder was asked"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "lang", "expected"),
    [
        ("вступительные экзамены по физике", "ru", "Вступительный экзамен по физике"),
        ("přijímací zkoušky z matematiky", "cs", "Přijímací zkouška z matematiky"),
        ("сдать экзамен по чешскому B1", "ru", "Чешский язык B1"),
        ("příprava na zkoušku z češtiny B2", "cs", "Čeština pro cizince B2"),
        # Nothing but the level beside the exam words: the level is the subject.
        ("příprava na zkoušku B2", "cs", "Čeština pro cizince B2"),
    ],
)
async def test_a_subject_beside_the_restating_words_is_still_found(
    session, text, lang, expected
) -> None:
    """The rule above is for a query that is *only* the kind of help.

    Scoring the subject over what is left once those words go lost the shelf
    names that contain them, and the language level with the prepositions.
    """
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.subject is not None
    assert parsed.subject.label.startswith(expected), parsed.subject


@pytest.mark.asyncio
async def test_exam_help_named_in_full_carries_no_subject(session) -> None:
    parsed = await parse(session, "помощь на экзамене", "ru", today=TODAY)
    assert parsed.service_type == "exam_live_help"
    assert parsed.subject is None, f"answered with {parsed.subject}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "lang", "expected"),
    [
        ("подготовка к нострификационным экзаменам", "ru", "Нострификационные экзамены"),
        ("нострификационный экзамен", "ru", "Нострификационные экзамены"),
        ("экзамены для нострификации", "ru", "Нострификационные экзамены"),
        ("nostrifikační zkouška", "cs", "Nostrifikační zkoušky"),
        ("příprava na nostrifikaci", "cs", "Nostrifikační zkoušky"),
        ("підготовка до нострифікаційних іспитів", "uk", "Нострифікаційні іспити"),
    ],
)
async def test_a_subject_that_is_the_kind_of_help_survives_a_bare_query(
    session, text, lang, expected
) -> None:
    """Nostrification is a kind of help and a subject by the same words.

    A bare query keeps only a named subject, and these inflections score below
    1.00 — but the subject's own name is nothing but the kind of help's words,
    so it is no guess about something the query did not say.
    """
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.service_type == "nostrification"
    assert parsed.subject is not None
    assert parsed.subject.label == expected, parsed.subject


@pytest.mark.asyncio
async def test_prijimacky_for_medicine_reaches_medicine(session) -> None:
    """Written the way one language writes it, which is where this stops.

    The mixed «přijímačky на медицину» still answers with the technical subject
    at 0.67, because `find_subjects` compares one script at a time — the
    institution lookup transliterates the query and the subject lookup does not,
    so a Cyrillic word cannot reach a Latin-spelled synonym. That is a separate
    change and is deferred with the measurement; what this one owes is that the
    phrase resolves at all, rather than the category word deciding it.
    """
    parsed = await parse(session, "prijimacky na medicinu", "ru", today=TODAY)
    assert parsed.service_type == "entrance_prep"
    assert parsed.subject is not None
    assert "медицин" in parsed.subject.label.lower(), parsed.subject.label


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text", ["pvzp na rok", "нужно оформить vzp", "slavia pojisteni"]
)
async def test_an_insurer_name_is_the_insurance_it_names(session, text) -> None:
    """Nobody asks for «pojištění». They ask for VZP."""
    parsed = await parse(session, text, "ru", today=TODAY)
    assert parsed.service_type == "insurance"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # An adjective is not an ask. This block sits above the non-study kinds,
        # so a bare "чешск" made every one of these a language lesson — a study
        # kind with no subject, which is an empty screen.
        ("нужна чешская виза", "residence"),
        ("нужна чешская страховка", "insurance"),
        # "pro cizince" is not a language phrase — it attaches to whatever came
        # before it, and «zdravotní pojištění pro cizince» is the literal name
        # of the product this same change taught the parser to know by brand.
        ("zdravotni pojisteni pro cizince", "insurance"),
        ("pvzp pojisteni pro cizince na rok", "insurance"),
        ("страховка для иностранцев", "insurance"),
        ("общежитие для иностранцев", "housing"),
        ("выписка со счета в чешском банке", "bank_letter"),
        ("потрібна чеська віза", "residence"),
        ("нужен репетитор по матану", "tutoring"),
        ("репетитора по физике", "tutoring"),
        # A language can be the medium rather than the subject, and reading
        # these as language lessons would carry a maths subject no language
        # offer has — an empty screen for a query that worked.
        ("нужен репетитор по матану на чешском", "tutoring"),
        # The same, where the subject scores far lower than the language does:
        # the guard cannot be "the subject won", or these three would be
        # language lessons carrying a subject no language offer has.
        ("нужен репетитор по химии на чешском", "tutoring"),
        ("chemistry tutor in czech", "tutoring"),
        ("physics tutor in english", "tutoring"),
        ("нужен репетитор по химии на чешском 500 kc", "tutoring"),
        # "мар" is March and the first three letters of "маркетингу", so a
        # month must be discounted only when one was actually read.
        ("нужен репетитор по маркетингу на чешском", "tutoring"),
        ("marketing tutor in czech", "tutoring"),
        ("doucovani marketingu v cestine", "tutoring"),
        ("репетитор з маркетингу англійською", "tutoring"),
        # And with a date beside it, which is where discounting month *words*
        # rather than what the date matcher consumed went wrong.
        ("нужен репетитор по маркетингу на чешском 14 марта", "tutoring"),
        ("doucovani marketingu v cestine 14 unora", "tutoring"),
        ("marketing tutor in czech 14 february", "tutoring"),
        ("нужен репетитор по маркетингу на чешском 3.03", "tutoring"),
        ("i need a chemistry tutor in czech", "tutoring"),
        ("репетитор з біології англійською", "tutoring"),
        ("репетитор по чешской литературе", "tutoring"),
        ("doucovani matematiky v cestine", "tutoring"),
        ("потрібен репетитор з матану чеською", "tutoring"),
        ("calculus tutor in czech", "tutoring"),
        ("нужен перевод диплома на чешский", "translation"),
    ],
)
async def test_a_language_beside_an_errand_is_not_a_lesson(
    session, text, expected
) -> None:
    parsed = await parse(session, text, "ru", today=TODAY)
    assert parsed.service_type == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "нужен репетитор по чешскому",
        "doucovani cestiny",
        "english tutor",
        "потрібен репетитор з англійської",
        # Every one of these is how it is actually typed, and every one of them
        # inflects the *first* word — which a multi-word keyword cannot follow.
        # Matching the language on its own is what carries them.
        "ищу репетитора по чешскому",
        "посоветуйте репетитора по немецкому",
        "шукаю репетитора з англійської",
        # A course is one too, in any of the forms both halves decline into.
        "kurzy cestiny",
        "курс чешского языка",
        "на курсах чешского",
        "курси чеської",
        "czech language course",
        # The weak-verb phrasings, which name no kind of help at all until the
        # subject says what it is about.
        "помогите с чешским языком",
        "нужен чешский",
        # A level, a shade and a second language all say the same thing more
        # precisely; none of them names another subject, so none of them stops
        # this being a language lesson.
        "doucovani cestiny B2",
        "репетитор по разговорному чешскому",
        "conversational czech tutor",
        "нужен репетитор по чешскому и английскому",
        # Everything else the query said is a field of its own by the time this
        # is asked — a budget, a date, a school — so none of them can make a
        # language request look like something else.
        "репетитор по чешскому 500 kc",
        "doucovani cestiny 14 unora",
        "doucovani cestiny na ČVUT",
        # The same school as the person typed it: it resolves through a code or
        # through the transliterated query, so the label's own characters are
        # nowhere in the text.
        "репетитор по чешскому на чвуте",
        "репетитор по чешскому до 600 крон",
        "doucovani cestiny do 600 korun",
        "репетитор по чешскому 14 марта",
        # English says it with a pronoun and an article, and Czech with the
        # adjective rather than the noun.
        "i need a czech tutor",
        "i am looking for an english tutor",
        "doucovani ceskeho jazyka",
        "doucovani anglickeho jazyka",
    ],
)
async def test_asking_for_a_language_tutor_finds_languages(session, text) -> None:
    """The more specific kind of help wins the word it shares with tutoring."""
    parsed = await parse(session, text, "ru", today=TODAY)
    assert parsed.service_type == "language_tutoring"


@pytest.mark.asyncio
async def test_nostrification_is_nameable_in_english(session) -> None:
    """Czech spells it with a k and English with a c.

    The stem `nostrifik` covers «нострификация» and «nostrifikace» and misses
    «nostrification», so the English word for this kind of help reached nothing
    — the same "unnameable and therefore unfindable" failure as the five that
    are not about studying.
    """
    parsed = await parse(session, "nostrification of a school certificate", "en")
    assert parsed.service_type == "nostrification"


# ── the third mechanism: meaning ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_query_the_rules_cannot_read_reaches_a_subject(session) -> None:
    """The case the data-model doc names: no name of the subject is in it.

    A fake embedder stands in for the model, and it is rigged the only way that
    proves the wiring: the query's vector is the passage's vector.
    """
    from students_cz.db.embed import rebuild
    from students_cz.services import embedding

    from .test_embedding import PointedEmbedder

    # Measured against the seeded catalog: no synonym and no trigram reaches a
    # subject from this, which is what makes it the case worth testing.
    query = "не понимаю как считать вероятности"
    pointed = PointedEmbedder({query: "Теория вероятностей и статистика"})
    await rebuild(session, embedder=pointed)
    embedding.set_embedder(pointed)
    try:
        parsed = await parse(session, query, "ru", today=TODAY)
    finally:
        embedding.set_embedder(None)

    assert parsed.subject is not None, "the vector was not consulted"
    assert parsed.subject.matched_on == "vector"
    assert "вероятност" in parsed.subject.label.lower()


@pytest.mark.asyncio
async def test_an_unsure_vector_answers_nothing(session) -> None:
    """Nothing rather than something plausible, when nothing stands out.

    The fake's vectors are all in the positive orthant, so everything scores
    high and nothing leads — which is the lead rule's case, not the floor's.
    `test_the_floor_is_what_stops_a_distant_nearest_neighbour` is the other one.

    A wrong subject is worse than no subject either way: `catalog.search` ANDs
    the subject with everything else, so a guess turns a list into an empty
    screen.
    """
    from students_cz.db.embed import rebuild
    from students_cz.services import embedding

    from .test_embedding import FakeEmbedder

    await rebuild(session, embedder=FakeEmbedder())
    embedding.set_embedder(FakeEmbedder())
    try:
        parsed = await parse(session, "zzzz xxxx yyyy", "ru", today=TODAY)
    finally:
        embedding.set_embedder(None)

    assert parsed.subject is None, f"answered {parsed.subject}"


@pytest.mark.asyncio
async def test_a_named_subject_is_never_overruled_by_the_vector(session) -> None:
    """The synonym is curated and scores 1.00; the embedder loses to it on slang."""
    from students_cz.db.embed import rebuild
    from students_cz.services import embedding

    from .test_embedding import PointedEmbedder

    pointed = PointedEmbedder({"матан": "Чешский язык B1"})
    await rebuild(session, embedder=pointed)
    embedding.set_embedder(pointed)
    try:
        parsed = await parse(session, "матан", "ru", today=TODAY)
    finally:
        embedding.set_embedder(None)

    assert parsed.subject is not None
    assert parsed.subject.matched_on != "vector"
    assert "анализ" in parsed.subject.label.lower()


@pytest.mark.asyncio
async def test_the_vector_is_a_guess_and_loses_to_a_subjectless_kind(session) -> None:
    """«нужна чешская виза» proposed «Чешский язык B2» at 0.50, measured.

    A kind of help that carries no subject cannot be answered with one — the
    search ANDs them and the pair matches nobody. That rule already exists, and
    the vector has to be asked before it rather than after, or its answer walks
    straight past it.
    """
    from students_cz.db.embed import rebuild
    from students_cz.services import embedding

    from .test_embedding import PointedEmbedder

    # Something is left over beside the visa, so the vector *is* asked — and
    # what it proposes still cannot survive next to a kind of help that carries
    # no subject.
    query = "нужна виза зззз ыыыы"
    pointed = PointedEmbedder({query: "Чешский язык B2 (для вуза и нострификации)"})
    await rebuild(session, embedder=pointed)
    embedding.set_embedder(pointed)
    try:
        parsed = await parse(session, query, "ru", today=TODAY)
    finally:
        embedding.set_embedder(None)

    assert parsed.service_type == "residence"
    assert parsed.subject is None, f"answered {parsed.subject}"
    assert parsed.vector is not None, "and it still says what it proposed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cosine", "answered"),
    [
        # Above the floor and clear of everything else: believed.
        (0.60, True),
        # The nearest thing in the catalog, and still not near: refused. A wrong
        # subject is worse than none, because the search ANDs it with the rest.
        (0.30, False),
    ],
)
async def test_the_floor_is_what_stops_a_distant_nearest_neighbour(
    session, cosine, answered
) -> None:
    from students_cz.db.embed import rebuild
    from students_cz.services import embedding

    from .test_embedding import RiggedEmbedder

    rigged = RiggedEmbedder("Теория вероятностей и статистика", cosine)
    await rebuild(session, embedder=rigged)
    embedding.set_embedder(rigged)
    try:
        parsed = await parse(
            session, "не понимаю как считать вероятности", "ru", today=TODAY
        )
    finally:
        embedding.set_embedder(None)

    assert parsed.vector is not None, "it always says what it proposed"
    assert (parsed.subject is not None) is answered


@pytest.mark.parametrize(
    ("text", "lang", "expected"),
    [
        ("помогите с линейной алгеброй", "ru", "Линейная алгебра"),
        ("нужна помощь по линейной алгебре", "ru", "Линейная алгебра"),
        ("помогите с математическим анализом", "ru", "Математический анализ"),
        ("подтянуть теорию вероятностей", "ru", "Теория вероятностей и статистика"),
        ("с дифференциальными уравнениями", "ru", "Дифференциальные уравнения"),
        ("по квантовой физике", "ru", "Квантовая физика"),
        ("допомога з лінійною алгеброю", "uk", "Лінійна алгебра"),
        ("з лінійної алгебри", "uk", "Лінійна алгебра"),
        ("pomoc s lineární algebrou", "cs", "Lineární algebra"),
        ("doučování organické chemie", "cs", "Organická chemie"),
        ("pomoc s diskrétní matematikou", "cs", "Diskrétní matematika"),
    ],
)
async def test_a_subject_named_in_any_case_is_named(session, text, lang, expected):
    """Russian, Ukrainian and Czech decline every word of a subject's name:
    «линейной алгеброй» names «Линейная алгебра» as surely as the nominative.
    It scores only about 0.6 by trigrams, so any stray synonym above that —
    «экзамен b1» at 0.67 — took the title from it."""
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.subject is not None
    assert parsed.subject.label == expected


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("экзамен через две недели", "ru"),
        ("іспит через два тижні", "uk"),
        ("zkouška za dva týdny", "cs"),
        ("exam in two weeks", "en"),
    ],
)
async def test_an_exam_and_its_timing_name_no_subject(session, text, lang):
    """«экзамен b1» is a synonym of Czech B1, and the word «экзамен» alone
    scored it 0.67: a request about an exam was titled «Чешский язык B1»."""
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.subject is None, parsed.subject


async def test_an_exam_beside_a_declined_subject_keeps_the_subject(session):
    parsed = await parse(
        session,
        "помогите с линейной алгеброй, экзамен через две недели",
        "ru",
        today=TODAY,
    )
    assert parsed.subject is not None
    assert parsed.subject.label == "Линейная алгебра"
    assert parsed.alternatives.get("subject", []) == []
