import type { WorkFormat } from './types';

/**
 * The cities the sheet offers as chips, first the default.
 *
 * As the catalog spells them, in Czech: the feed's city chip filters on the
 * stored string, so «Прага» from a Russian sheet and «Praha» from a Czech one
 * must arrive as the same word. `CityName` translates them back for display.
 */
export const REQUEST_CITIES = ['Praha', 'Brno'] as const;

/** The format and city a request is posted with. */
export function requestPlace(
  format: WorkFormat,
  city: string,
): { work_format: WorkFormat; city: string | null } {
  // The row is hidden for «Онлайн», so whatever it held before is not asked.
  if (format === 'online') return { work_format: format, city: null };
  return { work_format: format, city: city.trim() || null };
}

/**
 * A typed city, in Czech when it is one the app has a name for.
 *
 * For the same reason as the chips: «Острава» typed into a Russian sheet
 * would be a second chip in the feed beside «Ostrava», and a helper who picks
 * either would miss the other's requests. `names` maps the Czech spelling to
 * the reader's.
 */
export function spelledCity(typed: string, names: Record<string, string>): string {
  const city = typed.trim();
  const folded = city.toLocaleLowerCase();
  for (const [czech, local] of Object.entries(names)) {
    if (czech.toLocaleLowerCase() === folded || local.toLocaleLowerCase() === folded) {
      return czech;
    }
  }
  return city;
}
