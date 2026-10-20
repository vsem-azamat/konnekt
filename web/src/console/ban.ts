/** The console's ban, apart from the sheet that asks for it. */

/** Ban alone, or ban and delete every message of theirs the bot recorded. */
export type BanChoice = 'ban' | 'wipe';

/**
 * The `revoke_messages` a ban is sent with, or none while it may not go yet.
 * Deleting the messages cannot be undone, so it waits for `word` to be typed;
 * a phone keyboard capitalises and adds a space, and neither is a change of
 * mind.
 */
export function revokeMessages(
  choice: BanChoice,
  typed: string,
  word: string,
): boolean | null {
  if (choice === 'ban') return false;
  return typed.trim().toLocaleLowerCase() === word.toLocaleLowerCase() ? true : null;
}
