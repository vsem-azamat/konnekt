/**
 * Who a row in the console is about, as a face: the photo webapi keeps for a
 * person or a chat, and the letters that stand in while it loads or when there
 * is none. Nothing here draws (Faces.tsx does).
 */

import { initials } from '../lib/chats.ts';

/** The tones a face is painted in, as many as `--tone-N` in tokens.css. */
const TONES = 6;

export interface FacePerson {
  user_id: number;
  first_name: string | null;
  last_name: string | null;
  username: string | null;
}

/** A name's first letter: an emoji in front is skipped, never cut in half. */
const firstLetter = (text: string | null) => text?.match(/\p{L}/u)?.[0];

/** «Мила Орлова» is «МО»; a name-less person is their handle's first letter. */
export function personLetters(person: FacePerson): string {
  const first = firstLetter(person.first_name);
  const last = firstLetter(person.last_name);
  if (first) return `${first}${last ?? ''}`.toUpperCase();
  if (last) return last.toUpperCase();
  return (firstLetter(person.username) ?? '#').toUpperCase();
}

/** The same person is the same colour on every screen. */
export function personTone(userId: number): number {
  return ((userId % TONES) + TONES) % TONES;
}

export function chatLetters(chat: { id: number; title: string | null }): string {
  return initials(chat.title ?? String(chat.id));
}

export const personPhotoPath = (userId: number) => `/api/users/${userId}/photo`;
export const chatPhotoPath = (chatId: number) => `/api/chats/${chatId}/photo`;

/** Where a person's Telegram profile opens, or null without a @username. */
export function profileLink(person: Pick<FacePerson, 'username'>): string | null {
  return person.username ? `https://t.me/${person.username}` : null;
}
