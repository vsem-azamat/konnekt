import assert from 'node:assert/strict';
import { test } from 'node:test';

import { ownerStatus } from '../src/lib/ownerStatus.ts';
import type { MyHelper } from '../src/lib/types.ts';

function mine(over: Partial<MyHelper> = {}): MyHelper {
  return {
    exists: true,
    status: 'published',
    headline: null,
    about: null,
    work_format: 'both',
    city: null,
    place_note: null,
    offers: [],
    under_review: false,
    hidden_reason: null,
    hidden_note: null,
    ...over,
  };
}

test('a listed profile nobody has looked at is «на проверке», and still listed', () => {
  assert.equal(ownerStatus(mine({ under_review: true })), 'review');
  assert.equal(ownerStatus(mine()), 'listed');
});

test('who hid it is told apart: the owner, or an operator', () => {
  assert.equal(ownerStatus(mine({ status: 'hidden' })), 'hidden');
  assert.equal(ownerStatus(mine({ status: 'banned', hidden_reason: 'spam' })), 'banned');
  // An operator's ban is that, whatever else is said about it.
  assert.equal(ownerStatus(mine({ status: 'banned', under_review: true })), 'banned');
});

test('anything not out yet is a draft, a profile not made yet too', () => {
  for (const status of ['draft', 'pending', null]) {
    assert.equal(ownerStatus(mine({ status })), 'draft');
  }
  assert.equal(ownerStatus(mine({ exists: false, status: null })), 'draft');
});
