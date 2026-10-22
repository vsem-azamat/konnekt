// The welcome text is stored as the bot sends it, Telegram HTML, which is what
// !welcome writes. The console edits it as plain text.

const TAG = /<[^>]*>/g;

/** The stored text as a person reads it: no tags, no entities. */
export function welcomePlain(html: string | null): string {
  return (html ?? '')
    .replace(TAG, '')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&');
}

/** Typed text as Telegram HTML: a «<3» or «Q&A» would get the greeting refused. */
export function welcomeHtml(plain: string): string {
  return plain.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/** Whether editing in the console would drop bold or links !welcome wrote. */
export function hasFormatting(html: string | null): boolean {
  return /<[^>]*>/.test(html ?? '');
}

/**
 * What to store for text typed over `opened`, the text the sheet showed; null
 * when nothing should be saved. Untouched formatted text is kept as it was,
 * while untouched text an older console stored raw is escaped, which repairs it.
 */
export function welcomeChange(opened: string | null, typed: string): string | null {
  const html = welcomeHtml(typed);
  if (html === (opened ?? '')) return null;
  if (hasFormatting(opened) && typed === welcomePlain(opened).trim()) return null;
  return html;
}
