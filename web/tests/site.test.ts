import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  alternates,
  articlePath,
  authorPages,
  checkArticles,
  hiddenPaths,
  indexed,
  langOf,
  listings,
  localePath,
  readFrontmatter,
  related,
  sitemapLinks,
  telegramHome,
  translationsOf,
  versionsOf,
} from '../site/src/paths.ts';

test('Russian lives at the root, the other languages under their prefix', () => {
  assert.equal(localePath('ru', '/'), '/');
  assert.equal(localePath('uk', '/'), '/uk/');
  assert.equal(localePath('cs', '/articles/'), '/cs/articles/');
  assert.equal(localePath('en', '/articles/visa/'), '/en/articles/visa/');
});

test('an article is addressed by its language and slug', () => {
  assert.equal(articlePath('ru/viza'), '/articles/viza/');
  assert.equal(articlePath('en/visa'), '/en/articles/visa/');
  assert.equal(langOf('uk/viza'), 'uk');
});

test('hreflang names every version, and Russian as the default', () => {
  assert.deepEqual(
    alternates(versionsOf('/chats/', ['ru', 'cs']), 'https://konnekt.cz'),
    [
      { hreflang: 'ru', href: 'https://konnekt.cz/chats/' },
      { hreflang: 'cs', href: 'https://konnekt.cz/cs/chats/' },
      { hreflang: 'x-default', href: 'https://konnekt.cz/chats/' },
    ],
  );
});

test('a page with no Russian version has no default to point at', () => {
  assert.deepEqual(
    alternates(versionsOf('/articles/x/', ['en']), 'https://konnekt.cz/'),
    [{ hreflang: 'en', href: 'https://konnekt.cz/en/articles/x/' }],
  );
});

const russian = { id: 'ru/viza-studenta', draft: false, translationKey: 'student-visa' };
const english = { id: 'en/student-visa', draft: false, translationKey: 'student-visa' };
const visa = [
  russian,
  english,
  { id: 'ru/zhile', draft: false, translationKey: 'housing' },
];

test('the translations of an article are found by its key, each at its own slug', () => {
  const versions = translationsOf(english, visa);
  assert.deepEqual(versions, [
    { lang: 'ru', path: '/articles/viza-studenta/' },
    { lang: 'en', path: '/en/articles/student-visa/' },
  ]);
  assert.deepEqual(alternates(versions, 'https://konnekt.cz'), [
    { hreflang: 'ru', href: 'https://konnekt.cz/articles/viza-studenta/' },
    { hreflang: 'en', href: 'https://konnekt.cz/en/articles/student-visa/' },
    { hreflang: 'x-default', href: 'https://konnekt.cz/articles/viza-studenta/' },
  ]);
});

test('two articles in one language may not share a translation key', () => {
  checkArticles(visa);
  const twice = [
    ...visa,
    { id: 'ru/viza-2027', draft: false, translationKey: 'student-visa' },
  ];
  assert.throws(() => checkArticles(twice), /ru\/viza-studenta and ru\/viza-2027/);
});

