/**
 * The landing's words in one language, and the app screen in its phone,
 * rendered at build time from the prototype's data (data.ts).
 */

import type { Lang } from '../paths.ts';
import { COPY, ICON, PHONE, STATS, type Stat, VARIANT } from './data.ts';

/**
 * Where «Открыть Konnekt» leads. The catalog redirects to the bot from the
 * token it runs with, so the bot's handle is not written into the site too.
 */
export const OPEN = '/api/v1/open';

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

/** The app's help screen as the phone shows it, as the prototype drew it (appmock.js). */
export function phone(lang: Lang): string {
  const x = PHONE[lang];
  const tab = (active: string, id: string, icon: string, key: string) =>
    `<span class="am-tab${active === id ? ' on' : ''}">${ICON[icon]}<b>${t(lang, key)}</b></span>`;
  const tabs = (active: string) =>
    `<nav class="am-tabs">${tab(active, 'help', 'search', 'app.help')}${tab(active, 'chats', 'chat', 'app.chats')}${tab(active, 'req', 'mark', 'app.requests')}${tab(active, 'me', 'user', 'app.profile')}<span class="am-fab">+</span></nav>`;
  const tile = (tone: number, icon: string, title?: string, sub?: string) =>
    `<div class="am-tile"><span class="am-ico t${tone}">${ICON[icon]}</span><b>${title}</b><small>${sub}</small></div>`;
  const head = `<header class="am-head"><b>Konnekt</b><span class="am-pill">${lang.toUpperCase()}</span></header>`;
  return (
    `${head}<h3 class="am-h">${x.what}</h3><div class="am-search">${ICON.search}<span>${x.search}</span></div>` +
    `<p class="am-label">${x.study}</p><div class="am-grid">` +
    tile(0, 'person', x.t1, x.s1) +
    tile(1, 'lang', x.t2, x.s2) +
    tile(2, 'check', x.t3, x.s3) +
    tile(3, 'doc', x.t4, x.s4) +
    `</div><p class="am-label">${x.life}</p><div class="am-grid">` +
    tile(4, 'shield', x.t5, x.s5) +
    tile(5, 'home', x.t6, x.s6) +
    tile(1, 'doc', x.t7, x.s7) +
    tile(3, 'card', x.t8, x.s8) +
    `</div>${tabs('help')}`
  );
}
