/**
 * The console's chat list, apart from the screen that draws it.
 *
 * Grouped the way the public directory groups them, by parent chat, with the
 * chats the bot found but nobody approved yet above everything else: they are
 * the ones waiting for a decision.
 */

import { fold } from '../lib/chats.ts';
import type { ChatStatus, ConsoleChat, ConsoleChatDetail } from './session.ts';

export type StatusFilter = 'all' | ChatStatus;

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

export function consoleSections(
  chats: ConsoleChat[],
  filter: StatusFilter,
  query: string,
): ConsoleSection[] {
  const byId = new Map(chats.map((chat) => [chat.id, chat]));
  const isParent = new Set(
    chats.flatMap((chat) =>
      chat.parent_chat_id !== null && byId.has(chat.parent_chat_id)
        ? [chat.parent_chat_id]
        : [],
    ),
  );
  const shown = chats.filter(
    (chat) =>
      (filter === 'all' || chat.resource_status === filter) && matches(chat, query),
  );

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

export function statusCounts(chats: ConsoleChat[]): Record<StatusFilter, number> {
  const count = (status: ChatStatus) =>
    chats.filter((chat) => chat.resource_status === status).length;
  return {
    all: chats.length,
    discovered: count('discovered'),
    approved: count('approved'),
    observed: count('observed'),
    external: count('external'),
    disabled: count('disabled'),
  };
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

/** A `t.me/+hash` or `joinchat` link, as opposed to a username: webapi's rule. */
function isInviteLink(link: string): boolean {
  const tail = link.replace(/\/+$/, '').split('/').pop() ?? '';
  return tail.startsWith('+') || link.includes('joinchat');
}

/**
 * Whether people walk straight into the chat, whatever its mode says: a public
 * chat that does not approve new members sends the bot no request to answer.
 * Unknown until the bot has asked Telegram, and then the mode stands.
 */
export function joinsDirectly(
  chat: Pick<ConsoleChatDetail, 'public_link' | 'join_by_request'>,
): boolean {
  const isPublic = chat.public_link !== null && !isInviteLink(chat.public_link);
  return isPublic && chat.join_by_request === false;
}
