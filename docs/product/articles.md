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
  university, getting a school certificate or diploma recognised
  (nostrifikace), a visa or residence
  permit, a dormitory, a scholarship. Numbered steps, the documents and
  deadlines, where to go and what to expect there. It stays true until it is
  updated.
- `news`: what changed and from when, for one change of a rule, deadline or
  fee. It is of its day and is not updated afterwards.

It belongs to one `rubric`: `admission` (поступление), `visa` (виза и ВНЖ),
`housing` (жильё), `study` (учёба) or `work` (работа и деньги). `tags` narrow
it further.

It states what the official source says, never advice from chats or forums that
nobody has checked. Practical experience comes in only through the field notes
below, and is written as experience.

## Facts come from a primary source

Every number, deadline, fee, document and rule has a primary source, cited by
a footnote right where the claim is made. A claim with no source is cut. A
retelling in a chat, a forum, a competitor's channel or another article is not
a source; it can point to one.

| Fact | Primary source |
| --- | --- |
| Laws, legal deadlines, rights | The law itself in the official Collection of Laws, e-Sbírka (`e-sbirka.gov.cz`, for example zákon č. 111/1998 Sb., o vysokých školách) |
| Visas, long-term and permanent residence | The Ministry of the Interior (`mv.gov.cz` and its portal for foreigners `ipc.gov.cz`) and the Czech embassy in the reader's country (`mzv.gov.cz`) |
| Certificate and diploma recognition (nostrifikace) | The page of the university or regional office that grants it, and `msmt.gov.cz` |
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

Each source the article relies on goes into `sources` in the frontmatter, with
its `title` and `checked_at`, the date it was last read to confirm the claim.
Each footnote links one of those sources. When an article has footnotes, a
note whose link is not in `sources`, or a listed source no note cites, stops
the build; an article with `sources` and no footnotes still builds, so the
fact checker looks for that. A published article without `sources` does not
build.

A comparison names its rule for what it includes. Two universities' deadlines
with no reason for those two read as a random pick: either say why these, or
list every option the reader is likely to face. Where an option publishes
nothing, its row stays and says «не опубликовано».

Sources go stale: deadlines and fees change every year. A guide says which
academic year it describes, and a source read more than six months before
publication is read again and its `checked_at` moved.

## Glossary and field notes

The law says what is allowed; it does not say how readers talk or what they
usually end up doing. Two files in `docs/content/` keep that:

- [glossary.md](../content/glossary.md): each term as readers say it, its
  official name, a short explanation and the article that explains it. A
  term with no word yet in the article's language is reported, not guessed.
- [field-notes.md](../content/field-notes.md): practical things that are not
  in the law, each with where it comes from and when. Experience is written as
  experience, not as a rule. Notes are grouped by rubric. A note marked
  «Context only» informs the writer and never goes into an article.

The writer reads both before drafting, and the fact checker checks the article
against them. Every review Azamat gives on an article becomes a glossary row
or a field note, not only a fix in that article, so the next article starts
from it, and is applied to every open article it bears on, not only the one
it was about.

**Newest notes.** An article's branch may be older than the notes, so the
agents do not read them from their own checkout. They run `git fetch origin`
and read each file with `git show <ref>:docs/content/<file>`, where `<ref>` is
`origin/<branch>` of the open pull request that changes `docs/content/`, if
there is one, and `origin/main` otherwise:

```bash
gh pr list --state open --json headRefName,files \
  -q '.[] | select(any(.files[]; .path | startswith("docs/content/"))) | .headRefName'
```

If that lists more than one branch, read each. A note added after the draft
was written still counts: the fact check is against the newest notes.

## Authors and dates

- `author` is `konnekt` (Редакция Konnekt) for an article the editorial team
  wrote, agents included, or `azamat` for one Azamat wrote. Never an
  invented person.
- `reviewedBy` is `azamat`: the page names Azamat as the one who checked it,
  under «Проверил». A
  published article without it does not build, so it is set only once Azamat
  has read the article.
- `published` is the day the article first goes public. A draft must have one
  too: the writer puts the day of drafting, and it moves to the day of the
  merge. `updated` moves only
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
- A term is the word readers use, from the glossary: «нострифицировать
  аттестат», not «оценить аттестат». The official Czech name follows in
  brackets at its first use, «нострификация (nostrifikace)», and an office is
  explained the same way, «миграционный отдел МВД (Odbor azylové a migrační
  politiky, OAMP)». A form or office is named as it is written on the official
  page, so the reader can find it there.
- An article that uses a term links the published article that explains it,
  as the glossary names it.
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
- A guide opens with «Коротко» (in each language's words): the deadlines, sums
  and first step, a few bullets. It names no single option out of several; it
  gives the range and points to the section with the full list.
- Sources are GFM footnotes, `[^mv]`, with the note at the end of the file
  linking the source. A footnote mark goes at the end of the phrase or after
  the number, never between a name and its number: «poplatek MV[^mv] 300 Kč»
  renders as «poplatek MV⁵ 300 Kč» and reads as 5 300 Kč.
- Other links (konnekt.cz pages, other articles) are inline on the words they
  support, not bare URLs.
- A screenshot is from the official site itself and has alternative text in the
  article's language. An article is text first; it does not need figures. A
  `cover` needs `coverAlt`.

## Search

- `title` is at most 50 characters, so the page title with « — Konnekt» stays
  within 60.
- `description` is 120 to 155 characters and says what the reader can do after
  reading.
- The slug is lowercase Latin words joined by hyphens, without diacritics. An
  article's slug cannot be `topics` or `tags`: those addresses are the
  section's own.
- `tags` and `translationKey` are lowercase Latin words joined by hyphens in
  every language, Russian included; the build refuses anything else. A tag
  must be listed in `web/site/src/content/tags.yaml` with its name in each
  language; a new tag is added there in the same pull request.
- Each article links the related universities or chats on konnekt.cz and the
  published articles it builds on.

## From draft to production

1. The writer adds the article with `draft: true` on a branch and opens a pull
   request. A draft is still built: it appears on konnekt.cz with an «Example»
   badge («Пример» in Russian) and is kept out of search. So a draft is not
   merged before approval either; every merge to main deploys konnekt.cz.
2. A fact-checker checks the claim list and the draft against the sources.
3. A fresh reader, who sees only the rendered dev page, follows the steps as a
   newcomer and reports where they get stuck.
4. The dev page is looked at in a browser at 1280 px and 390 px.
5. Findings are fixed. Any rewrite after the fact check sends the article
   through the fact check again. What Azamat says in review goes into the
   glossary or the field notes in the same pull request, added by whoever makes
   the fix.
6. Azamat approves the article. Then, on the same branch, `reviewedBy: azamat`
   is set, `published` moves to the day of the merge, `draft: true` is removed,
   the glossary's «Explained in» gets this article for the terms it explains,
   and the pull request is merged.

The project agents in `.claude/agents/` (`article-writer`,
`article-fact-checker`, `article-fresh-reader`) follow this page.
