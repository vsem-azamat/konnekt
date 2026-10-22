import assert from 'node:assert/strict';
import { test } from 'node:test';

import { REQUEST_CITIES, requestPlace, spelledCity } from '../src/lib/requestPlace.ts';

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

test('a city typed by hand goes trimmed', () => {
  assert.deepEqual(requestPlace('offline', '  Ostrava '), {
    work_format: 'offline',
    city: 'Ostrava',
  });
});

const NAMES = { Ostrava: 'Острава', 'Hradec Králové': 'Градец-Кралове' };

test('a known city typed in the reader’s language goes as the feed spells it', () => {
  assert.equal(spelledCity(' острава ', NAMES), 'Ostrava');
  assert.equal(spelledCity('hradec králové', NAMES), 'Hradec Králové');
});

test('a city the app does not know goes as typed', () => {
  assert.equal(spelledCity(' Kutná Hora ', NAMES), 'Kutná Hora');
  assert.equal(spelledCity('   ', NAMES), '');
});
