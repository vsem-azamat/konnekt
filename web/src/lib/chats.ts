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

/**
 * What a chat is about, and the catalogue's heading for it. Supervisor says
 * `university` for a university's chats; a chat nobody filed has none.
 */
export type Topic = 'university' | 'subjects' | 'dorms' | 'work_it' | 'general';

/**
 * A group people talk in, or a channel they only read. Only somebody else's
 * chat is ever a channel, and its count is of subscribers.
 */
export type ChatKind = 'group' | 'channel';

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
  /** A kind this app does not know, or none, is a group: it draws as before. */
  kind: ChatKind;
  /**
   * Somebody else's chat, listed so it can be found: Konnekt does not run it,
   * so its rules are not ours. False for every chat we run.
   */
  external: boolean;
  /**
   * The chat's photo, an address on this origin that changes when the photo
   * does. Null when it has none or supervisor could not read it, and the tile
   * keeps its letters.
   */
  avatar: string | null;
  /**
   * The city the chat is for, spelled as the catalog's taxonomy spells it
   * («Praha»). Null is all of Czechia, not unknown: such a chat is in every city.
   */
  city: string | null;
  topic: Topic | null;
}

const ACTIVITIES: readonly Activity[] = ['unknown', 'quiet', 'active', 'busy'];

/** The catalogue's headings, in the order it shows them. */
export const TOPICS: readonly Topic[] = [
  'university',
  'subjects',
  'dorms',
  'work_it',
  'general',
];

/** A catalog institution code, the shape supervisor stores. */
const INSTITUTION_CODE = /^[a-z0-9][a-z0-9_-]{0,31}$/;

/** Where a photo may come from: supervisor's own picture route, and nowhere else. */
const AVATAR_PATH = /^\/api\/public\/avatars\/[A-Za-z0-9_-]{1,64}$/;

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
      kind,
      external,
      avatar,
      city,
      topic,
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
      kind: kind === 'channel' ? 'channel' : 'group',
      external: external === true,
      avatar: typeof avatar === 'string' && AVATAR_PATH.test(avatar) ? avatar : null,
      city: typeof city === 'string' && city.trim() ? city : null,
      topic: TOPICS.includes(topic as Topic) ? (topic as Topic) : null,
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

/** One heading of the catalogue and what stands under it. */
export interface Block {
  heading: Topic;
  entries: Entry[];
}

/** The chat that speaks for an entry: a section's own chat, or its first. */
function lead(entry: Entry): PublicChat | undefined {
  return entry.kind === 'chat' ? entry.chat : (ownChat(entry) ?? entry.chats[0]);
}

/**
 * The catalogue under its headings, for one city or for all (`city` null).
 *
 * Built on {@link directory}, so sections and the student's own university
 * first work as they did. An entry is filed by its lead chat's topic, and an
 * unfiled one under «Общее». A city keeps the entries for it and those for
 * all of Czechia; a section goes by its own chat's city, so a university's
 * faculties are never split between two cities. Empty headings are left out.
 */
export function blocks(
  chats: PublicChat[],
  { mine, city }: { mine: string | null; city: string | null },
): Block[] {
  const { entries, rest } = directory(chats, mine);
  const all: Entry[] = [
    ...entries,
    ...rest.map((chat) => ({ kind: 'chat' as const, chat })),
  ];
  const shown = all.filter((entry) => {
    const where = lead(entry)?.city ?? null;
    return city === null || where === null || where === city;
  });
  return TOPICS.map((heading) => ({
    heading,
    entries: shown.filter((entry) => (lead(entry)?.topic ?? 'general') === heading),
  })).filter((block) => block.entries.length > 0);
}

/**
 * The cities a reader can pick: those that have entries of their own, the one
 * with most first. Chats for all of Czechia name no city.
 */
