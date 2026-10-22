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
