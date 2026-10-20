import assert from 'node:assert/strict';
import { test } from 'node:test';

import { canBan } from '../src/console/ban.ts';

test('a ban that keeps the messages needs no word typed', () => {
  assert.equal(canBan('ban', '', 'стереть'), true);
});

test('wiping the messages waits for the word', () => {
  assert.equal(canBan('wipe', '', 'стереть'), false);
  assert.equal(canBan('wipe', 'стер', 'стереть'), false);
  assert.equal(canBan('wipe', 'удалить', 'стереть'), false);
  assert.equal(canBan('wipe', 'стереть', 'стереть'), true);
});

test('the word is read as typed on a phone: any case, stray spaces', () => {
  assert.equal(canBan('wipe', '  Стереть ', 'стереть'), true);
  assert.equal(canBan('wipe', 'ERASE', 'erase'), true);
});
