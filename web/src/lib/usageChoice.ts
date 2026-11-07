/**
 * Whether this person lets the app count what they do (lib/track.ts).
 *
 * Kept in Telegram's cloud storage for the bot, so the choice follows them to
 * every device; where the client has none, in this browser's storage. Read
 * before anything is counted, and a read that fails or does not answer in time
 * counts as «off» for this launch: somebody who said no must never be counted
 * because Telegram was slow.
 */

import { cloudStorage } from '@tma.js/sdk-react';
import { OPT_OUT_KEY } from './track';

/** How long a launch waits for the answer before it gives up counting. */
const READ_TIMEOUT_MS = 3000;

function cloud(): boolean {
  try {
    return cloudStorage.isSupported();
  } catch {
    return false;
  }
}

/** The stored choice: true allowed, false turned off, null not known (no answer, or no storage). */
export async function readChoice(): Promise<boolean | null> {
  if (!cloud()) {
    try {
      return localStorage.getItem(OPT_OUT_KEY) !== '1';
    } catch {
      return null;
    }
  }
  try {
    return (await cloudStorage.getItem(OPT_OUT_KEY)) !== '1';
  } catch {
    return null;
  }
}

/** Whether to count this launch: only on an answer, and only if it is not «off». */
export async function countingAllowed(): Promise<boolean> {
  const late = new Promise<null>((resolve) =>
    setTimeout(() => resolve(null), READ_TIMEOUT_MS),
  );
  return (await Promise.race([readChoice(), late])) === true;
}

export async function allowCounting(allowed: boolean): Promise<void> {
  const value = allowed ? '' : '1';
  if (cloud()) {
    await cloudStorage.setItem(OPT_OUT_KEY, value);
    return;
  }
  localStorage.setItem(OPT_OUT_KEY, value);
}