test('an article may not take a slug of the section’s own pages', () => {
  for (const slug of ['topics', 'tags']) {
    const article = { id: `ru/${slug}`, draft: false, translationKey: slug };
    assert.throws(() => checkArticles([article]), /the section's own/);
  }
});

test('the site hands a Telegram launch on to the app, launch data and all', () => {
  const data = '#tgWebAppData=user%3D1&tgWebAppVersion=8.0';
  const app = 'https://app.konnekt.cz';
  assert.equal(telegramHome(data, '', app), `${app}/home${data}`);
  assert.equal(telegramHome(data, '?x=1', `${app}/`), `${app}/home?x=1${data}`);
});

test('a launch on the public catalogue opens the app’s own chats', () => {
  // Buttons sent in Telegram named konnekt.cz/chats while it was the app.
  const data = '#tgWebAppData=user%3D1&tgWebAppVersion=8.0';
  const app = 'https://app.konnekt.cz';
  assert.equal(telegramHome(data, '', app, '/chats/'), `${app}/chats${data}`);
  assert.equal(telegramHome(data, '', app, '/uk/chats/'), `${app}/chats${data}`);
  assert.equal(telegramHome(data, '', app, '/universities/cvut/'), `${app}/home${data}`);
});

test('a browser stays on the site', () => {
  assert.equal(telegramHome('', '', 'https://app.konnekt.cz'), null);
  assert.equal(telegramHome('#guides', '?q=1', 'https://app.konnekt.cz'), null);
});

test('draft articles and an index with no published article are kept out of search', () => {
  const articles = [
    { id: 'ru/primer', draft: true, translationKey: 'primer' },
    { id: 'ru/viza', draft: false, translationKey: 'visa' },
    { id: 'en/example', draft: true, translationKey: 'primer' },
  ];
  assert.deepEqual(hiddenPaths(articles).sort(), [
    '/articles/primer/',
    '/cs/articles/',
    '/en/articles/',
    '/en/articles/example/',
    '/uk/articles/',
  ]);
});

test('hreflang names only the versions search engines may keep', () => {
  const hidden = [
    '/en/articles/student-visa/',
    '/uk/articles/',
    '/cs/articles/',
    '/en/articles/',
  ];
  assert.deepEqual(indexed(translationsOf(russian, visa), hidden), [
    { lang: 'ru', path: '/articles/viza-studenta/' },
  ]);
  assert.deepEqual(
    indexed(versionsOf('/articles/', ['ru', 'uk', 'cs', 'en']), hidden).map(
      (v) => v.lang,
    ),
    ['ru'],
  );
  assert.deepEqual(
    indexed(versionsOf('/', ['ru', 'uk', 'cs', 'en']), hidden).map((v) => v.lang),
    ['ru', 'uk', 'cs', 'en'],
  );
});

test('an author has a page in each language they wrote or checked in, hidden while all are examples', () => {
  const articles = [
    {
      id: 'ru/primer',
      draft: true,
      translationKey: 'primer',
      people: ['konnekt', 'azamat'],
    },
    {
      id: 'ru/viza',
      draft: false,
      translationKey: 'visa',
      people: ['konnekt', 'azamat'],
    },
    { id: 'en/visa', draft: true, translationKey: 'visa', people: ['azamat'] },
  ];
  assert.deepEqual(authorPages(articles), [
    { id: 'konnekt', lang: 'ru', hidden: false },
    { id: 'azamat', lang: 'ru', hidden: false },
    { id: 'azamat', lang: 'en', hidden: true },
  ]);
  assert.ok(hiddenPaths(articles).includes('/en/authors/azamat/'));
  assert.ok(!hiddenPaths(articles).includes('/authors/azamat/'));
});

const listed = [
  {
    id: 'ru/a',
    draft: false,
    translationKey: 'a',
    rubric: 'visa',
    tags: ['vnzh', 'prodlenie'],
  },
  { id: 'ru/b', draft: false, translationKey: 'b', rubric: 'visa', tags: ['vnzh'] },
  { id: 'ru/c', draft: false, translationKey: 'c', rubric: 'housing', tags: ['vnzh'] },
  { id: 'ru/d', draft: true, translationKey: 'd', rubric: 'study', tags: ['prodlenie'] },
  { id: 'en/a', draft: false, translationKey: 'a', rubric: 'visa', tags: ['prodlenie'] },
];

test('a rubric has a page in each language it has an article in, hidden while all are examples', () => {
  const rubrics = listings(listed).filter((page) => page.kind === 'topics');
  assert.deepEqual(rubrics, [
    {
      kind: 'topics',
      key: 'visa',
      lang: 'ru',
      path: '/articles/topics/visa/',
      count: 2,
      hidden: false,
    },
    {
      kind: 'topics',
      key: 'housing',
      lang: 'ru',
      path: '/articles/topics/housing/',
      count: 1,
      hidden: false,
    },
    {
      kind: 'topics',
      key: 'study',
      lang: 'ru',
      path: '/articles/topics/study/',
      count: 0,
      hidden: true,
    },
    {
      kind: 'topics',
      key: 'visa',
      lang: 'en',
      path: '/en/articles/topics/visa/',
      count: 1,
      hidden: false,
    },
  ]);
});

test('a tag is kept out of search until three published articles carry it', () => {
  const tags = listings(listed).filter((page) => page.kind === 'tags');
  const hidden = Object.fromEntries(tags.map((page) => [page.path, page.hidden]));
  assert.deepEqual(hidden, {
    '/articles/tags/vnzh/': false,
    '/articles/tags/prodlenie/': true,
    '/en/articles/tags/prodlenie/': true,
  });
  assert.ok(hiddenPaths(listed).includes('/articles/tags/prodlenie/'));
  assert.ok(!hiddenPaths(listed).includes('/articles/tags/vnzh/'));
  assert.ok(hiddenPaths(listed).includes('/articles/topics/study/'));
});

test('read next: the same rubric first, then shared tags, never itself, examples, or another language', () => {
  const a = listed[0] as (typeof listed)[number];
  assert.deepEqual(
    related(a, listed, 3).map((x) => x.id),
    ['ru/b', 'ru/c'],
  );
});

test('the sitemap pairs translations by key, not by a slug they happen to share', () => {
  const articles = [
    russian,
    english,
    { id: 'ru/erasmus', draft: false, translationKey: 'erasmus-ru' },
    { id: 'en/erasmus', draft: false, translationKey: 'erasmus-en' },
  ];
  assert.deepEqual(
    sitemapLinks('/en/articles/student-visa/', articles, [], 'https://konnekt.cz'),
    [
      { lang: 'ru', url: 'https://konnekt.cz/articles/viza-studenta/' },
      { lang: 'en', url: 'https://konnekt.cz/en/articles/student-visa/' },
      { lang: 'x-default', url: 'https://konnekt.cz/articles/viza-studenta/' },
    ],
  );
  assert.deepEqual(
    sitemapLinks('/articles/erasmus/', articles, [], 'https://konnekt.cz'),
    [
      { lang: 'ru', url: 'https://konnekt.cz/articles/erasmus/' },
      { lang: 'x-default', url: 'https://konnekt.cz/articles/erasmus/' },
    ],
  );
  // Not an article: the sitemap's own pairing by path stands.
  assert.equal(sitemapLinks('/uk/', articles, [], 'https://konnekt.cz'), undefined);
});

test('a file name that is not already its slug is refused, as Astro would change it', () => {
  for (const id of ['ru/Draft_Case', 'ru/Tags', 'ru/viza studenta']) {
    assert.throws(
      () => checkArticles([{ id, draft: true, translationKey: 'x' }]),
      /slug/,
    );
  }
});

test('the config reads frontmatter the way Astro does, or refuses', () => {
  assert.deepEqual(readFrontmatter('\uFEFF---\ndraft: true\n---\ntext', 'ru/a.md'), {
    draft: true,
  });
  assert.deepEqual(readFrontmatter('---\r\ndraft: false\r\n---\r\n', 'ru/a.md'), {
    draft: false,
  });
  assert.throws(() => readFrontmatter('draft: true\n', 'ru/a.md'), /ru\/a.md/);
});
