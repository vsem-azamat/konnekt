/**
 * The public catalogue as the site's pages read it: the chats supervisor
 * publishes (`/api/public/catalog`, the list the app reads), under the
 * universities the catalog knows (`/api/v1/universities`).
 *
 * Pure functions over the two lists, shared by the pages and the tests. The
 * rules that are the app's — what a chat is, which cities there are, how a
 * name folds — are imported from it rather than repeated.
 */

import {
  cityChoices,
  fold,
  type PublicChat,
  TOPICS,
  type Topic,
} from '../../../src/lib/chats.ts';

/** A university as `/api/v1/universities` names it in the page's language. */
export interface CatalogFaculty {
  /** `cvut_fit`: its university's code, then its own. */
  code: string;
  name: string;
  short_name: string | null;
}

export interface CatalogUniversity {
  code: string;
  name: string;
  short_name: string | null;
  city: string | null;
  site_url: string | null;
  /** Its active faculties, in the catalog's order. */
  faculties: CatalogFaculty[];
}

/** A university's page goes to search only with this many chats; below it, noindex. */
export const MIN_INDEXED_CHATS = 2;

export interface UniversityChats {
  university: CatalogUniversity;
  /** Every chat that names the university, in supervisor's order. */
  chats: PublicChat[];
}

/**
 * The universities that have chats, in the catalogue's order: supervisor
 * sends ours first, then the larger, and a university goes by its first chat.
 */
export function universitiesWithChats(
  universities: readonly CatalogUniversity[],
  chats: readonly PublicChat[],
): UniversityChats[] {
  const known = new Map(universities.map((u) => [u.code, u]));
  const found = new Map<string, UniversityChats>();
  for (const chat of chats) {
    const university = chat.institution ? known.get(chat.institution) : undefined;
    if (!university) continue;
    const entry = found.get(university.code);
    if (entry) entry.chats.push(chat);
    else found.set(university.code, { university, chats: [chat] });
  }
  return [...found.values()];
}

export function indexable({ chats }: UniversityChats): boolean {
  return chats.length >= MIN_INDEXED_CHATS;
}

const topicOf = (chat: PublicChat): Topic => chat.topic ?? 'general';

/**
 * The chat a university's line opens with on /chats/, marked «главный чат»:
 * its own room, the one its group is named after, or else its largest common
 * chat. Never its largest chat as such, which is a dorm's at ČVUT (Azamat,
 * agora 10228), and never a channel, which is read rather than joined. A
 * university with one chat has none: the mark means something only beside
 * others.
 */
export function mainChat(chats: readonly PublicChat[]): PublicChat | null {
  if (chats.length < 2) return null;
  const rooms = chats.filter((c) => c.kind === 'group');
  const own = rooms.find((c) => c.group !== null && c.title === c.group);
  if (own) return own;
  const common = rooms.filter((c) => topicOf(c) === 'university');
  return common.reduce<PublicChat | null>(
    (best, c) =>
      best === null || (c.member_count ?? -1) > (best.member_count ?? -1) ? c : best,
    null,
  );
}

/** A list with its main chat moved to the front, the rest in their order. */
function mainFirst(chats: readonly PublicChat[]): PublicChat[] {
  const main = mainChat(chats);
  return main ? [main, ...chats.filter((c) => c !== main)] : [...chats];
}

export interface Section {
  topic: Topic;
  chats: PublicChat[];
}

/** A university's page: its chats under the app's headings, its main chat first. */
export function sections(chats: readonly PublicChat[]): Section[] {
  const ordered = mainFirst(chats);
  return TOPICS.map((topic) => ({
    topic,
    chats: ordered.filter((c) => topicOf(c) === topic),
  })).filter((s) => s.chats.length > 0);
}

/** One university's line on /chats/: its page when the catalog knows it. */
export interface CatalogueUniversity {
  /** The catalog's code, which names its page; null for a group the catalog has no university for. */
  code: string | null;
  name: string;
  city: string | null;
  main: PublicChat | null;
  chats: PublicChat[];
}

export interface Catalogue {
  universities: CatalogueUniversity[];
  /** A university's chat with neither a code nor a group: a line of its own. */
  loose: PublicChat[];
  /** Everything not a university's, under the app's headings. */
  topics: Section[];
}

