/**
 * The picture a link to an article shows (og:image), 1200×630, drawn when the
 * site is built. Dark, as uiux chose: in a Telegram chat it stands out where
 * a light card fades into the bubble.
 *
 * With the article's image: the text on the left, the image on the right in a
 * frame, any school's logo on it, and the Konnekt icon's two glows (blue and
 * red) along the bottom. Without one: the same text across the whole card. An
 * article always gets a card, so a link to it is never a bare line.
 *
 * Satori lays the card out (a subset of CSS, every box a flexbox) and resvg
 * draws its SVG; sharp crops the image and turns a logo into pixels. Bytes in,
 * JPEG out: what to read from disk is cards.ts's business.
 */
import { Resvg } from '@resvg/resvg-js';
import satori, { type Font } from 'satori';
import sharp from 'sharp';

import { OG_HEIGHT, OG_WIDTH } from './ogImage.ts';

const TEXT_WIDTH = 640;
/** The image's frame: what is left right of the text, inset by 20. */
const PANEL = { width: OG_WIDTH - TEXT_WIDTH - 20, height: OG_HEIGHT - 40 };

// The site's dark palette (landing/f.css) and the icon's two colours.
const INK = '#fffefc';
const SOFT = '#e9e6df';
const MUTED = '#a8a39a';
const GROUND = '#141312';
const GLOW = [
  'radial-gradient(ellipse 560px 250px at 6% 110%, rgba(63,107,184,0.62), rgba(63,107,184,0) 100%)',
  'radial-gradient(ellipse 300px 160px at 32% 116%, rgba(244,242,238,0.16), rgba(244,242,238,0) 100%)',
  'radial-gradient(ellipse 560px 250px at 58% 112%, rgba(178,58,63,0.55), rgba(178,58,63,0) 100%)',
].join(', ');

/** What every card is drawn with. */
export interface CardAssets {
  fonts: Font[];
  /** The Konnekt icon (web/public/favicon.svg). */
  mark: Buffer;
}

/** A logo ready for the card: pixels, and its width over its height. */
export interface LogoArt {
  png: Buffer;
  ratio: number;
}

export interface Card {
  /** The rubric's name, in a chip above the title. */
  rubric?: string;
  title: string;
  /** The day it came out, as the page writes it: shown when there is no image. */
  date?: string;
  /** The article's image, cropped to the frame (`framed`). */
  picture?: Buffer;
  logos?: readonly LogoArt[];
}

/**
 * The fonts' family names. Satori merges faces that share a name, so each
 * subset (Latin, Latin Extended for Č, Ř and Ž, Cyrillic) is a family of its
 * own, and a glyph is looked up in them in this order.
 */
export const FONT_FAMILIES = {
  latin: 'Inter Tight',
  'latin-ext': 'Inter Tight Ext',
  cyrillic: 'Inter Tight Cyrillic',
} as const;
const FAMILY = Object.values(FONT_FAMILIES).join(', ');

// Prepositions and conjunctions of three letters; any word of one or two is
// short enough on its own. Not every three-letter word: «что для вас и как»
// would set as one piece too long for a line.
const SHORT = new Set(
  'без для или над под при про что где как чем або під pro při nad pod bez and the for but'.split(
    ' ',
  ),
);

/**
 * A title as the card sets it: a short word (в, на, или, і, a, v, the) never
 * ends a line, and is kept with the word after it.
 */
export function glue(title: string): string {
  return title.replace(/(?<=^|\s)(\p{L}+) (?=\S)/gu, (whole, word: string) =>
    word.length <= 2 || SHORT.has(word.toLowerCase()) ? `${word}\u00a0` : whole,
  );
}

/**
 * The part of an article's image the card shows: the frame's shape, filled,
 * cut around `focus` (0 the left edge, 1 the right) and centred vertically.
 */
export async function framed(image: Buffer, focus = 0.5): Promise<Buffer> {
  // Upright first, as a camera's EXIF says: the page's copy is turned so too.
  const upright = await sharp(image).rotate().toBuffer();
  const { width = 0, height = 0 } = await sharp(upright).metadata();
  if (!width || !height) throw new Error('an image with no size');
  const scale = Math.max(PANEL.width / width, PANEL.height / height);
  const w = Math.max(PANEL.width, Math.round(width * scale));
  const h = Math.max(PANEL.height, Math.round(height * scale));
  const left = Math.round(
    Math.min(w - PANEL.width, Math.max(0, focus * w - PANEL.width / 2)),
  );
  const top = Math.round((h - PANEL.height) / 2);
  return sharp(upright)
    .resize({ width: w, height: h })
    .extract({ left, top, width: PANEL.width, height: PANEL.height })
    .jpeg({ quality: 90, mozjpeg: true })
    .toBuffer();
}

/** A logo file (SVG or PNG) as pixels tall enough for any size the card draws it at. */
export async function logoArt(file: Buffer): Promise<LogoArt> {
  const png = await sharp(file, { density: 300 })
    .resize({ height: 240 })
    .png()
    .toBuffer();
  const { width = 0, height = 0 } = await sharp(png).metadata();
  return { png, ratio: width / height };
}

// A satori element: an object shaped as React's, every box a flexbox.
interface Element {
  type: string;
  props: Record<string, unknown>;
}
type Child = Element | string | null | false | undefined;

function box(style: Record<string, unknown>, ...children: Child[]): Element {
  return {
    type: 'div',
    props: {
      style: { display: 'flex', boxSizing: 'border-box', ...style },
      children: children.filter((child) => child !== null && child !== false && child),
    },
  };
}

