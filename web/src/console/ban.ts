/** The console's ban, apart from the sheet that asks for it. */

/** Ban alone, or ban and delete every message of theirs the bot recorded. */
export type BanChoice = 'ban' | 'wipe';

/**
 * Whether the ban may go. Deleting the messages cannot be undone, so it waits
 * for `word` to be typed; a phone keyboard capitalises and adds a space, and
 * neither is a change of mind.
 */
export function canBan(choice: BanChoice, typed: string, word: string): boolean {
  if (choice === 'ban') return true;
  return typed.trim().toLocaleLowerCase() === word.toLocaleLowerCase();
}
