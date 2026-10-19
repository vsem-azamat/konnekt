import { find } from './search.ts';
import type { Institution } from './types.ts';

/** A school the picker can offer, with the university it sits under. */
export interface Pickable {
  row: Institution;
  under: string | null;
  /** The school's city, or its university's: faculties often have none. */
  city: string | null;
}

/** How many schools the picker lists at once. */
const SHOWN = 6;

/**
 * The schools a query finds, universities and their faculties alike, leaving
 * out the ones in `taken`. A faculty is matched on its university's name as
 * well, so «fel чвут» finds ČVUT FEL, and on its city, spelled right, so
 * «брно» finds VUT and MUNI. Nothing until two letters are typed.
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
    flat.push({ row: university, under: null, city: university.city });
    for (const faculty of university.faculties) {
      flat.push({
        row: faculty,
        under: university.short_name ?? university.name,
        city: faculty.city ?? university.city,
      });
    }
  }
  return find(
    flat.filter(({ row }) => !taken.has(row.id)),
    ({ row, under, city }) => [
      row.name,
      row.short_name,
      row.code,
      under,
      { exact: city },
    ],
    needle,
  ).slice(0, SHOWN);
}
