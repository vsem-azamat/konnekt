/**
 * What a request is called, when it has a name of its own.
 *
 * Null for a request written as free text with no subject or institution: its
 * words are then the only thing there is, and a screen that used them as the
 * heading must not also print them as the body.
 */
export function requestName(request: {
  subject?: string | null;
  institution?: string | null;
}): string | null {
  return [request.subject, request.institution].filter(Boolean).join(', ') || null;
}

/** The request as the answer sheet quotes it: its name, then the words they typed. */
export function requestQuote(request: {
  subject?: string | null;
  institution?: string | null;
  text: string;
}): string {
  const name = requestName(request);
  return name ? `${name}. ${request.text}` : request.text;
}
