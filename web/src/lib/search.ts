/**
 * Matching what somebody typed against names, whatever script they typed in.
 *
 * Russian speakers write Czech names in Cyrillic and by ear: «чвут», «вше»,
 * «масарик», «страгов». Both sides are folded to one key, so «ČVUT», «cvut»
 * and «чвут» are the same word, and then every word of the query has to start
 * some word of the name, so «вут» finds VUT and not ČVUT. The lists are small
 * and already on the client, so this is plain string work and no index.
 *
 * The server's catalog does the same for free text in
 * catalog/src/students_cz/services/lookup.py, in SQL. The transliteration
 * table is copied from there, so that a name is spelled alike on both sides.
 */

// Czech-flavoured rather than the usual Russian romanisation: ч is «c» as in
// Č, because the target is a Czech name, not an English transcription.
const CYRILLIC: Record<string, string> = {
  а: 'a',
  б: 'b',
  в: 'v',
  г: 'g',
  д: 'd',
  е: 'e',
  ж: 'z',
  з: 'z',
  и: 'i',
  й: 'j',
  к: 'k',
  л: 'l',
  м: 'm',
  н: 'n',
  о: 'o',
  п: 'p',
  р: 'r',
  с: 's',
  т: 't',
  у: 'u',
  ф: 'f',
  х: 'ch',
  ц: 'c',
  ч: 'c',
  ш: 's',
  щ: 's',
  ъ: '',
  ы: 'y',
  ь: '',
  э: 'e',
  ю: 'ju',
  я: 'ja',
  ё: 'e',
  і: 'i',
  ї: 'ji',
  є: 'je',
  ґ: 'g',
};

/**
 * One key for a name in any script: lower case, no diacritics, Cyrillic
 * spelled in Latin, and the sounds the two languages write differently merged.
 *
 * Czech h is Russian г (Strahov, «Страгов») and Czech ch is Russian х, so all
 * three are «h»; Czech y and i are both Russian и («Masaryk», «Масарик»). That
 * makes some words collide that should not — «вше» is «все» too, and «uk»
 * starts «Украина» — which a search over a short list can afford.
 *
 * Accents come off Latin letters first: blanket mark-stripping turns «й» into
 * «и», and the catalog learnt that the hard way. What is left once «й» and «ё»
 * are put back together is a stress mark, and goes too.
 */
export function searchKey(text: string): string {
  let out = '';
  for (const char of text.toLowerCase().normalize('NFD')) {
    if (/\p{M}/u.test(char) && /[a-z]$/.test(out)) continue;
    out += char;
  }
  const composed = out.normalize('NFC').replace(/\p{M}/gu, '');
  return Array.from(composed, (char) => CYRILLIC[char] ?? char)
    .join('')
    .replace(/ch|g/g, 'h')
    .replace(/y/g, 'i');
}

/** The words of a text, folded. Punctuation and «|» separate words. */
function keyWords(text: string): string[] {
  return searchKey(text)
    .split(/[^\p{L}\p{N}]+/u)
    .filter(Boolean);
}

/** From this length a word may carry one typo. «fit» and «fel» are names. */
const TYPO_FROM = 5;

/**
 * Whether `word` starts with `typed`, allowing one typo — a letter replaced,
 * dropped, added or two swapped — once the typed word is long enough.
 *
 * Edit distance against the best prefix of `word`: the row's minimum at the
 * end, rather than its last cell, is what lets «masarek» reach «masarikova».
 */
function startsWord(word: string, typed: string, typos: boolean): boolean {
  if (word.startsWith(typed)) return true;
  if (!typos || typed.length < TYPO_FROM) return false;
  // Optimal string alignment distance, typed against the prefixes of word.
  let older: number[] = [];
  let prev = Array.from({ length: word.length + 1 }, (_, j) => j);
  for (let i = 1; i <= typed.length; i++) {
    const row = [i];
    for (let j = 1; j <= word.length; j++) {
      const cost = typed[i - 1] === word[j - 1] ? 0 : 1;
      let best = Math.min(
        (prev[j] ?? Infinity) + 1,
        (row[j - 1] ?? Infinity) + 1,
        (prev[j - 1] ?? Infinity) + cost,
      );
      if (
        i > 1 &&
        j > 1 &&
        typed[i - 1] === word[j - 2] &&
        typed[i - 2] === word[j - 1]
      ) {
        best = Math.min(best, (older[j - 2] ?? Infinity) + 1);
      }
      row.push(best);
    }
    older = prev;
    prev = row;
  }
  return Math.min(...prev) <= 1;
}

/**
 * Whether every word of the query starts a word of one of the fields, in any
 * order. An empty query matches everything; one with no words in it, «--» or
 * «ьь», matches nothing. Empty fields are skipped.
 */
export function matches(
  fields: (string | null | undefined)[],
  query: string,
  typos = true,
): boolean {
  const typed = keyWords(query);
  if (typed.length === 0) return query.trim() === '';
  const words = fields.flatMap((field) => (field ? keyWords(field) : []));
  return typed.every((part) => words.some((word) => startsWord(word, part, typos)));
}

/**
 * The items the query matches, typos allowed only when nothing is spelled the
 * way it was typed: «карлов» is one swap from «králov», and Univerzita Karlova
 * should not share the list with Hradec Králové because of it.
 */
export function find<T>(
  items: T[],
  fields: (item: T) => (string | null | undefined)[],
  query: string,
): T[] {
  const exact = items.filter((item) => matches(fields(item), query, false));
  return exact.length > 0 ? exact : items.filter((item) => matches(fields(item), query));
}
