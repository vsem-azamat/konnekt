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

  assert.equal(client.getQueryData(['my-helper']), undefined);
});

test('leaving before the refetch lands does not bring the old profile back', async () => {
  const client = new QueryClient();
  client.setQueryData(['my-helper'], before);
  // The screen is still refetching when the save succeeds…
  void client
    .fetchQuery({
      queryKey: ['my-helper'],
      queryFn: () => new Promise<MyHelper>(() => {}),
    })
    .catch(() => {});

  afterHelperSaved(client, me);
  // …and «назад» cancels that refetch, which reverts to what it started from.
  await client.cancelQueries({ queryKey: ['my-helper'] }, { revert: true });

  assert.equal(client.getQueryData(['my-helper']), undefined);
});

test('the account the server answered with is what the app now knows', () => {
  const client = new QueryClient();
  afterHelperSaved(client, me);
  assert.deepEqual(client.getQueryData(['me']), me);
});

test('the catalog front page is marked stale, its counts changed', () => {
  const client = new QueryClient();
  client.setQueryData(['home'], { people: [], things: [] });
  afterHelperSaved(client, me);
  assert.equal(client.getQueryState(['home'])?.isInvalidated, true);
});
