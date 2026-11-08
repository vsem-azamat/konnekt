/**
 * The cards links show (og.ts) for the articles, from what the build reads
 * from disk: the fonts, the icon, the article's image and its logos. Each
 * file is read once per build.
 */

import { root, srcDir } from 'astro:config/server';
import type { CollectionEntry } from 'astro:content';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { type Lang, langOf, readFrontmatter } from '../paths.ts';
import { longDate, TEXTS } from '../texts.ts';
import { LOGOS, type LogoId } from './logos.ts';
import {
  type CardAssets,
  FONT_FAMILIES,
  framed,
  type LogoArt,
  logoArt,
  ogCard,
} from './og.ts';

let assets: Promise<CardAssets> | undefined;

function cardAssets(): Promise<CardAssets> {
  assets ??= (async () => {
    // Satori reads WOFF, not WOFF2, and no variable fonts: the static faces.
    const require = createRequire(srcDir);
    const fonts = await Promise.all(
      ([500, 600, 800] as const).flatMap((weight) =>
        Object.entries(FONT_FAMILIES).map(async ([subset, name]) => ({
          name,
          weight,
          style: 'normal' as const,
          data: await readFile(
            require.resolve(
              `@fontsource/inter-tight/files/inter-tight-${subset}-${weight}-normal.woff`,
            ),
          ),
        })),
      ),
    );
    // The icons are web/public/, which both builds serve.
    const mark = await readFile(new URL('../../public/favicon.svg', srcDir));
    return { fonts, mark };
  })();
  return assets;
}

const logos = new Map<LogoId, Promise<LogoArt>>();

function logo(id: LogoId): Promise<LogoArt> {
  let art = logos.get(id);
  if (!art) {
    art = readFile(new URL(`assets/logos/${LOGOS[id].file}`, srcDir)).then(logoArt);
    logos.set(id, art);
  }
  return art;
}

/**
 * The article's image file. The collection gives the image's metadata, not
 * where it lies, so the path is read from the article's own frontmatter,
 * relative to the article as written there.
 */
async function coverFile(article: CollectionEntry<'articles'>): Promise<Buffer> {
  const file = article.filePath;
  if (!file) throw new Error(`article ${article.id}: no file`);
  const project = fileURLToPath(root);
  const at = resolve(project, file);
  const cover = String(readFrontmatter(await readFile(at, 'utf8'), file).cover);
  // As Astro reads it: from the project's root when it starts with a slash,
  // else from the article; a path, not a URL, so # and % are only characters.
  return readFile(
    cover.startsWith('/') ? join(project, cover) : resolve(dirname(at), cover),
  );
}

/** An article's card: its rubric and title, and its image if it has one. */
export async function articleCard(article: CollectionEntry<'articles'>): Promise<Buffer> {
  const { data } = article;
  const lang = langOf(article.id);
  const image = data.cover ? await coverFile(article) : undefined;
  return ogCard(
    {
      rubric: TEXTS[lang].rubrics[data.rubric],
      title: data.title,
      date: longDate(lang, data.published),
      picture: image && (await framed(image, data.coverFocus)),
      logos: image ? await Promise.all(data.coverLogos.map(logo)) : [],
    },
    await cardAssets(),
  );
}

/** The card of the articles in `lang`: their name, nothing else. */
export async function listCard(lang: Lang): Promise<Buffer> {
  return ogCard({ title: TEXTS[lang].cardTitle }, await cardAssets());
}

export function jpeg(bytes: Buffer): Response {
  return new Response(new Uint8Array(bytes), {
    headers: { 'Content-Type': 'image/jpeg' },
  });
}
