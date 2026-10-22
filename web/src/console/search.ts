/**
 * The console's search across everything, from the browser's top bar (#288,
 * layout A): a few chats and people, each a way to the screen that shows it.
 */

import type { ConsoleChat } from './session';

export interface SearchChat {
  id: number;
  title: string | null;
  resource_status: ConsoleChat['resource_status'];
  public_link: string | null;
}

export interface SearchPerson {
  user_id: number;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  /** They have a card on the Audience screen. */
  in_audience: boolean;
  /** On the global blacklist. */
  blocked: boolean;
}

export interface SearchResults {
  chats: SearchChat[];
  people: SearchPerson[];
}

/** One thing found, in the order the list shows them. */
export type Found =
  | { kind: 'chat'; chat: SearchChat; to: string }
  | { kind: 'person'; person: SearchPerson; to: string | null };

/** The text webapi is asked about, or null when nothing is typed. */
export function searchText(typed: string): string | null {
  const text = typed.trim();
  return text.replace(/^@/, '').trim() ? text : null;
}

export function searchPath(text: string): string {
  return `/api/search?${new URLSearchParams({ q: text })}`;
}

/**
 * Where a person opens: their card, else the blacklist that names them;
 * someone only the chats know has no screen of their own yet.
 */
export function personTarget(person: SearchPerson): string | null {
  if (person.in_audience) return `/console/audience/${person.user_id}`;
  if (person.blocked) return '/console/blacklist';
  return null;
}

export function foundList(results: SearchResults): Found[] {
  return [
    ...results.chats.map(
      (chat): Found => ({ kind: 'chat', chat, to: `/console/chats/${chat.id}` }),
    ),
    ...results.people.map(
      (person): Found => ({ kind: 'person', person, to: personTarget(person) }),
    ),
  ];
}
