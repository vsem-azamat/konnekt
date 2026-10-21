/** A catalog profile in the console, apart from the sheet that shows it. */

import type {
  AdminHide,
  AdminProfileDetail,
  HideReason,
} from '../lib/generated/types.gen.ts';

export type ProfileAction = 'keep' | 'hide' | 'view' | 'restore';

/**
 * What the operator may do with a profile, in the order the sheet offers it.
 * The catalog allows hiding only a listed profile and restoring only a hidden
 * one; one its owner took down is theirs.
 */
export function profileActions(profile: AdminProfileDetail): ProfileAction[] {
  // Back on the list because its owner changed it: list it again, or leave
  // it hidden for the reason it was hidden.
  if (profile.status === 'banned')
    return profile.reviewed_at ? ['restore'] : ['restore', 'keep'];
  if (profile.status !== 'published') return [];
  return profile.reviewed_at ? ['hide', 'view'] : ['keep', 'hide', 'view'];
}

/** What the catalog takes for a note on «Другое». */
export const HIDE_NOTE_MAX = 200;

/**
 * What «Скрыть» sends, or null while it cannot be sent. A reason from the list
 * goes alone, since the owner would never see a note beside it; «Другое» is
 * only a way of saying it in words, so it needs them.
 */
export function hideBody(reason: HideReason | null, note: string): AdminHide | null {
  if (reason === null) return null;
  if (reason !== 'other') return { reason };
  const said = note.trim();
  if (!said || said.length > HIDE_NOTE_MAX) return null;
  return { reason, note: said };
}
