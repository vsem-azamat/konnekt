import assert from 'node:assert/strict';
import { test } from 'node:test';

import { botStanding, missingRights, rightsChange } from '../src/console/botState.ts';

const FULL = {
  can_delete_messages: true,
  can_restrict_members: true,
  can_invite_users: true,
  can_pin_messages: true,
  can_change_info: true,
};

test('an administrator with every right the bot uses lacks nothing', () => {
  assert.deepEqual(missingRights({ status: 'administrator', rights: FULL }), []);
});

test('the rights an administrator lacks are named in the order they matter', () => {
  const rights = { ...FULL, can_pin_messages: false, can_restrict_members: false };

  assert.deepEqual(missingRights({ status: 'administrator', rights }), [
    'can_restrict_members',
    'can_pin_messages',
  ]);
});

test('a right Telegram left out is missing', () => {
  const { can_invite_users: _, ...rest } = FULL;

  assert.deepEqual(missingRights({ status: 'administrator', rights: rest }), [
    'can_invite_users',
  ]);
});

test('the owner of the chat lacks nothing, and neither does a bot that is not an administrator', () => {
  // Not an administrator is its own, bigger problem: listing every right would bury it.
  assert.deepEqual(missingRights({ status: 'creator', rights: {} }), []);
  assert.deepEqual(missingRights({ status: 'member', rights: {} }), []);
});

test('the standing says what is wrong first', () => {
  assert.equal(botStanding(null, null), 'unknown');
  assert.equal(botStanding({ status: 'administrator', rights: FULL }, null), 'ok');
  assert.equal(
    botStanding(
      { status: 'administrator', rights: { ...FULL, can_delete_messages: false } },
      null,
    ),
    'lacking',
  );
  assert.equal(botStanding({ status: 'member', rights: {} }, null), 'not_admin');
  assert.equal(botStanding({ status: 'restricted', rights: {} }, null), 'not_admin');
  assert.equal(botStanding({ status: 'kicked', rights: {} }, null), 'removed');
  assert.equal(botStanding({ status: 'left', rights: {} }, null), 'left');
  // The hourly loop's mark wins over rights not corrected since…
  const confirmed = {
    status: 'administrator',
    rights: FULL,
    known_at: '2026-11-01T09:00:00',
  };
  assert.equal(botStanding(confirmed, '2026-11-01T10:00:00'), 'left');
  // …but not over the bot's own word that it is back, which comes at once.
  assert.equal(botStanding(confirmed, '2026-11-01T08:00:00'), 'ok');
});

test('a change in the history is told by the rights it gave and took', () => {
  const before = { status: 'administrator', rights: FULL };
  const after = {
    status: 'administrator',
    rights: { ...FULL, can_delete_messages: false, can_manage_video_chats: true },
  };

  // Only rights the bot uses are worth a line.
  assert.deepEqual(rightsChange(before, after), {
    gained: [],
    lost: ['can_delete_messages'],
  });
  assert.deepEqual(rightsChange(after, before), {
    gained: ['can_delete_messages'],
    lost: [],
  });
  assert.deepEqual(rightsChange(null, before), { gained: [], lost: [] });
});