export function cityChoices(chats: PublicChat[]): string[] {
  // By the same chat {@link blocks} filters by: a faculty in another city
  // than its university's would otherwise offer a chip that shows nothing.
  const { entries, rest } = directory(chats);
  const counts = new Map<string, number>();
  for (const entry of [
    ...entries,
    ...rest.map((chat) => ({ kind: 'chat' as const, chat })),
  ]) {
    const city = lead(entry)?.city;
    if (city) counts.set(city, (counts.get(city) ?? 0) + 1);
  }
  return [...counts]
    .sort(([a, x], [b, y]) => y - x || a.localeCompare(b, 'cs'))
    .map(([city]) => city);
}

/**
 * Where the catalogue opens: the city of the student's university when it has
 * chats, otherwise all of them.
 */
export function defaultCity(
  choices: readonly string[],
  universityCity: string | null | undefined,
): string | null {
  return universityCity && choices.includes(universityCity) ? universityCity : null;
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

/**
 * The section's own chat, which is the university itself: named like the
 * section. Found by name rather than by position, because where supervisor
 * puts it has changed before.
 */
function ownChat(section: Extract<Entry, { kind: 'section' }>): PublicChat | undefined {
  return section.chats.find((chat) => chat.title === section.name);
}

/**
 * The photo for a section's row: that of the section's own chat. A faculty's
 * photo would say the wrong thing, so a section whose own chat has none keeps
 * its letters.
 */
export function sectionAvatar(
  section: Extract<Entry, { kind: 'section' }>,
): string | null {
  return ownChat(section)?.avatar ?? null;
}

/**
 * The chat a section's row speaks for: the university's own, named like the
 * section. Its activity and whether it is ours are the row's, as its photo is.
 */
export function sectionLead(
  section: Extract<Entry, { kind: 'section' }>,
): PublicChat | undefined {
  return ownChat(section);
}

/**
 * How many people a section's row shows: its own chat's, for the same reason
 * as its photo. Adding up the faculties would count one student many times.
 */
export function sectionMembers(
  section: Extract<Entry, { kind: 'section' }>,
): number | null {
  return ownChat(section)?.member_count ?? null;
}

/** How many chat names a section's row lists under its own. */
const HINT_CHATS = 3;

/**
 * What a section's row says under its name: how many chats it holds and the
 * first few of them, cut with «…» when there are more.
 *
 * The section's own chat is skipped, since the row's title already says it;
 * `more` is whether there was one, so the rest are «ещё» chats.
 */
export function sectionHint(section: Extract<Entry, { kind: 'section' }>): {
  count: number;
  names: string;
  more: boolean;
} {
  const own = ownChat(section);
  const others = section.chats.filter((chat) => chat !== own);
  const names = others
    .slice(0, HINT_CHATS)
    .map((chat) => chat.title)
    .join(', ');
  return {
    count: others.length,
    names: others.length > HINT_CHATS ? `${names}…` : names,
    more: own !== undefined,
  };
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
      { exact: chat.city },
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
 * Where a chat is, for its preview: the university's full name when it is a
 * university's chat, and the city supervisor gave, null being all of Czechia —
 * the same value the list filters by, so the two never disagree. No name when
 * the taxonomy has not heard of the university: a bare code says nothing.
 */
export function placeOf(
  chat: PublicChat,
  taxonomy: readonly { code: string; name: string }[],
): { university: string | null; city: string | null } {
  const university =
    chat.institution === null
      ? undefined
      : taxonomy.find(({ code }) => code === chat.institution);
  return {
    university: chat.topic === 'university' ? (university?.name ?? null) : null,
    city: chat.city,
  };
}

/** Which chip a chat wears. None for `unknown`: an empty space is the honest answer. */
export function chipFor(activity: Activity): Exclude<Activity, 'unknown'> | null {
  return activity === 'unknown' ? null : activity;
}

/**
 * Which dot a chat has by its member count in a list: filled for `busy`, a
 * ring for `active`. None for `quiet` either: most chats are, and a mark on
 * nearly every row says nothing. Its sheet still says it in words.
 */
export function rowDotFor(activity: Activity): 'active' | 'busy' | null {
  return activity === 'active' || activity === 'busy' ? activity : null;
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
