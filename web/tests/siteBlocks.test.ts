import assert from 'node:assert/strict';
import { test } from 'node:test';

import { creditLine, creditSite } from '../site/src/articles/credit.ts';
import {
  checkUnmarked,
  type MdNode,
  type Photo,
  placeBlocks,
  placeBlocksPlugin,
} from '../site/src/catalog/blocks.ts';

const text = (value: string): MdNode => ({ type: 'text', value });
const heading = (title: string, mark?: string, depth = 2): MdNode => ({
  type: 'heading',
  depth,
  children: [text(title)],
  ...(mark ? { data: { hProperties: { className: [mark] } } } : {}),
});
const para = (...children: MdNode[]): MdNode => ({ type: 'paragraph', children });
const list = (...items: string[]): MdNode => ({
  type: 'list',
  children: items.map((item) => ({ type: 'listItem', children: [para(text(item))] })),
});
const image = (url: string, title: string | null = null): MdNode => ({
  type: 'image',
  url,
  title,
});
const root = (...children: MdNode[]): MdNode => ({ type: 'root', children });

const PHOTO: Photo = {
  src: '../x.jpg',
  author: 'Utar',
  licence: 'CC BY-SA 3.0',
  licenceUrl: 'https://creativecommons.org/licenses/by-sa/3.0/',
  source: 'https://commons.wikimedia.org/wiki/File:X.jpg',
  cropped: false,
};

const blocks = (tree: MdNode, photos: Photo[] = []) =>
  placeBlocks(tree, { lang: 'ru', photos }).children ?? [];
const parts = (tree: MdNode, photos: Photo[] = []) =>
  Object.fromEntries(
    blocks(tree, photos)
      .filter((node) => node.data?.hName === 'div')
      .map((node) => [
        ((node.data?.hProperties?.className ?? []) as string[])[1]?.replace('part-', ''),
        node.children ?? [],
      ]),
  ) as Record<'top' | 'rest' | 'end', MdNode[]>;

test('a text splits into top, rest and end at {.chats} and {.end}', () => {
  const { top, rest, end } = parts(
    root(
      para(text('Intro.')),
      heading('Учёба'),
      heading('Поступление', 'chats'),
      para(text('Admissions.')),
      heading('Факты', 'end'),
      para(text('Table.')),
    ),
  );
  assert.deepEqual(
    top?.map((node) => node.type),
    ['paragraph', 'heading'],
  );
  assert.equal(rest?.[0]?.children?.[0]?.value, 'Поступление');
  assert.equal(rest?.length, 2);
  assert.equal(end?.[0]?.children?.[0]?.value, 'Факты');
});

test('without marks the whole text is the top, and the other two parts are empty', () => {
  const { top, rest, end } = parts(root(para(text('Intro.')), heading('Учёба')));
  assert.equal(top?.length, 2);
  assert.deepEqual(rest, []);
  assert.deepEqual(end, []);
});

test('footnote definitions stay at the root, outside the parts', () => {
  const definition: MdNode = { type: 'footnoteDefinition', children: [] };
  const out = blocks(root(para(text('A.')), definition));
  assert.equal(out.at(-1), definition);
  assert.equal(out.length, 4);
});

test('{.brief} marks the list under it', () => {
  const { top } = parts(root(heading('Коротко', 'brief'), list('One', 'Two')));
  assert.deepEqual(top?.[1]?.data?.hProperties?.className, ['brief']);
});

test('{.brief} without a list under it stops the build', () => {
  assert.throws(
    () => blocks(root(heading('Коротко', 'brief'), para(text('No list.')))),
    /has no list under it/,
  );
});

