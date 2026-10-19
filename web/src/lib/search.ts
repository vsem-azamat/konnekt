/**
 * Matching what somebody typed against names, whatever script they typed in.
 *
 * Russian speakers write Czech names in Cyrillic and by ear: «чвут», «вше»,
 * «масарик», «страгов». Both sides are folded to one key, so «ČVUT», «cvut»
 * and «чвут» are the same word, and then every word of the query has to start
 * some word of the name. The lists searched here are a few dozen chats and a
 * hundred-odd schools, already on the client, so this is plain string work and
 * no index.
 *
 * The server's catalog does the same for free text in
 * catalog/src/students_cz/services/lookup.py, in SQL; the transliteration table
 * is the same one, and has to be, so a name is spelled the same in both.
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
 * makes a few Czech words collide that should not, which a search over a few
 * dozen names can afford.
 *
 * Accents come off Latin letters only: blanket mark-stripping turns «й» into
 * «и», and the catalog learnt that the hard way.
 */
export function searchKey(text: string): string {
  let out = '';
  for (const char of text.toLowerCase().normalize('NFD')) {
    if (/\p{M}/u.test(char) && /[a-z]$/.test(out)) continue;
    out += char;
  }
  return Array.from(out.normalize('NFC'), (char) => CYRILLIC[char] ?? char)
    .join('')
    .replace(/ch|g/g, 'h')
    .replace(/y/g, 'i')
    .replace(/w/g, 'v');
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
 * Whether `typed` starts `word`, allowing one typo — a letter replaced,
 * dropped, added or two swapped — once the typed word is long enough.
 *
 * Edit distance against the best prefix of `word`: the row's minimum at the
 * end, rather than its last cell, is what lets «masarik» reach «masarikova».
 */
function startsWord(word: string, typed: string): boolean {
  if (word.startsWith(typed)) return true;
  if (typed.length < TYPO_FROM) return false;
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
 * order. An empty query matches everything; empty fields are skipped.
 */
export function matches(fields: (string | null | undefined)[], query: string): boolean {
  const typed = keyWords(query);
  if (typed.length === 0) return true;
  const words = fields.flatMap((field) => (field ? keyWords(field) : []));
  return typed.every((part) => words.some((word) => startsWord(word, part)));
}
