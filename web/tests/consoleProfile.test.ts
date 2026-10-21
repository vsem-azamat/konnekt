import assert from 'node:assert/strict';
import { test } from 'node:test';
import { hideBody, profileActions } from '../src/console/profile.ts';
import type { AdminProfileDetail } from '../src/lib/generated/types.gen.ts';

function profile(over: Partial<AdminProfileDetail> = {}): AdminProfileDetail {
  return {
    user_id: 1,
    name: 'Ekaterina K.',
    status: 'published',
    headline: null,
    about: null,
    services: [],
    institution: null,
    published_at: '2026-10-19T10:00:00Z',
    reviewed_at: null,
    updated_at: '2026-10-19T10:00:00Z',
    hidden_reason: null,
    hidden_note: null,
    ...over,
  };
}

const LOOKED = '2026-10-20T08:00:00Z';

test('a new listed profile is kept or hidden, and can be seen as students see it', () => {
  assert.deepEqual(profileActions(profile()), ['keep', 'hide', 'view']);
});

test('a profile already looked at is not kept twice', () => {
  assert.deepEqual(profileActions(profile({ reviewed_at: LOOKED })), ['hide', 'view']);
});

test('a hidden profile only comes back: students cannot see it', () => {
  assert.deepEqual(profileActions(profile({ status: 'banned', reviewed_at: LOOKED })), [
    'restore',
  ]);
});

test('a hidden profile its owner changed comes back, or stays hidden on purpose', () => {
  assert.deepEqual(profileActions(profile({ status: 'banned' })), ['restore', 'keep']);
});

test('a profile its owner took down or never finished is not the operator’s to act on', () => {
  for (const status of ['hidden', 'draft', 'pending'] as const) {
    assert.deepEqual(profileActions(profile({ status })), []);
  }
});

test('a reason from the list goes alone, «другое» only with words', () => {
  assert.deepEqual(hideBody('spam', 'ignored'), { reason: 'spam' });
  assert.deepEqual(hideBody('other', '  Чужие фото '), {
    reason: 'other',
    note: 'Чужие фото',
  });
  assert.equal(hideBody('other', '   '), null);
  assert.equal(hideBody(null, ''), null);
  assert.equal(hideBody('other', 'x'.repeat(201)), null);
});
