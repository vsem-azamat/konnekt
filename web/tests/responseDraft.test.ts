import assert from 'node:assert/strict';
import { test } from 'node:test';

import { responseDraft } from '../src/lib/responseDraft.ts';

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
