import assert from 'node:assert/strict';
import { test } from 'node:test';

import { revokeMessages } from '../src/console/ban.ts';

test('a ban that keeps the messages needs no word typed', () => {
  assert.equal(revokeMessages('ban', '', 'стереть'), false);
  assert.equal(revokeMessages('ban', 'стереть', 'стереть'), false);
});

test('wiping the messages waits for the word', () => {
  assert.equal(revokeMessages('wipe', '', 'стереть'), null);
  assert.equal(revokeMessages('wipe', 'стер', 'стереть'), null);
  assert.equal(revokeMessages('wipe', 'удалить', 'стереть'), null);
  assert.equal(revokeMessages('wipe', 'стереть', 'стереть'), true);
});

test('the word is read as typed on a phone: any case, stray spaces', () => {
  assert.equal(revokeMessages('wipe', '  Стереть ', 'стереть'), true);
  assert.equal(revokeMessages('wipe', 'ERASE', 'erase'), true);
});
