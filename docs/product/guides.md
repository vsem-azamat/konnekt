[Product](README.md) / **Guides**

# Guides

How Konnekt writes the guides on konnekt.cz (`/guides/`) and how a guide
reaches the public site. A guide is one Markdown file per language in
`web/site/src/content/guides/<lang>/<slug>.md`; a translation keeps the slug of
the original.

## What a guide is

A guide helps a student from the CIS, or someone about to become one, finish
one task about studying or living in Czechia: applying to a university, getting
a diploma recognised (nostrifikace), a visa or residence permit, a dormitory, a
scholarship. It is a how-to: numbered steps, the documents and deadlines, where
to go and what to expect there. It states what the official source says, never
advice from chats or forums that nobody has checked.

## Facts come from a primary source

Every number, deadline, fee, document and rule has a primary source, linked in
the text right where the claim is made. A claim with no source is cut. A
retelling in a chat, a forum, a competitor's channel or another guide is not a
source; it can point to one.

| Fact | Primary source |
| --- | --- |
| Laws, legal deadlines, rights | The law itself in the official Collection of Laws, e-Sbírka (`e-sbirka.gov.cz`, for example zákon č. 111/1998 Sb., o vysokých školách) |
| Visas, long-term and permanent residence | The Ministry of the Interior (`mv.gov.cz` and its portal for foreigners `ipc.gov.cz`) and the Czech embassy in the reader's country (`mzv.gov.cz`) |
| Diploma recognition (nostrifikace) | The page of the university or regional office that grants it, and `msmt.gov.cz` |
| Admission, entrance exams, deadlines, tuition, scholarships, dormitories | The official page of that university or faculty for the current academic year |
| Health insurance | The insurer's own page and the law it cites |
| Prices that are not set by law | The provider's own page, with the date it was read |
| Konnekt's own data: universities, chats, tutors | konnekt.cz and the catalog API, not memory |

When an official source exists in Czech, the Czech page wins over a translation
of it, including the university's own English page. When two official sources
disagree, the guide says so and links both.

The writer keeps a claim list while drafting: each claim, its source URL, the
quoted line from the source, and the date it was read. The list is a working
file and is not committed.

Sources go stale: deadlines and fees change every year. A guide says which
academic year it describes, and a source read more than six months before
publication is read again.

## Language

- Russian first, then Ukrainian, Czech and English. Each language reads as
  written for its reader, not translated word for word.
- Short, plain sentences. Friendly, not familiar; no sales tone and at most one
  exclamation mark in a guide.
- Official Czech names stay in Czech, explained the first time they appear, for
  example «nostrifikace (признание иностранного диплома)», «Odbor azylové a
  migrační politiky (OAMP, миграционный отдел МВД)». A form or office is named
  as it is written on the official page, so the reader can find it there.
- Numbers follow the language: in Russian and Czech a decimal comma and a space
  before the unit, «1 500 Kč», «0,5 л».
- Phrases that mark machine-written text are removed: «в современном мире»,
  «ключевой», «важно отметить», «стоит отметить», «не только…, но и»,
  «комплексный подход», «в заключение», a closing paragraph that repeats the
  guide. The `humanizer` and `stop-slop` skills (user-level, in
  `~/.claude/skills/`) catch the rest.

## Markup

- Standard Markdown. A step is an item of a numbered list; a document list is a
  bulleted list; a table is for comparing options.
- Links are inline on the words they support, not bare URLs and not a list of
  sources at the end alone.
- A screenshot is from the official site itself and has alternative text in the
  guide's language. A guide is text first; it does not need figures.

## Search

- `title` is at most 50 characters, so the page title with the site name
  stays within 60.
- `description` is 120 to 155 characters and says what the reader can do after
  reading.
- The slug is in Latin letters without diacritics and is the same in every
  language.
- Each guide links the related universities or chats on konnekt.cz and related
  guides.

## From draft to production

1. The writer adds the guide with `draft: true` on a branch and opens a pull
   request. A draft is kept out of search.
2. A fact-checker checks the claim list and the draft against the sources.
3. A fresh reader, who sees only the rendered dev page, follows the steps as a
   newcomer and reports where they get stuck.
4. The dev page is looked at in a browser at 1280 px and 390 px.
5. Findings are fixed. Any rewrite after the fact check sends the guide through
   the fact check again.
6. Azamat approves the guide before `draft: true` is removed and the pull
   request is merged: every merge to main deploys konnekt.cz.

The project agents in `.claude/agents/` follow this page.
