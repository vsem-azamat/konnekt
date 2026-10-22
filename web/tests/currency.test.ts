import assert from 'node:assert/strict';
import { test } from 'node:test';

import { currencyLabel } from '../src/lib/currency.ts';

test('crowns read as people here write them, not as their ISO code', () => {
  assert.equal(currencyLabel('CZK'), 'Kč');
});

test('a price that names no currency is in crowns, as the API defaults it', () => {
  assert.equal(currencyLabel(undefined), 'Kč');
});

test('any other currency keeps its code rather than vanishing', () => {
  assert.equal(currencyLabel('EUR'), 'EUR');
});
