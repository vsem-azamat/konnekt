/**
 * The chat directory, as the Chats tab reads it.
 *
 * The chats are supervisor-telegram's (`GET /api/public/catalog`), served on
 * this origin by the router. What may be read and why is in
 * catalog/docs/architecture.md, «One origin, two APIs»; how the directory is
 * built from it is the paragraph after.
 */

import { find } from './search.ts';

/** Supervisor's own words for how much a chat talks. `unknown` is an answer. */
export type Activity = 'unknown' | 'quiet' | 'active' | 'busy';

/** One chat as supervisor publishes it: no ids, nothing about who is in it. */
export interface PublicChat {
  title: string;
  link: string;
  /**
   * The section's title — the parent chat's, or the chat's own when others sit
   * under it: supervisor's grouping. No name is written in the app.
   */
  group: string | null;
  /** The group's university as the catalog codes it ("cvut"), when set. */
  institution: string | null;
  activity: Activity;
  /** How many people, as last measured. Null when never measured, not zero. */
  member_count: number | null;
  /** Whether the chat is split into Telegram topics. */
  is_forum: boolean;
  /**
   * Somebody else's chat, listed so it can be found: Konnekt does not run it,
   * so its rules are not ours. False for every chat we run.
   */
  external: boolean;
}

const ACTIVITIES: readonly Activity[] = ['unknown', 'quiet', 'active', 'busy'];

/** A catalog institution code, the shape supervisor stores. */
const INSTITUTION_CODE = /^[a-z0-9][a-z0-9_-]{0,31}$/;

/** Where a chat may lead: Telegram's own hosts, which openTelegramLink accepts. */
const TELEGRAM_LINK = /^https:\/\/(t\.me|telegram\.me|telegram\.dog)\//;

/**
 * The directory as it arrived, checked rather than trusted.
 *
 * It comes from another service through a proxy, so anything can: a
 * Cloudflare page instead of JSON, an item without a title, an activity added
 * later. An item that cannot be drawn or opened is dropped; an activity this
 * app does not know is `unknown`, which draws nothing.
 */
export function sanitize(payload: unknown[]): PublicChat[] {
  const chats: PublicChat[] = [];
  for (const item of payload) {
    if (!item || typeof item !== 'object') continue;
    const {
      title,
      link,
      group,
      institution,
      activity,
      member_count,
      is_forum,
      external,
    } = item as Record<string, unknown>;
    if (typeof title !== 'string' || !title.trim()) continue;
    if (typeof link !== 'string' || !TELEGRAM_LINK.test(link)) continue;
    chats.push({
      title,
      link,
      group: typeof group === 'string' && group ? group : null,
      institution:
        typeof institution === 'string' && INSTITUTION_CODE.test(institution)
          ? institution
          : null,
      activity: ACTIVITIES.includes(activity as Activity)
        ? (activity as Activity)
        : 'unknown',
      member_count:
        Number.isInteger(member_count) && (member_count as number) >= 0
          ? (member_count as number)
          : null,
      is_forum: is_forum === true,
      external: external === true,
    });
  }
  return chats;
}

/** A line of the directory: a group with its own screen, or a chat. */
export type Entry =
  | { kind: 'section'; name: string; chats: PublicChat[] }
  | { kind: 'chat'; chat: PublicChat };

export interface Directory {
  entries: Entry[];
  /** Chats without a group, shown last under their own heading. */
  rest: PublicChat[];
}

/**
 * Entries in the order supervisor gave, with three exceptions.
 *
 * A group with a single chat is that chat: a screen with one line behind it
 * is a tap for nothing. A group the server returned in two runs is still one
 * group, since the directory is a list of places, not a transcript of rows.
 * And the reader's own university comes first; the rest keep their order.
 */
export function directory(chats: PublicChat[], mine: string | null = null): Directory {
  const groups = new Map<string, PublicChat[]>();
  const rest: PublicChat[] = [];
  for (const chat of chats) {
    if (chat.group === null) {
      rest.push(chat);
      continue;
    }
    const members = groups.get(chat.group);
    if (members) members.push(chat);
    else groups.set(chat.group, [chat]);
  }

  const entries: Entry[] = [];
  for (const [name, members] of groups) {
    const [only] = members;
    entries.push(
      members.length === 1 && only
        ? { kind: 'chat', chat: only }
        : { kind: 'section', name, chats: members },
    );
  }
  if (mine !== null) {
    const own = (entry: Entry) =>
      (entry.kind === 'chat' ? entry.chat : entry.chats[0])?.institution === mine;
    entries.sort((a, b) => Number(own(b)) - Number(own(a)));
  }
  return { entries, rest };
}

/**
 * A section's chats split by who runs them, each half in the order given:
 * ours above, the ones it only lists below under their own heading.
 */
