import assert from 'node:assert/strict';
import { test } from 'node:test';

import { QueryClient } from '@tanstack/react-query';

import { afterHelperSaved } from '../src/lib/helperSaved.ts';
import type { Me, MyHelper } from '../src/lib/types.ts';

const before: MyHelper = {
  exists: false,
  status: null,
  headline: null,
  about: null,
  work_format: 'both',
  city: null,
  place_note: null,
  offers: [],
};
const me = { id: 1, tg_id: 1, name: 'Студент', is_helper: true } as Me;

test('publishing leaves no cached profile for «Моя анкета» to fill itself from', () => {
  const client = new QueryClient();
  // What /offer loaded before the save: no services yet.
  client.setQueryData(['my-helper'], before);

  afterHelperSaved(client, me);

  // Invalidating kept this copy, «Моя анкета» filled its form from it once and
  // «Сохранить» then sent an empty list, deleting what was just published (#230).
  assert.equal(client.getQueryData(['my-helper']), undefined);
});

test('the account the server answered with is what the app now knows', () => {
  const client = new QueryClient();
  afterHelperSaved(client, me);
  assert.deepEqual(client.getQueryData(['me']), me);
});
