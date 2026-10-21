import assert from 'node:assert/strict';
import { mock, test } from 'node:test';

import {
  type ClientEvent,
  createReporter,
  describeError,
  endpointOf,
  FLUSH_MS,
  isFailure,
  layoutLooksBroken,
  PER_SESSION,
  scrub,
} from '../src/lib/clientErrors.ts';

function setup() {
  mock.timers.enable({ apis: ['setTimeout'] });
  const sent: ClientEvent[][] = [];
  const reporter = createReporter({
    send: (events) => sent.push(events),
    route: () => '/chats/:group',
  });
  return { reporter, sent };
}

test('events wait a moment and go out together', (t) => {
  t.after(() => mock.timers.reset());
  const { reporter, sent } = setup();
  reporter.report({ kind: 'error', message: 'one' });
  reporter.report({ kind: 'api', endpoint: '/api/v1/me', status: 502 });
  assert.equal(sent.length, 0);
  mock.timers.tick(FLUSH_MS);
  assert.equal(sent.length, 1);
  assert.deepEqual(
    sent[0]?.map((event) => [event.kind, event.route]),
    [
      ['error', '/chats/:group'],
      ['api', '/chats/:group'],
    ],
  );
});

test('leaving the app sends what is waiting at once', (t) => {
  t.after(() => mock.timers.reset());
  const { reporter, sent } = setup();
  reporter.report({ kind: 'error', message: 'one' });
  reporter.flush();
  assert.equal(sent.length, 1);
  mock.timers.tick(FLUSH_MS);
  assert.equal(sent.length, 1);
});

test('the same failure in a loop is one event', (t) => {
  t.after(() => mock.timers.reset());
  const { reporter, sent } = setup();
  for (let i = 0; i < 50; i += 1) reporter.report({ kind: 'error', message: 'loop' });
  mock.timers.tick(FLUSH_MS);
  assert.equal(sent.flat().length, 1);
});

test('a session reports a bounded number of events', (t) => {
  t.after(() => mock.timers.reset());
  const { reporter, sent } = setup();
  for (let i = 0; i < PER_SESSION + 10; i += 1) {
    reporter.report({ kind: 'error', message: `different ${i}` });
  }
  mock.timers.tick(FLUSH_MS);
  assert.equal(sent.flat().length, PER_SESSION);
  assert.ok(sent.every((batch) => batch.length <= 10));
});

test('a report that fails to send is not reported', (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ['setTimeout'] });
  const reporter = createReporter({
    send: () => {
      throw new Error('offline');
    },
    route: () => '/',
  });
  reporter.report({ kind: 'error', message: 'x' });
  assert.doesNotThrow(() => mock.timers.tick(FLUSH_MS));
});

test('an endpoint is named by its pattern, without ids or a query', () => {
  assert.equal(
    endpointOf('/api/v1/helpers/123/contact?x=1'),
    '/api/v1/helpers/:id/contact',
  );
  assert.equal(endpointOf('/api/public/catalog'), '/api/public/catalog');
  assert.equal(endpointOf('/api/v1/requests/9f8e7d6c-1a2b'), '/api/v1/requests/:id');
  assert.equal(endpointOf('https://app.example/api/v1/me#frag'), '/api/v1/me');
});

test('a message loses addresses tails and long numbers, and is cut short', () => {
  assert.equal(
    scrub('at https://app.example/#tgWebAppData=user%3D42 for 123456789'),
    'at https://app.example/ for …',
  );
  assert.equal(scrub('x'.repeat(900), 500).length, 500);
});

test('an error is described by its name and message; anything else as text', () => {
  assert.deepEqual(
    describeError(new TypeError('x is undefined')).message,
    'TypeError: x is undefined',
  );
  assert.equal(describeError('plain').message, 'plain');
  assert.equal(describeError({ odd: true }).message, '[object Object]');
});

test('an aborted request is not a failure', () => {
  const abort = new DOMException('The operation was aborted.', 'AbortError');
  assert.equal(describeError(abort).ignore, true);
});

// The bug that started this: minimised and expanded again on Android, the app
// stayed the height of the bottom bar and showed a heading and nothing else.
test('an app far shorter than its window looks broken; a keyboard does not', () => {
  assert.equal(layoutLooksBroken(96, 800), true);
  assert.equal(layoutLooksBroken(800, 800), false);
  assert.equal(layoutLooksBroken(450, 800), false);
  assert.equal(layoutLooksBroken(0, 0), false);
});

test('a call that broke is a failure; the API saying no is not', () => {
  for (const status of [0, 401, 500, 502, 503]) assert.equal(isFailure(status), true);
  for (const status of [400, 403, 404, 409, 422]) assert.equal(isFailure(status), false);
});
