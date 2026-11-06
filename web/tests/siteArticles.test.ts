import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  articleGraph,
  day,
  jsonLd,
  profileGraph,
} from '../site/src/articles/structured.ts';
import { newestPublished, rubricTally } from '../site/src/paths.ts';
import { articleCount } from '../site/src/texts.ts';

const site = 'https://konnekt.cz/';
const azamat = {
  kind: 'person' as const,
  name: 'Azamat',
  url: 'https://konnekt.cz/authors/azamat/',
};
const team = {
  kind: 'organization' as const,
  name: 'Редакция Konnekt',
  url: 'https://konnekt.cz/',
};

const article = {
  type: 'guide' as const,
  url: 'https://konnekt.cz/articles/viza-studenta/',
  lang: 'ru' as const,
  headline: 'Виза студента в Чехию',
  description: 'Что нужно для долгосрочной визы на учёбу.',
  published: new Date('2026-11-03'),
  author: team,
  reviewer: azamat,
  crumbs: [
    { name: 'Konnekt', url: 'https://konnekt.cz/' },
    { name: 'Статьи', url: 'https://konnekt.cz/articles/' },
  ],
};

function node(graph: { '@graph': Record<string, unknown>[] }, type: string) {
  const found = graph['@graph'].find((n) => n['@type'] === type);
  assert.ok(found, `no ${type}`);
  return found;
}

test('a guide is an Article, news a NewsArticle', () => {
  assert.equal(node(articleGraph(article, site), 'Article').headline, article.headline);
  assert.ok(
    articleGraph({ ...article, type: 'news' }, site)['@graph'].some(
      (n) => n['@type'] === 'NewsArticle',
    ),
  );
});

test('an article never updated was modified when it was published', () => {
  const ld = node(articleGraph(article, site), 'Article');
  assert.equal(ld.datePublished, '2026-11-03');
  assert.equal(ld.dateModified, '2026-11-03');
  const updated = node(
    articleGraph({ ...article, updated: new Date('2026-12-01') }, site),
    'Article',
  );
  assert.equal(updated.dateModified, '2026-12-01');
});

test('the author is named as the kind it is, the reviewer on the page', () => {
  const graph = articleGraph(article, site);
  assert.deepEqual(node(graph, 'Article').author, {
    '@type': 'Organization',
    name: 'Редакция Konnekt',
    url: 'https://konnekt.cz/',
  });
  assert.deepEqual(node(graph, 'WebPage').reviewedBy, {
    '@type': 'Person',
    name: 'Azamat',
    url: 'https://konnekt.cz/authors/azamat/',
  });
});

test('the publisher is Konnekt, with its logo', () => {
  const org = node(articleGraph(article, site), 'Organization');
  assert.equal(org.url, 'https://konnekt.cz/');
  assert.equal(org.logo, 'https://konnekt.cz/apple-touch-icon.png');
});

test('the breadcrumbs end at the article itself', () => {
  const list = node(articleGraph(article, site), 'BreadcrumbList');
  assert.deepEqual(list.itemListElement, [
    { '@type': 'ListItem', position: 1, name: 'Konnekt', item: 'https://konnekt.cz/' },
    {
      '@type': 'ListItem',
      position: 2,
      name: 'Статьи',
      item: 'https://konnekt.cz/articles/',
    },
    { '@type': 'ListItem', position: 3, name: article.headline },
  ]);
});

test('a profile page is about its person, with the links that are theirs', () => {
  const graph = profileGraph({ ...azamat, links: ['https://t.me/example'] });
  const page = node(graph, 'ProfilePage');
  assert.deepEqual(page.mainEntity, {
    '@type': 'Person',
    name: 'Azamat',
    url: 'https://konnekt.cz/authors/azamat/',
    sameAs: ['https://t.me/example'],
  });
});

test('structured data cannot close its script element', () => {
  assert.equal(jsonLd({ a: '</script><b>' }), '{"a":"\\u003c/script>\\u003cb>"}');
});

test('a day is written the way schema.org reads it, in UTC', () => {
  assert.equal(day(new Date('2026-11-03')), '2026-11-03');
});

test('the landing shows the newest published articles in its language only', () => {
  const at = (id: string, draft: boolean, published: string) => ({
    id,
    draft,
    translationKey: id,
    published: new Date(published),
  });
  const articles = [
    at('ru/old', false, '2026-10-01'),
    at('ru/draft', true, '2026-11-02'),
    at('en/visa', false, '2026-11-03'),
    at('ru/new', false, '2026-11-01'),
  ];
  assert.deepEqual(
    newestPublished(articles, 'ru').map((a) => a.id),
    ['ru/new', 'ru/old'],
  );
  assert.deepEqual(newestPublished(articles, 'cs'), []);
});

test('the count of articles takes the form its number asks for', () => {
  assert.equal(articleCount('ru', 1), '1 статья');
  assert.equal(articleCount('ru', 3), '3 статьи');
  assert.equal(articleCount('ru', 5), '5 статей');
  assert.equal(articleCount('ru', 21), '21 статья');
  assert.equal(articleCount('uk', 3), '3 статті');
  assert.equal(articleCount('uk', 11), '11 статей');
  assert.equal(articleCount('cs', 1), '1 článek');
  assert.equal(articleCount('cs', 3), '3 články');
  assert.equal(articleCount('cs', 5), '5 článků');
  assert.equal(articleCount('en', 1), '1 article');
  assert.equal(articleCount('en', 3), '3 articles');
});

test('the landing counts the articles by rubric, the newest one’s rubric first', () => {
  const rubrics = ['visa', 'admission', 'visa', 'housing'] as const;
  assert.deepEqual(rubricTally(rubrics.map((rubric) => ({ rubric }))), [
    ['visa', 2],
    ['admission', 1],
    ['housing', 1],
  ]);
  assert.deepEqual(rubricTally([]), []);
});
