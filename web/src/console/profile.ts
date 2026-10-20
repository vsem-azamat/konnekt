/** A catalog profile in the console, apart from the sheet that shows it. */

import type { AdminProfileDetail } from '../lib/generated/types.gen.ts';

export type ProfileAction = 'keep' | 'hide' | 'view' | 'restore';

/**
 * What the operator may do with a profile, in the order the sheet offers it.
 * The catalog allows hiding only a listed profile and restoring only a hidden
 * one; one its owner took down is theirs.
 */
export function profileActions(profile: AdminProfileDetail): ProfileAction[] {
  if (profile.status === 'banned') return ['restore'];
  if (profile.status !== 'published') return [];
  return profile.reviewed_at ? ['hide', 'view'] : ['keep', 'hide', 'view'];
}
