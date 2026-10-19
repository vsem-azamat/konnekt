import { find } from './search.ts';
import type { Institution } from './types.ts';

/** A school the picker can offer, with the university it sits under. */
export interface Pickable {
  row: Institution;
  under: string | null;
}

/** How many schools the picker lists at once. */
const SHOWN = 6;

/**
 * The schools a query finds, universities and their faculties alike, leaving
 * out the ones in `taken`. A faculty is matched on its university's name as
 * well, so «fel чвут» finds ČVUT FEL. Nothing until two letters are typed.
 */
export function pickable(
  universities: Institution[],
  query: string,
  taken: ReadonlySet<number>,
): Pickable[] {
  const needle = query.trim();
  if (needle.length < 2) return [];
  // Faculties as well as universities: somebody prepares for ČVUT FEL, not for
  // ČVUT in general, and the row says which is which.
  const flat: Pickable[] = [];
  for (const university of universities) {
    flat.push({ row: university, under: null });
    for (const faculty of university.faculties) {
      flat.push({ row: faculty, under: university.short_name ?? university.name });
    }
  }
  return find(
    flat.filter(({ row }) => !taken.has(row.id)),
    ({ row, under }) => [row.name, row.short_name, row.code, under],
    needle,
  ).slice(0, SHOWN);
}