/**
 * /chats/ as Azamat chose it (variant A, agora 10228): one line a
 * university, its main chat and the way to the rest on its page; a group the
 * catalog has no university for keeps all its chats here, having no page.
 * Everything else stands under its heading.
 *
 * `city`, when given, keeps what is for that city and what is for all of
 * Czechia; a university goes by its main chat's city, as the app's sections
 * go by their own chat's, so its faculties are never split.
 */
export function catalogue(
  chats: readonly PublicChat[],
  universities: readonly CatalogUniversity[],
  city: string | null = null,
): Catalogue {
  const known = new Map(universities.map((u) => [u.code, u]));
  const lines = new Map<string, CatalogueUniversity>();
  const loose: PublicChat[] = [];
  const rest: PublicChat[] = [];
  for (const chat of chats) {
    const university = chat.institution ? known.get(chat.institution) : undefined;
    const key = university
      ? `code:${university.code}`
      : chat.group
        ? `group:${chat.group}`
        : null;
    const line = key ? lines.get(key) : undefined;
    if (line) {
      line.chats.push(chat);
    } else if (key && (university || topicOf(chat) === 'university')) {
      lines.set(key, {
        code: university?.code ?? null,
        name: university
          ? (university.short_name ?? university.name)
          : (chat.group as string),
        city: null,
        main: null,
        chats: [chat],
      });
    } else if (topicOf(chat) === 'university') {
      loose.push(chat);
    } else {
      rest.push(chat);
    }
  }
  const here = (where: string | null) =>
    city === null || where === null || where === city;
  const shown = [...lines.values()]
    .map((line) => {
      const main = mainChat(line.chats);
      return {
        ...line,
        main,
        chats: mainFirst(line.chats),
        city: (main ?? line.chats[0])?.city ?? null,
      };
    })
    .filter((line) => here(line.city));
  return {
    universities: shown,
    loose: loose.filter((c) => here(c.city)),
    topics: TOPICS.filter((t) => t !== 'university')
      .map((topic) => ({
        topic,
        chats: rest.filter((c) => topicOf(c) === topic && here(c.city)),
      }))
      .filter((s) => s.chats.length > 0),
  };
}

/** The cities a reader can pick on /chats/: the app's, the one with most first. */
export const cities = (chats: PublicChat[]): string[] => cityChoices(chats);

/** A city in an address: «České Budějovice» is `ceske-budejovice`. */
export function citySlug(city: string): string {
  return fold(city).trim().replace(/\s+/g, '-');
}

/**
 * The city `?city=` names, among those there are. Anything else, a city
 * spelled with capitals included, is no city: the page shows them all.
 */
export function cityFromSlug(
  slug: string | null,
  choices: readonly string[],
): string | null {
  if (slug === null) return null;
  return choices.find((city) => citySlug(city) === slug) ?? null;
}

/** A Telegram username in a link: what a public chat is known by. */
const USERNAME =
  /^https:\/\/(?:t\.me|telegram\.me|telegram\.dog)\/([A-Za-z0-9_]{4,32})\/?$/;

/**
 * Each chat's anchor on its university's page, which stands in for a page of
 * its own (/universities/cvut/#cvut_fit): its public name, or for an invite
 * link its folded title, the invite itself being nobody's address.
 */
export function anchors(chats: readonly PublicChat[]): Map<PublicChat, string> {
  const taken = new Set<string>();
  const ids = new Map<PublicChat, string>();
  for (const chat of chats) {
    const base =
      chat.link.match(USERNAME)?.[1]?.toLowerCase() ??
      (fold(chat.title)
        .replace(/[^\p{L}\p{N}]+/gu, '-')
        .replace(/^-+|-+$/g, '') ||
        'chat');
    let id = base;
    for (let n = 2; taken.has(id); n++) id = `${base}-${n}`;
    taken.add(id);
    ids.set(chat, id);
  }
  return ids;
}

/**
 * `value` as the text of a `<script type="application/ld+json">`. JSON alone
 * is not safe there: a chat's title, which its group's admins choose, could
 * hold `</script>` and end the script early. Every `<` is written as its
 * escape, which JSON reads back as the same character.
 */
export function jsonLd(value: unknown): string {
  return JSON.stringify(value).replace(/</g, '\\u003c');
}
