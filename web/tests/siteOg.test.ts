import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

import sharp from 'sharp';

import { LOGO_IDS, LOGOS } from '../site/src/articles/logos.ts';
import {
  type CardAssets,
  FONT_FAMILIES,
  framed,
  glue,
  logoArt,
  ogCard,
} from '../site/src/articles/og.ts';
import { cardPath, listCardPath, ogImage } from '../site/src/articles/ogImage.ts';

const require = createRequire(import.meta.url);
const assets: CardAssets = {
  fonts: [800, 600, 500].flatMap((weight) =>
    Object.entries(FONT_FAMILIES).map(([subset, name]) => ({
      name,
      weight: weight as 500 | 600 | 800,
      style: 'normal' as const,
      data: readFileSync(
        require.resolve(
          `@fontsource/inter-tight/files/inter-tight-${subset}-${weight}-normal.woff`,
        ),
      ),
    })),
  ),
  mark: readFileSync(new URL('../public/favicon.svg', import.meta.url)),
};

const logoFile = (id: (typeof LOGO_IDS)[number]) =>
  readFileSync(new URL(`../site/src/assets/logos/${LOGOS[id].file}`, import.meta.url));

/** A stand-in for an article's image: left half red, right half blue. */
const halves = () =>
  sharp({
    create: { width: 1536, height: 1024, channels: 3, background: '#d00000' },
  })
    .composite([
      {
        input: {
          create: { width: 768, height: 1024, channels: 3, background: '#0000d0' },
        },
        left: 768,
        top: 0,
      },
    ])
    .png()
    .toBuffer();

test('a short word stays with the next one, in any of the languages', () => {
  assert.equal(
    glue('Поступление в Чехию бесплатно: план на 2027/28'),
    'Поступление в\u00a0Чехию бесплатно: план на\u00a02027/28',
  );
  assert.equal(glue('Як вступити і що треба'), 'Як\u00a0вступити і\u00a0що\u00a0треба');
  assert.equal(
    glue('Studium v Praze a v Brně'),
    'Studium v\u00a0Praze a\u00a0v\u00a0Brně',
  );
  // An abbreviation is a word of its own, not a preposition.
  assert.equal(glue('FIT ČVUT: přijímačky'), 'FIT ČVUT: přijímačky');
  // Nothing after the last word to keep it with.
  assert.equal(glue('Что делать в'), 'Что\u00a0делать в');
});

test('the frame shows the part of the image its focus names', async () => {
  const pixel = async (focus: number) => {
    const frame = await framed(await halves(), focus);
    const { data, info } = await sharp(frame).raw().toBuffer({ resolveWithObject: true });
    assert.deepEqual([info.width, info.height], [540, 590]);
    const middle =
      (Math.floor(info.height / 2) * info.width + Math.floor(info.width / 2)) * 3;
    return (data[middle] as number) > (data[middle + 2] as number) ? 'red' : 'blue';
  };
  assert.equal(await pixel(0), 'red');
  assert.equal(await pixel(1), 'blue');
});

test('every logo in the registry has its file, and a usable shape', async () => {
  for (const id of LOGO_IDS) {
    const art = await logoArt(logoFile(id));
    assert.ok(art.ratio > 0.5 && art.ratio < 8, `${id}: ratio ${art.ratio}`);
  }
});

test('a card is 1200×630, with an image and logos or with the text alone', async () => {
  const cards = [
    await ogCard(
      {
        rubric: 'Поступление',
        title: 'Поступление в Чехию бесплатно: план на 2027/28',
        picture: await framed(await halves()),
        logos: await Promise.all(
          ['uk', 'cvut', 'vse', 'muni', 'vut'].map((id) =>
            logoArt(logoFile(id as (typeof LOGO_IDS)[number])),
          ),
        ),
      },
      assets,
    ),
    await ogCard(
      {
        rubric: 'Přijímací řízení',
        title: 'Jak se dostat na ČVUT',
        date: '3. listopadu 2026',
      },
      assets,
    ),
    await ogCard({ title: 'Статьи Konnekt' }, assets),
  ];
  for (const card of cards) {
    const { width, height, format } = await sharp(card).metadata();
    assert.deepEqual([format, width, height], ['png', 1200, 630]);
  }
});

test('a card lives next to its page, and its tags are absolute', () => {
  assert.equal(cardPath('/uk/articles/vstup/'), '/uk/articles/vstup/og.png');
  assert.equal(listCardPath('ru'), '/articles/og.png');
  assert.equal(listCardPath('cs'), '/cs/articles/og.png');
  assert.deepEqual(ogImage('/articles/og.png', 'https://konnekt.cz/', 'Статьи Konnekt'), {
    url: 'https://konnekt.cz/articles/og.png',
    alt: 'Статьи Konnekt',
    width: 1200,
    height: 630,
  });
});
