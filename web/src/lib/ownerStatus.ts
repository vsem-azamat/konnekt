/**
 * Where a helper's own profile stands, as «Моя анкета» tells its owner.
 *
 * Five states, not the server's statuses: «на проверке» is a listed profile
 * no operator has looked at yet, and listing does not wait for it; `banned`
 * is the operator's «Скрыть», which the owner reads as hidden by an
 * administrator and cannot undo.
 */

import type { MyHelper } from './types';

export type OwnerStatus = 'draft' | 'review' | 'listed' | 'hidden' | 'banned';

export function ownerStatus(helper: MyHelper): OwnerStatus {
  if (helper.status === 'banned') return 'banned';
  if (helper.status === 'hidden') return 'hidden';
  if (helper.status === 'published') return helper.under_review ? 'review' : 'listed';
  return 'draft';
}

/**
 * Where «Видимость» starts when the form opens.
 *
 * A profile not made yet starts listed, so «Сохранить» publishes it; the draft
 * hint says so. One the owner saved hidden, as a draft or after listing it,
 * starts hidden. A banned one starts listed: the server ignores the flag then,
 * and if an operator lists it again while the screen is open, the next save
 * must not take it down.
 */
export function startsListed(helper: MyHelper): boolean {
  return helper.status !== 'hidden' && helper.status !== 'draft';
}
