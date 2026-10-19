/**
 * A subject's name and the note in brackets at its end, which a chip shows
 * lighter: «Чешский язык B2» is what was picked, «для вуза и нострификации»
 * only says what for.
 */
export function splitNote(label: string): { name: string; note: string | null } {
  const [, name, note] = /^(.*\S)\s*\(([^()]+)\)$/.exec(label.trim()) ?? [];
  return name && note ? { name, note } : { name: label, note: null };
}
