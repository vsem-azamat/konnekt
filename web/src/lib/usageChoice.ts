/**
 * Whether this person lets the app count what they do (lib/track.ts).
 *
 * Kept in Telegram's cloud storage for the bot, so the choice follows them to
 * every device; where the client has none, in this browser's storage. Read
 * before anything is counted: until the answer comes, nothing is sent.
 */

import { cloudStorage } from '@tma.js/sdk-react';
import { OPT_OUT_KEY } from './track';

/** A slow answer is taken as «not turned off» rather than holding counting back forever. */
const READ_TIMEOUT_MS = 3000;

function cloud(): boolean {
  try {
    return cloudStorage.isSupported();
  } catch {
    return false;
  }
}

export async function countingAllowed(): Promise<boolean> {
  if (!cloud()) {
    try {
      return localStorage.getItem(OPT_OUT_KEY) !== '1';
    } catch {
      return true;
    }
  }
  const read = cloudStorage.getItem(OPT_OUT_KEY).then((value) => value !== '1');
  const late = new Promise<boolean>((resolve) =>
    setTimeout(() => resolve(true), READ_TIMEOUT_MS),
  );
  try {
    return await Promise.race([read, late]);
  } catch {
    return true;
  }
}

export async function allowCounting(allowed: boolean): Promise<void> {
  const value = allowed ? '' : '1';
  if (cloud()) {
    await cloudStorage.setItem(OPT_OUT_KEY, value);
    return;
  }
  try {
    localStorage.setItem(OPT_OUT_KEY, value);
  } catch {
    // Nowhere to keep it: the choice lasts this launch.
  }
}
