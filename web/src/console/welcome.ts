// The welcome text is stored as the bot sends it, Telegram HTML, which is what
// !welcome writes. The console edits it as plain text.

// Only the tags Telegram knows, so a raw «<3 и ->» or «<имя>» is not a tag.
const TAG =
  /<\/?(?:b|strong|i|em|u|ins|s|strike|del|a|code|pre|span|tg-spoiler|tg-emoji|blockquote)(?:\s[^>]*)?>/g;
const ENTITY = /&(?:lt|gt|amp|quot|#\d+|#x[\da-f]+);/gi;

// An entity past the last character stays as written instead of throwing.
function codePoint(entity: string, n: number): string {
  return n <= 0x10ffff ? String.fromCodePoint(n) : entity;
}

/** The stored text as a person reads it: no tags, no entities. */
export function welcomePlain(html: string | null): string {
  return (html ?? '')
    .replace(TAG, '')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#(\d+);/g, (entity, n: string) => codePoint(entity, Number(n)))
    .replace(/&#x([\da-f]+);/gi, (entity, n: string) =>
      codePoint(entity, Number.parseInt(n, 16)),
    )
    .replace(/&amp;/g, '&');
}

/** Typed text as Telegram HTML: a «<3» or «Q&A» would get the greeting refused. */
export function welcomeHtml(plain: string): string {
  return plain.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/** Whether editing in the console would drop bold or links !welcome wrote. */
export function hasFormatting(html: string | null): boolean {
  return new RegExp(TAG.source).test(html ?? '');
}

/** Whether Telegram would refuse the text: a bare «&» or «<» outside a tag. */
function isBroken(html: string): boolean {
  return /[&<]/.test(html.replace(TAG, '').replace(ENTITY, ''));
}

/**
 * What to store for text typed over `opened`, the text the sheet showed; null
 * when nothing should be saved. Untouched formatted text is kept as it was,
 * while untouched text an older console stored raw is escaped, which repairs it.
 */
export function welcomeChange(opened: string | null, typed: string): string | null {
  const stored = (opened ?? '').trim();
  const untouched = typed === welcomePlain(stored).trim();
  if (untouched && !isBroken(stored)) return null;
  return welcomeHtml(typed);
}