export function byOwner(chats: PublicChat[]): {
  ours: PublicChat[];
  others: PublicChat[];
} {
  return {
    ours: chats.filter((chat) => !chat.external),
    others: chats.filter((chat) => chat.external),
  };
}

/** How many chat names a section's row lists under its own. */
const HINT_CHATS = 3;

/**
 * A few of a section's chats, for the row that opens it.
 *
 * The section's own general chat, named like the section, is skipped: the
 * row's title already says it. Found by name rather than by position, because
 * where supervisor puts it has changed before.
 */
export function sectionHint(section: Extract<Entry, { kind: 'section' }>): string {
  return section.chats
    .filter((chat) => chat.title !== section.name)
    .slice(0, HINT_CHATS)
    .map((chat) => chat.title)
    .join(', ');
}

/** Lower case, without diacritics: «ČVUT» and «cvut» are the same word here. */
export function fold(text: string): string {
  return text.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase();
}

/**
 * The chats every word of the query starts a word of, in title, group, the
 * university's code or its city, in any order and either script (see
 * lib/search.ts).
 *
 * The code and the city are there for what nobody writes in a title: «uk»,
 * «muni», «брно». They also put a university's dormitories under its name,
 * which is where they belong. A city takes no typos, since «права» is one
 * letter from «praha». Cities come from the catalog's taxonomy.
 *
 * Flat on purpose: somebody who typed «fit» wants the chat, not the section
 * it sits in. An empty query narrows nothing.
 */
export function search(
  chats: PublicChat[],
  query: string,
  cityOf: ReadonlyMap<string, string> = new Map(),
): PublicChat[] {
  return find(
    chats,
    (chat) => [
      chat.title,
      chat.group,
      chat.institution,
      { exact: chat.institution === null ? null : cityOf.get(chat.institution) },
    ],
    query,
  );
}

/** Each university's city by its code, for {@link search}. */
export function cities(
  taxonomy: { code: string; city: string | null }[],
): Map<string, string> {
  const out = new Map<string, string>();
  for (const { code, city } of taxonomy) if (city) out.set(code, city);
  return out;
}

/**
 * Where a chat is, for its preview: the university's full name and its city,
 * from the catalog's taxonomy. Null when the chat names no university or the
 * taxonomy has not heard of it: a bare code says nothing to a reader.
 */
export function placeOf(
  chat: PublicChat,
  taxonomy: readonly { code: string; name: string; city: string | null }[],
): string | null {
  if (chat.institution === null) return null;
  const university = taxonomy.find(({ code }) => code === chat.institution);
  if (!university) return null;
  return university.city ? `${university.name} · ${university.city}` : university.name;
}

/** Which chip a chat wears. None for `unknown`: an empty space is the honest answer. */
export function chipFor(activity: Activity): Exclude<Activity, 'unknown'> | null {
  return activity === 'unknown' ? null : activity;
}

/**
 * A tile's letters, from the name before any «|»: chats name themselves
 * twice, «ČVUT | ЧВУТ», and the two halves' initials read as one name.
 */
export function initials(title: string): string {
  const [name = title] = title.split('|');
  const words = name
    .replace(/[^\p{L}\p{N} ]/gu, ' ')
    .split(/\s+/)
    .filter(Boolean);
  const [first = '#', second] = words;
  // «ČVUT FIT»: a university's abbreviation, then the faculty's. The
  // faculty's is what tells it from its neighbours. «Fyzika v ČR» ends in an
  // abbreviation too, but does not start with one.
  const last = words.at(-1) ?? '';
  const isAbbreviation = (word: string) =>
    word.length <= 5 && (word.match(/\p{Lu}/gu)?.length ?? 0) >= 2;
  // «VŠE», «VŠCHT»: an abbreviation is the name, and cutting it to two
  // letters makes neighbours identical.
  if (words.length === 1 && isAbbreviation(first)) return first.toUpperCase();
  if (
    words.length > 1 &&
    isAbbreviation(first) &&
    isAbbreviation(last) &&
    last.length <= 4
  ) {
    return last.toUpperCase();
  }
  if (second) return (first.charAt(0) + second.charAt(0)).toUpperCase();
  return first.slice(0, 2).toUpperCase();
}

/** An institution as the catalog's taxonomy lists it, as far as this needs. */
export interface TaxonomyInstitution {
  id: number;
  code: string;
  parent_id: number | null;
  faculties: TaxonomyInstitution[];
}

/**
 * The university a student chose, by its code: their own when they chose a
 * university, its parent's when they chose a faculty. Null when there is
 * nothing to put first.
 */
export function ownUniversity(
  institution: Pick<TaxonomyInstitution, 'id' | 'code' | 'parent_id'> | null | undefined,
  taxonomy: TaxonomyInstitution[],
): string | null {
  if (!institution) return null;
  if (institution.parent_id === null) return institution.code;
  return (
    taxonomy.find((university) =>
      university.faculties.some((faculty) => faculty.id === institution.id),
    )?.code ?? null
  );
}
