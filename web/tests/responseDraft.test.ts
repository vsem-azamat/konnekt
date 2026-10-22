import assert from 'node:assert/strict';
import { test } from 'node:test';

import { openDraft, responseDraft, withStarter } from '../src/lib/responseDraft.ts';

test('a message alone goes out without a price', () => {
  assert.deepEqual(responseDraft('  Помогу в среду  ', ''), {
    message: 'Помогу в среду',
  });
  assert.deepEqual(responseDraft('Помогу', '   '), { message: 'Помогу' });
});

test('a price is per hour', () => {
  assert.deepEqual(responseDraft('Помогу', ' 450 '), {
    message: 'Помогу',
    price_amount: 450,
    price_unit: 'hour',
  });
  assert.deepEqual(responseDraft('Помогу', '0'), {
    message: 'Помогу',
    price_amount: 0,
    price_unit: 'hour',
  });
});

test('a decimal comma is a decimal point, a thousands one is not a price', () => {
  assert.deepEqual(responseDraft('Помогу', '350,5'), {
    message: 'Помогу',
    price_amount: 350.5,
    price_unit: 'hour',
  });
  assert.equal(responseDraft('Помогу', '1,000'), null);
  assert.equal(responseDraft('Помогу', '1,000,5'), null);
});

test('too short a message, or a price that is not a number, cannot be sent', () => {
  assert.equal(responseDraft('ок', ''), null);
  assert.equal(responseDraft('   ', '450'), null);
  assert.equal(responseDraft('Помогу', 'дорого'), null);
  assert.equal(responseDraft('Помогу', '-5'), null);
});

test('a price taken from the profile keeps the profile’s unit', () => {
  assert.deepEqual(responseDraft('Помогу', '800', 'work'), {
    message: 'Помогу',
    price_amount: 800,
    price_unit: 'work',
  });
});

test('the draft opens on the price the profile asks for that kind of work', () => {
  assert.deepEqual(openDraft(7, { amount: 600, currency: 'CZK', unit: 'hour' }), {
    requestId: 7,
    message: '',
    price: '600',
    unit: 'hour',
    suggested: true,
  });
});

test('without a price in the profile, or one left to agree, the field starts empty and per hour', () => {
  const empty = { requestId: 7, message: '', price: '', unit: 'hour', suggested: false };
  assert.deepEqual(openDraft(7, null), empty);
  assert.deepEqual(
    openDraft(7, { amount: null, currency: 'CZK', unit: 'negotiable' }),
    empty,
  );
});

test('a starter begins an empty message and follows a typed one as its own sentence', () => {
  assert.equal(withStarter('', 'Могу на этой неделе'), 'Могу на этой неделе');
  assert.equal(
    withStarter('Привет', 'Могу на этой неделе'),
    'Привет. Могу на этой неделе',
  );
  assert.equal(
    withStarter('Привет!  ', 'Могу на этой неделе'),
    'Привет! Могу на этой неделе',
  );
});

test('a starter already in the message is not added twice', () => {
  assert.equal(
    withStarter('Могу на этой неделе', 'Могу на этой неделе'),
    'Могу на этой неделе',
  );
});