function picture(src: string, style: Record<string, unknown>): Element {
  return { type: 'img', props: { src, style } };
}

const dataUri = (bytes: Buffer, type: string) =>
  `data:${type};base64,${bytes.toString('base64')}`;

/**
 * The logos on white, as their manuals ask: one in a badge in the corner, more
 * in a strip along the bottom, three to a row.
 */
function logoOverlay(logos: readonly LogoArt[]): Element | null {
  const logo = (art: LogoArt, height: number) =>
    picture(dataUri(art.png, 'image/png'), {
      height,
      width: Math.round(height * art.ratio),
    });
  const [only] = logos;
  if (!only) return null;
  if (logos.length === 1) {
    return box(
      {
        position: 'absolute',
        left: 18,
        bottom: 18,
        background: '#ffffff',
        borderRadius: 14,
        padding: '14px 18px',
        boxShadow: '0 2px 10px rgba(20,19,18,0.18)',
      },
      logo(only, 62),
    );
  }
  const rows = Array.from({ length: Math.ceil(logos.length / 3) }, (_, row) =>
    logos.slice(row * 3, row * 3 + 3),
  );
  return box(
    {
      position: 'absolute',
      left: 0,
      right: 0,
      bottom: 0,
      background: '#ffffff',
      flexDirection: 'column',
      padding: '16px 22px',
      gap: 14,
    },
    ...rows.map((row) =>
      box(
        { justifyContent: 'space-around', alignItems: 'center' },
        ...row.map((art) => logo(art, 40)),
      ),
    ),
  );
}

function brand(mark: Buffer): Element {
  return box(
    { alignItems: 'center', gap: 12 },
    picture(dataUri(mark, 'image/svg+xml'), {
      width: 36,
      height: 36,
      borderRadius: 9,
      border: '1.5px solid rgba(255,254,252,0.22)',
    }),
    box(
      { fontSize: 30, fontWeight: 800, letterSpacing: '-0.02em', color: INK },
      'Konnekt',
    ),
  );
}

function heading(card: Card, size: number): Element {
  return box(
    { flexDirection: 'column', gap: 22 },
    card.rubric
      ? box(
          {},
          box(
            {
              fontSize: 22,
              fontWeight: 600,
              color: SOFT,
              padding: '6px 14px',
              borderRadius: 10,
              background: 'rgba(255,254,252,0.08)',
              border: '1.5px solid rgba(255,254,252,0.16)',
            },
            card.rubric,
          ),
        )
      : null,
    box(
      {
        fontSize: size,
        fontWeight: 800,
        lineHeight: 1.06,
        letterSpacing: '-0.03em',
        color: INK,
        textWrap: 'balance',
      },
      glue(card.title),
    ),
  );
}

const footnote = (text: string) =>
  box({ fontSize: 22, fontWeight: 500, color: MUTED }, text);

/** The card as a satori tree: with the image in its frame, or the text alone. */
function layout(card: Card, assets: CardAssets): Element {
  const root = (...children: Child[]) =>
    box(
      {
        width: OG_WIDTH,
        height: OG_HEIGHT,
        fontFamily: FAMILY,
        backgroundColor: GROUND,
        backgroundImage: GLOW,
      },
      ...children,
    );
  const length = card.title.length;
  if (!card.picture) {
    return root(
      box(
        {
          flexDirection: 'column',
          justifyContent: 'space-between',
          width: OG_WIDTH,
          height: OG_HEIGHT,
          padding: '54px 72px 50px 72px',
        },
        box(
          { justifyContent: 'space-between', alignItems: 'center' },
          brand(assets.mark),
          footnote('konnekt.cz'),
        ),
        heading(card, length > 60 ? 64 : length > 40 ? 70 : 76),
        card.date ? footnote(card.date) : box({}),
      ),
    );
  }
  return root(
    box(
      {
        flexDirection: 'column',
        justifyContent: 'space-between',
        width: TEXT_WIDTH,
        height: OG_HEIGHT,
        padding: '54px 44px 50px 64px',
      },
      brand(assets.mark),
      heading(card, length > 44 ? 52 : length > 34 ? 56 : 60),
      footnote('konnekt.cz'),
    ),
    box(
      { width: OG_WIDTH - TEXT_WIDTH, height: OG_HEIGHT, padding: '20px 20px 20px 0' },
      box(
        {
          position: 'relative',
          width: PANEL.width,
          height: PANEL.height,
          borderRadius: 22,
          overflow: 'hidden',
          border: '1.5px solid rgba(255,254,252,0.14)',
          background: '#efede8',
        },
        picture(dataUri(card.picture, 'image/jpeg'), {
          width: PANEL.width,
          height: PANEL.height,
        }),
        logoOverlay(card.logos ?? []),
      ),
    ),
  );
}

/**
 * The card, as a JPEG: a photo's card as a PNG is half a megabyte, more than
 * some messengers fetch for a preview.
 */
export async function ogCard(card: Card, assets: CardAssets): Promise<Buffer> {
  const svg = await satori(layout(card, assets) as Parameters<typeof satori>[0], {
    width: OG_WIDTH,
    height: OG_HEIGHT,
    fonts: assets.fonts,
  });
  const png = new Resvg(svg, { fitTo: { mode: 'width', value: OG_WIDTH } })
    .render()
    .asPng();
  return sharp(png).jpeg({ quality: 86, mozjpeg: true }).toBuffer();
}
