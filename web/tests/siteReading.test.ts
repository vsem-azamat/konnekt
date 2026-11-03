import assert from 'node:assert/strict';
import { test } from 'node:test';

import { type El, reading } from '../site/src/articles/reading.ts';

const el = (
  tagName: string,
  properties: El['properties'] = {},
  children: El['children'] = [],
): El => ({
  type: 'element',
  tagName,
  properties,
  children,
});
const text = (value: string) => ({ type: 'text' as const, value });

/** What remark-rehype makes of one GFM footnote, as Astro renders it. */
function notes(url: string): El {
  return el('section', { dataFootnotes: true, className: ['footnotes'] }, [
    el('h2', { className: ['sr-only'], id: 'footnote-label' }, [text('Footnotes')]),
    el('ol', {}, [
      el('li', { id: 'user-content-fn-1' }, [
        el('p', {}, [
          text('Закон о высших школах, § 90 — '),
          el('a', { href: url }, [text('e-Sbírka')]),
          text(' '),
          el(
            'a',
            {
              href: '#user-content-fnref-1',
              dataFootnoteBackref: '',
              ariaLabel: 'Back to reference 1',
            },
            [text('↩')],
          ),
        ]),
      ]),
    ]),
  ]);
}

const law = {
  url: 'https://www.e-sbirka.cz/sb/1998/111',
  title: 'Zákon o vysokých školách',
  checked_at: new Date('2026-11-03'),
};

function find(node: El, test: (el: El) => boolean): El | undefined {
  if (test(node)) return node;
  for (const child of node.children) {
    if (child.type === 'element') {
      const found = find(child as El, test);
      if (found) return found;
    }
  }
  return undefined;
}

test('the footnotes become the sources: a visible heading in the article’s language', () => {
  const root = el('root', {}, [notes(law.url)]);
  const result = reading(root, { lang: 'ru', sources: [law] });
  assert.equal(result.notes, true);
  const heading = find(root, (e) => e.tagName === 'h2') as El;
  assert.deepEqual(heading.children, [text('Источники')]);
  assert.equal(heading.properties.className, undefined);
});

test('each note says when its source was checked, and its way back is in the article’s language', () => {
  const root = el('root', {}, [notes(law.url)]);
  reading(root, { lang: 'ru', sources: [law] });
  const checked = find(
    root,
    (e) => (e.properties.className as string[] | undefined)?.includes('checked') ?? false,
  );
  assert.deepEqual(checked?.children[0], text('проверено 3 ноября 2026 г. '));
  const back = checked?.children[1] as El;
  assert.ok('dataFootnoteBackref' in back.properties, 'the way back is on the same line');
  assert.equal(back.properties.ariaLabel, 'Назад к тексту');
  assert.deepEqual(back.children, [text('↩\uFE0E')]);
});

test('a note that links to no listed source stops the build', () => {
  const root = el('root', {}, [notes('https://example.org/other')]);
  assert.throws(
    () => reading(root, { lang: 'ru', sources: [law] }),
    /example\.org\/other/,
  );
});

test('a listed source no note cites stops the build', () => {
  const other = { ...law, url: 'https://www.mv.gov.cz/' };
  const root = el('root', {}, [notes(law.url)]);
  assert.throws(
    () => reading(root, { lang: 'ru', sources: [law, other] }),
    /mv\.gov\.cz/,
  );
});

test('without footnotes nothing is required of the sources', () => {
  const root = el('root', {}, [el('p', {}, [text('x')])]);
  assert.equal(reading(root, { lang: 'ru', sources: [law] }).notes, false);
});

test('a table scrolls in a box of its own', () => {
  const table = el('table');
  const root = el('root', {}, [table]);
  reading(root, { lang: 'ru', sources: [] });
  const box = root.children[0] as El;
  assert.equal(box.tagName, 'div');
  assert.deepEqual(box.properties.className, ['table']);
  assert.equal(box.children[0], table);
});

test('a list inside a note is part of the note, not a note of its own', () => {
  const root = el('root', {}, [notes(law.url)]);
  const note = find(root, (e) => e.tagName === 'li') as El;
  note.children.unshift(el('ul', {}, [el('li', {}, [text('a point')])]));
  assert.doesNotThrow(() => reading(root, { lang: 'ru', sources: [law] }));
});

test('a source is found whether or not its address is percent-encoded', () => {
  const raw = { ...law, url: 'https://cs.wikipedia.org/wiki/Nostrifikace_(školství)' };
  const root = el('root', {}, [
    notes('https://cs.wikipedia.org/wiki/Nostrifikace_(%C5%A1kolstv%C3%AD)'),
  ]);
  assert.doesNotThrow(() => reading(root, { lang: 'ru', sources: [raw] }));
});
