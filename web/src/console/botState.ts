/**
 * The bot's own place in a chat, as the console shows it: what Telegram last
 * said the bot is there and which of the rights it works with it lacks.
 */

/** As `chat_bot_rights` keeps it: Telegram's status, and every right it named. */
export interface BotRights {
  status: string;
  rights: Record<string, boolean>;
}

/**
 * The rights the bot works with, by what goes wrong without them first:
 * moderation, then joining, then the chat's furniture.
 */
export const USED_RIGHTS = [
  'can_delete_messages',
  'can_restrict_members',
  'can_invite_users',
  'can_pin_messages',
  'can_change_info',
] as const;

export type UsedRight = (typeof USED_RIGHTS)[number];

const ADMINISTRATORS = new Set(['administrator', 'creator']);

/** What an administrator lacks; nothing for the owner, nor for a bot that is not an administrator. */
export function missingRights(bot: BotRights): UsedRight[] {
  if (bot.status !== 'administrator') return [];
  return USED_RIGHTS.filter((right) => !bot.rights[right]);
}

export type Standing =
  | 'unknown'
  | 'ok'
  | 'lacking'
  | 'not_admin'
  | 'removed'
  | 'left'
  | 'absent';

/**
 * The one thing to say about the bot in the chat, the worst first.
 *
 * A kick or a leave the bot was told of stands, with its own date. Without
 * one, `absentAt` is the hourly loop's mark: it comes before the daily check
 * corrects the rights, and is stamped again at every daily ask. The bot's own
 * update that it is back comes at once, so rights newer than the mark win.
 */
export function botStanding(
  bot: (BotRights & { known_at?: string }) | null,
  absentAt: string | null,
): Standing {
  if (bot?.status === 'kicked') return 'removed';
  if (bot?.status === 'left') return 'left';
  if (absentAt !== null && !(bot?.known_at && bot.known_at > absentAt)) return 'absent';
  if (bot === null) return 'unknown';
  if (!ADMINISTRATORS.has(bot.status)) return 'not_admin';
  return missingRights(bot).length ? 'lacking' : 'ok';
}

/** The rights the bot uses that one change in the history gave and took. */
export function rightsChange(
  before: BotRights | null,
  after: BotRights,
): { gained: UsedRight[]; lost: UsedRight[] } {
  if (before === null) return { gained: [], lost: [] };
  // A restricted member's permissions are not rights the bot holds.
  const had = (bot: BotRights, right: UsedRight) =>
    bot.status === 'creator' ||
    (bot.status === 'administrator' && Boolean(bot.rights[right]));
  return {
    gained: USED_RIGHTS.filter((right) => !had(before, right) && had(after, right)),
    lost: USED_RIGHTS.filter((right) => had(before, right) && !had(after, right)),
  };
}
