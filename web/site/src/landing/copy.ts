/**
 * The landing's words in one language, rendered at build time from the
 * prototype's data (data.ts).
 */

import type { Lang } from '../paths.ts';
import { COPY, STATS, type Stat, VARIANT } from './data.ts';

/**
 * Where «Открыть Konnekt» leads: into the Mini App. The catalog redirects to
 * the bot from the token it runs with (`?app` adds startapp), so the bot's
 * handle is not written into the site too. `source` says which button it was
 * (`site_header`): the catalog passes it on as the start parameter, and the
 * app's audience counts it as where somebody came from. No cookies.
 */
export function openLink(source: string): string {
  return `/api/v1/open?app=1&from=${source}`;
}

/** An article's buttons into the app, by its slug, within Telegram's 64 characters. */
export function articleSource(slug: string): string {
  return `site_article_${slug}`.slice(0, 64);
}

/** A number in the language's own grouping, with no line break inside it. */
export function num(lang: Lang, n: number): string {
  return n.toLocaleString(lang === 'en' ? 'en-GB' : lang).replace(/\s/g, ' ');
}

function word(
  table: Record<Lang, Record<string, string>>,
  lang: Lang,
  key: string,
): string {
  const text = table[lang][key] ?? table.ru[key];
  if (text === undefined) throw new Error(`no copy for ${key}`);
  return text;
}

/** The shared copy, with `{students}`, `{chats}`… filled in. */
export function t(lang: Lang, key: string): string {
  return word(COPY, lang, key).replace(/\{(\w+)\}/g, (match, name: string) =>
    name in STATS && name !== 'date' ? num(lang, STATS[name as Stat]) : match,
  );
}

/** Copy only landing F has. */
export function v(lang: Lang, key: string): string {
  return word(VARIANT, lang, key);
}
