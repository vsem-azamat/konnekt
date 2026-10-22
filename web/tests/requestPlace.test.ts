import assert from 'node:assert/strict';
import { test } from 'node:test';

import { REQUEST_CITIES, requestPlace } from '../src/lib/requestPlace.ts';

test('the sheet opens on «Неважно» in Prague', () => {
  assert.deepEqual(requestPlace('both', REQUEST_CITIES[0]), {
    work_format: 'both',
    city: 'Praha',
  });
});

test('the cities offered are spelt as the feed filters them, in Czech', () => {
  assert.deepEqual(REQUEST_CITIES, ['Praha', 'Brno']);
});

test('help online is in no city, whatever was picked before switching', () => {
  assert.deepEqual(requestPlace('online', 'Brno'), { work_format: 'online', city: null });
});

test('a city typed by hand goes as typed, trimmed; an empty one is any city', () => {
  assert.deepEqual(requestPlace('offline', '  Ostrava '), {
    work_format: 'offline',
    city: 'Ostrava',
  });
  assert.deepEqual(requestPlace('offline', '   '), {
    work_format: 'offline',
    city: null,
  });
});
