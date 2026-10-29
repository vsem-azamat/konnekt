/**
 * The console's chat list, apart from the screen that draws it.
 *
 * Grouped the way the public directory groups them, by parent chat, with the
 * chats the bot found but nobody approved yet above everything else: they are
 * the ones waiting for a decision.
 */

import { fold } from '../lib/chats.ts';
import type { ChatStatus, ConsoleChat } from './session.ts';

export type ConsoleSection =
  | { key: 'review'; title: null; chats: ConsoleChat[] }
  | { key: 'group'; title: string; root: number; chats: ConsoleChat[] }
  | { key: 'rest'; title: null; chats: ConsoleChat[] };

/** Title words, in any order and without diacritics; digits also find an id. */
function matches(chat: ConsoleChat, query: string): boolean {
  const trimmed = query.trim();
  if (!trimmed) return true;
  if (/^-?\d+$/.test(trimmed) && String(chat.id).includes(trimmed)) return true;
  const title = fold(chat.title ?? '');
  return fold(trimmed)
    .split(/\s+/)
    .every((word) => title.includes(word));
}

/**
 * The chats `keep` lets through that match `query`, in sections. Parents are
 * looked up among all of them, so a tab that keeps a child but not its parent
 * still files it under the parent's name.
 */
export function consoleSections(
  chats: ConsoleChat[],
  query: string,
  keep: (chat: ConsoleChat) => boolean = () => true,
): ConsoleSection[] {
  const byId = new Map(chats.map((chat) => [chat.id, chat]));
  const isParent = new Set(
    chats.flatMap((chat) =>
      chat.parent_chat_id !== null && byId.has(chat.parent_chat_id)
        ? [chat.parent_chat_id]
        : [],
    ),
  );
  const shown = chats.filter((chat) => keep(chat) && matches(chat, query));

  const review = shown.filter((chat) => chat.resource_status === 'discovered');
  const groups = new Map<number, ConsoleChat[]>();
  const rest: ConsoleChat[] = [];
  for (const chat of shown) {
    if (chat.resource_status === 'discovered') continue;
    const root =
      chat.parent_chat_id !== null && byId.has(chat.parent_chat_id)
        ? chat.parent_chat_id
        : isParent.has(chat.id)
          ? chat.id
          : null;
    if (root === null) rest.push(chat);
    else groups.set(root, [...(groups.get(root) ?? []), chat]);
  }

  const sections: ConsoleSection[] = [];
  if (review.length) sections.push({ key: 'review', title: null, chats: review });
  for (const [root, members] of groups) {
    // The parent first, then its children in the order they came.
    members.sort((a, b) => Number(b.id === root) - Number(a.id === root));
    sections.push({
      key: 'group',
      title: byId.get(root)?.title ?? String(root),
      root,
      chats: members,
    });
  }
  if (rest.length) sections.push({ key: 'rest', title: null, chats: rest });
  return sections;
}

/** The statuses the public catalogue lists; the others await or ended a decision. */
const LISTABLE: readonly ChatStatus[] = ['approved', 'observed', 'external'];

/**
 * Whether students see the chat on the public tab, by the same rule the
 * public catalogue applies: decided on, with a title and a link.
 */
export function isListed(chat: ConsoleChat): boolean {
  return (
    LISTABLE.includes(chat.resource_status) &&
    Boolean(chat.title) &&
    Boolean(chat.public_link)
  );
}

/** Why a chat is or is not in the students' catalogue, in the order the rule asks. */
export type CatalogPlace = 'listed' | 'undecided' | 'off' | 'no_title' | 'no_link';

export function catalogPlace(chat: ConsoleChat): CatalogPlace {
  if (chat.resource_status === 'discovered') return 'undecided';
  if (chat.resource_status === 'disabled') return 'off';
  if (!chat.title) return 'no_title';
  if (!chat.public_link) return 'no_link';
  return 'listed';
}

/**
 * The console's tabs, each the answer to one question about the chats: which
 * wait for me, which do students see, which did I decide on that they still
 * do not see, which are off.
 */
export type ChatTab = 'all' | 'decide' | 'listed' | 'hidden' | 'off';

export function tabOf(chat: ConsoleChat): Exclude<ChatTab, 'all'> {
  switch (catalogPlace(chat)) {
    case 'undecided':
      return 'decide';
    case 'off':
      return 'off';
    case 'listed':
      return 'listed';
    default:
      return 'hidden';
  }
}

export function tabCounts(chats: ConsoleChat[]): Record<ChatTab, number> {
  const counts: Record<ChatTab, number> = {
    all: chats.length,
    decide: 0,
    listed: 0,
    hidden: 0,
    off: 0,
  };
  for (const chat of chats) counts[tabOf(chat)] += 1;
  return counts;
}

/** How many of them students see: the console's one-line answer to that question. */
export function listedCount(chats: ConsoleChat[]): number {
  return chats.filter(isListed).length;
}

/** A `t.me/+hash` or `joinchat` link, as opposed to a username: webapi's rule. */
function isInviteLink(link: string): boolean {
  const tail = link.replace(/\/+$/, '').split('/').pop();
  return Boolean(tail?.startsWith('+')) || link.includes('joinchat');
}

/**
 * Whether people walk straight into the chat, whatever its mode says: a public
 * chat that does not approve new members sends the bot no request to answer.
 * Unknown until the bot has asked Telegram, and then the mode stands.
 */
export function joinsDirectly(
  chat: Pick<ConsoleChat, 'public_link' | 'join_by_request'>,
): boolean {
  const isPublic = chat.public_link !== null && !isInviteLink(chat.public_link);
  return isPublic && chat.join_by_request === false;
}

export type Guard = 'captcha' | 'welcome';

/**
 * What the bot does for a chat's newcomers; null where it does nothing because
 * the chat is not approved, so the status is the thing to know. Where people
 * walk straight in, a stored captcha asks nobody.
 */
export function chatGuards(
  chat: Pick<
    ConsoleChat,
    | 'resource_status'
    | 'join_mode'
    | 'public_link'
    | 'join_by_request'
    | 'is_welcome_enabled'
  >,
): Guard[] | null {
  if (chat.resource_status !== 'approved') return null;
  const guards: Guard[] = [];
  if (chat.join_mode === 'captcha' && !joinsDirectly(chat)) guards.push('captcha');
  if (chat.is_welcome_enabled) guards.push('welcome');
  return guards;
}
