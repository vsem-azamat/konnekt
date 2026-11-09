/**
 * Where the catalog pages get their data, on the server, per request.
 *
 * Supervisor's public catalogue (`/api/public/catalog`, the list the app
 * reads), the catalog's universities (`/api/v1/universities`) and the tutors
 * who asked to be on the site (`/api/v1/public/helpers`), read over
 * the containers' own network from the addresses the deploy gives
 * (WEBAPI_URL, CATALOG_API_URL), with no cookie and no init data: public
 * fields only. Each answer is checked rather than trusted, as the app checks
 * the same list, and kept a minute (remembered.ts).
 */

import { INSTITUTION_CODE, type PublicChat, sanitize } from '../../../src/lib/chats.ts';
import type { Lang } from '../paths.ts';
import type { CatalogFaculty, CatalogUniversity } from './catalog.ts';
import { facultyAddress } from './directory.ts';
import { remembered } from './remembered.ts';
import {
  sanitizeTutor,
  sanitizeTutors,
  type TutorCard,
  type TutorPage,
} from './tutors.ts';

/** How long an answer is kept before the API is asked again. */
const KEEP_FOR = 60_000;
/** How long a page waits for an API before it falls back or gives up. */
const TIMEOUT = 5_000;

function origin(name: 'WEBAPI_URL' | 'CATALOG_API_URL'): string {
  const value = process.env[name];
  if (!value)
    throw new Error(`${name} is not set: the catalog pages read their data there`);
  return value.replace(/\/+$/, '');
}

async function read(url: string, missing?: 'null'): Promise<unknown> {
  const response = await fetch(url, {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.timeout(TIMEOUT),
  });
  // A 404 is an answer, that it is not there; anything else is a failure.
  if (response.status === 404 && missing) return null;
  if (!response.ok) throw new Error(`${url} answered ${response.status}`);
  return response.json();
}

export const publicChats: () => Promise<PublicChat[]> = remembered(
  async () => {
    const payload = await read(`${origin('WEBAPI_URL')}/api/public/catalog`);
    if (!Array.isArray(payload)) throw new Error('the public catalogue is not a list');
    return sanitize(payload);
  },
  { ttl: KEEP_FOR },
);

const text = (value: unknown): string | null =>
  typeof value === 'string' && value.trim() ? value : null;

/** A university's faculties as they arrived: only its own, each with a name and a code an address can carry. */
function sanitizeFaculties(university: string, payload: unknown): CatalogFaculty[] {
  if (!Array.isArray(payload)) return [];
  const faculties: CatalogFaculty[] = [];
  for (const item of payload) {
    if (!item || typeof item !== 'object') continue;
    const row = item as Record<string, unknown>;
    const code = text(row.code);
    const name = text(row.name);
    if (!code || !name || !facultyAddress(university, code)) continue;
    faculties.push({ code, name, short_name: text(row.short_name) });
  }
  return faculties;
}

/** The universities as they arrived, checked: a row the page cannot name or address is dropped. */
export function sanitizeUniversities(payload: unknown): CatalogUniversity[] {
  if (!Array.isArray(payload)) throw new Error('the universities are not a list');
  const universities: CatalogUniversity[] = [];
  for (const item of payload) {
    if (!item || typeof item !== 'object') continue;
    const row = item as Record<string, unknown>;
    const code = text(row.code);
    const name = text(row.name);
    if (!code || !INSTITUTION_CODE.test(code) || !name) continue;
    const site = text(row.site_url);
    universities.push({
      code,
      name,
      short_name: text(row.short_name),
      city: text(row.city),
      // A link the page prints: the university's own site, over https only.
      site_url: site?.startsWith('https://') ? site : null,
      faculties: sanitizeFaculties(code, row.faculties),
    });
  }
  return universities;
}

const byLang = new Map<Lang, () => Promise<CatalogUniversity[]>>();

export function universities(lang: Lang): Promise<CatalogUniversity[]> {
  let load = byLang.get(lang);
  if (!load) {
    load = remembered(
      async () =>
        sanitizeUniversities(
          await read(`${origin('CATALOG_API_URL')}/api/v1/universities?lang=${lang}`),
        ),
      { ttl: KEEP_FOR },
    );
    byLang.set(lang, load);
  }
  return load();
}

const tutorLists = new Map<Lang, () => Promise<TutorCard[]>>();

/** Everybody on the site, in the order the catalog gives: the most proven first. */
export function tutors(lang: Lang): Promise<TutorCard[]> {
  let load = tutorLists.get(lang);
  if (!load) {
    load = remembered(
      async () =>
        sanitizeTutors(
          await read(`${origin('CATALOG_API_URL')}/api/v1/public/helpers?lang=${lang}`),
        ),
      { ttl: KEEP_FOR },
    );
    tutorLists.set(lang, load);
  }
  return load();
}

const tutorPages = new Map<string, () => Promise<TutorPage | null>>();

/**
 * One tutor's page, for a tutor `tutors` lists: an id that is not on the list
 * is no page, and never a request to the catalog, so neither a made-up
 * address nor a crawler's guess is one.
 */
export async function tutor(lang: Lang, id: number): Promise<TutorPage | null> {
  if (!(await tutors(lang)).some((row) => row.user_id === id)) return null;
  const key = `${lang}:${id}`;
  let load = tutorPages.get(key);
  if (!load) {
    load = remembered(
      // Gone (404) is an answer and is kept as one: only a failure falls
      // back to the last page, so a tutor who left is not shown from before.
      async () => {
        const payload = await read(
          `${origin('CATALOG_API_URL')}/api/v1/public/helpers/${id}?lang=${lang}`,
          'null',
        );
        return payload === null ? null : sanitizeTutor(payload);
      },
      { ttl: KEEP_FOR },
    );
    tutorPages.set(key, load);
  }
  return load();
}
