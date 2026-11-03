[Product](README.md) / **Articles**

# Articles

How Konnekt writes the articles on konnekt.cz (`/articles/`) and how an article
reaches the public site. An article is one Markdown file per language in
`web/site/src/content/articles/<lang>/<slug>.md`. The fields it carries, and
which of them a published article must have, are the schema in
`web/site/src/content.config.ts`; this page says how to fill them.

## What an article is

An article helps a student from the CIS, or someone about to become one, with
studying or living in Czechia. It has a `type`:

- `guide` (the default): one task, finished by following it: applying to a
  university, getting a diploma recognised (nostrifikace), a visa or residence
  permit, a dormitory, a scholarship. Numbered steps, the documents and
  deadlines, where to go and what to expect there. It stays true until it is
  updated.
- `news`: what changed and from when, for one change of a rule, deadline or
  fee. It is of its day and is not updated afterwards.

It belongs to one `rubric`: `admission` (поступление), `visa` (виза и ВНЖ),
`housing` (жильё), `study` (учёба) or `work` (работа и деньги). `tags` narrow
it further.

It states what the official source says, never advice from chats or forums that
nobody has checked.

## Facts come from a primary source

Every number, deadline, fee, document and rule has a primary source, linked in
the text right where the claim is made. A claim with no source is cut. A
retelling in a chat, a forum, a competitor's channel or another article is not
a source; it can point to one.

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
disagree, the article says so and links both.

The writer keeps a claim list while drafting: each claim, its source URL, the
quoted line from the source, and the date it was read. The list is a working
file and is not committed.

Each source the article relies on also goes into `sources` in the frontmatter,
with its `title` and `checked_at`, the date it was last read to confirm the
claim. The inline link and the `sources` entry use the same URL. A published
article without `sources` does not build.

Sources go stale: deadlines and fees change every year. A guide says which
academic year it describes, and a source read more than six months before
publication is read again and its `checked_at` moved.

## Authors and dates

- `author` is `konnekt` (Редакция Konnekt) for an article the editorial team
  wrote, agents included, or `azamat` for one Azamat wrote. Never an
  invented person.
- `reviewedBy` is `azamat`: the page names Azamat as the one who checked it. A
  published article without it does not build, so it is set only once Azamat
  has read the article.
- `published` is the day the article first goes public. A draft must have one
  too; it is the day of drafting until the article is approved. `updated` moves only
  for a change of substance (a new fee, deadline, step or source), never for a
  typo, and is not earlier than `published`.

## Languages

- Russian first, then Ukrainian and English. There is no Czech version of an
  article: its readers do not yet read Czech.
- Each language is its own file with its own slug, in that language's words but
  in Latin letters. The translations of one article share `translationKey`,
  which is how the site links them and tells search engines they are one page.
- Each language reads as written for its reader, not translated word for word.

## Writing

- Short, plain sentences. Friendly, not familiar; no sales tone and at most one
  exclamation mark in an article.
- Official Czech names stay in Czech, explained the first time they appear, for
  example «nostrifikace (признание иностранного диплома)», «Odbor azylové a
  migrační politiky (OAMP, миграционный отдел МВД)». A form or office is named
  as it is written on the official page, so the reader can find it there.
- Numbers follow the language: in Russian and Ukrainian a decimal comma and a
  space before the unit, «1 500 Kč», «0,5 л».
- Phrases that mark machine-written text are removed: «в современном мире»,
  «ключевой», «важно отметить», «стоит отметить», «не только…, но и»,
  «комплексный подход», «в заключение», a closing paragraph that repeats the
  article. The `humanizer` and `stop-slop` skills (user-level, in
  `~/.claude/skills/`) catch the rest.

## Markup

- Standard Markdown. A step is an item of a numbered list; a document list is a
  bulleted list; a table is for comparing options.
- Links are inline on the words they support, not bare URLs. `sources` in the
  frontmatter does not replace them.
- A screenshot is from the official site itself and has alternative text in the
  article's language. An article is text first; it does not need figures. A
  `cover` needs `coverAlt`.

## Search

- `title` is at most 50 characters, so the page title with « — Konnekt» stays
  within 60.
- `description` is 120 to 155 characters and says what the reader can do after
  reading.
- The slug is lowercase Latin words joined by hyphens, without diacritics.
  `topics` and `tags` are the section's own and cannot be slugs.
- Each article links the related universities or chats on konnekt.cz and
  related articles.

## From draft to production

1. The writer adds the article with `draft: true` on a branch and opens a pull
   request. A draft is still built: it appears on konnekt.cz with an «Пример»
   badge and is kept out of search. So a draft is not merged before approval
   either; every merge to main deploys konnekt.cz.
2. A fact-checker checks the claim list and the draft against the sources.
3. A fresh reader, who sees only the rendered dev page, follows the steps as a
   newcomer and reports where they get stuck.
4. The dev page is looked at in a browser at 1280 px and 390 px.
5. Findings are fixed. Any rewrite after the fact check sends the article
   through the fact check again.
6. Azamat approves the article. Then, on the same branch, `reviewedBy: azamat`
   is set, `published` moves to the day of the merge, `draft: true` is removed,
   and the pull request is merged.

The project agents in `.claude/agents/` (`article-writer`,
`article-fact-checker`, `article-fresh-reader`) follow this page.
