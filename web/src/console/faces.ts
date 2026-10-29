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

/** «Дарина Коваленко» is «ДК»; a name-less person is their handle's first letter. */
export function personLetters(person: FacePerson): string {
  const first = person.first_name?.trim().at(0);
  const last = person.last_name?.trim().at(0);
  if (first) return `${first}${last ?? ''}`.toUpperCase();
  return (person.username?.at(0) ?? '#').toUpperCase();
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
