// The welcome text is stored as the bot sends it, Telegram HTML, which is what
// !welcome writes. The console edits it as plain text.

/** The stored text as a person reads it: no tags, no entities. */
export function welcomePlain(html: string | null): string {
  return (html ?? '')
    .replace(/<[^>]*>/g, '')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;|&#39;/g, "'")
    .replace(/&amp;/g, '&');
}

/** Typed text as Telegram HTML: a «<3» or «Q&A» would get the greeting refused. */
export function welcomeHtml(plain: string): string {
  return plain.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
