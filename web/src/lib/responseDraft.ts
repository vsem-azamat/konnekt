/**
 * What a helper has typed into the answer sheet, as the server will take it.
 *
 * Null while it cannot go out: fewer than three characters of message, or a
 * price that is not a number. An empty price field means "did not say", not
 * zero, so it leaves the price out of the payload altogether.
 */

import type { ResponseCreate } from './types';

export function responseDraft(message: string, price: string): ResponseCreate | null {
  const words = message.trim();
  if (words.length < 3) return null;

  const typed = price.trim();
  if (!typed) return { message: words };

  const amount = Number(typed);
  if (!Number.isFinite(amount) || amount < 0) return null;
  return { message: words, price_amount: amount, price_unit: 'hour' };
}
