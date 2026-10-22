import assert from 'node:assert/strict';
import { test } from 'node:test';

import { type ClientEvent, startReporting } from '../src/lib/clientErrors.ts';
import { lazyScreen } from '../src/lib/lazyScreen.ts';

function reported(): Omit<ClientEvent, 'route'>[] {
  const events: Omit<ClientEvent, 'route'>[] = [];
  startReporting({ report: (event) => events.push(event), flush: () => {} });
  return events;
}

test('a screen that fails to download is reported, then shown as failed', async () => {
  const events = reported();
  const failure = new TypeError('Failed to fetch dynamically imported module');
  const load = lazyScreen(() => Promise.reject(failure));
  await assert.rejects(load(), failure);
  assert.deepEqual(
    events.map((event) => [event.kind, event.message]),
    [['error', 'TypeError: Failed to fetch dynamically imported module']],
  );
});

test('a screen that arrives is the route’s component, and nothing is said', async () => {
  const events = reported();
  const Screen = () => null;
  assert.deepEqual(await lazyScreen(async () => ({ default: Screen }))(), {
    Component: Screen,
  });
  assert.deepEqual(events, []);
});