test('{.questions}: a paragraph opening in bold is a question, up to the next section', () => {
  const question = para({ type: 'strong', children: [text('«Q?»')] }, text(' A.'));
  const { top } = parts(
    root(
      heading('Что спрашивают', 'questions'),
      para(text('Intro, not a question.')),
      question,
      heading('Дальше'),
      para({ type: 'strong', children: [text('Bold')] }, text(' but not a question.')),
    ),
  );
  assert.equal(top?.[1]?.data, undefined);
  assert.deepEqual(top?.[2]?.data?.hProperties?.className, ['question']);
  assert.equal(top?.[4]?.data, undefined);
});

test('an unknown mark, a mark twice, or {.chats} after {.end} stops the build', () => {
  assert.throws(() => blocks(root(heading('X', 'facts'))), /a mark is one of/);
  assert.throws(
    () => blocks(root(heading('A', 'end'), heading('B', 'end'))),
    /marks two headings/,
  );
  assert.throws(
    () => blocks(root(heading('A', 'end'), heading('B', 'chats'))),
    /after \{\.end\}/,
  );
  assert.throws(() => blocks(root(heading('A', 'chats', 3))), /second-level heading/);
  assert.throws(
    () =>
      blocks(
        root({
          type: 'heading',
          depth: 2,
          children: [text('A')],
          data: { hProperties: { id: 'a' } },
        }),
      ),
    /a mark is one of/,
  );
});

test('a photo becomes a figure with its caption and credit', () => {
  const { top } = parts(root(para(image('../x.jpg', 'Вход в здание.'))), [PHOTO]);
  const figure = top?.[0] as MdNode;
  assert.equal(figure.data?.hName, 'figure');
  const [img, caption] = figure.children ?? [];
  assert.equal(img?.type, 'image');
  assert.equal(img?.title, null);
  assert.equal(caption?.data?.hName, 'figcaption');
  const words = (caption?.children ?? [])
    .map((node) => node.value ?? node.children?.[0]?.value)
    .join('');
  assert.equal(words, 'Вход в здание. Фото: Utar, CC BY-SA 3.0, Wikimedia Commons');
  const links = (caption?.children ?? []).filter((node) => node.type === 'link');
  assert.deepEqual(
    links.map((link) => link.url),
    [PHOTO.licenceUrl, PHOTO.source],
  );
});

test('an image inside a paragraph of text is not a photo', () => {
  const { top } = parts(root(para(text('See '), image('../x.jpg'))));
  assert.equal(top?.[0]?.type, 'paragraph');
});

test('a photo without its credit, or a credit without its photo, stops the build', () => {
  assert.throws(() => blocks(root(para(image('../y.jpg')))), /has no credit/);
  assert.throws(
    () => blocks(root(para(text('No photo.'))), [PHOTO]),
    /no photo in the text/,
  );
});

test('an article with a marked heading stops the build', () => {
  assert.throws(
    () => checkUnmarked(root(heading('A', 'brief'))),
    /only a directory text/,
  );
  checkUnmarked(root(heading('A')));
});

test('the plugin works on directory texts and articles, and leaves other Markdown alone', () => {
  const doc = (path: string) => ({ fileURL: new URL(`file://${path}`), data: {} });
  assert.ok(placeBlocksPlugin(doc('/site/src/content/universities/ru/cvut/fit.md')));
  assert.ok(placeBlocksPlugin(doc('/site/src/content/articles/ru/x.md')));
  assert.equal(placeBlocksPlugin(doc('/site/README.md')), null);
});

test('a credit: the site by name, the licence and the source linked, a cut said', () => {
  assert.equal(
    creditSite('https://commons.wikimedia.org/wiki/File:X.jpg'),
    'Wikimedia Commons',
  );
  assert.equal(creditSite('https://www.example.cz/x'), 'example.cz');
  const line = creditLine('en', { ...PHOTO, cropped: true });
  assert.equal(
    line.map((part) => part.text).join(''),
    'Photo: Utar, CC BY-SA 3.0, cropped, Wikimedia Commons',
  );
  const bare = creditLine('ru', { ...PHOTO, licenceUrl: undefined });
  assert.equal(bare[1]?.href, undefined);
});
