import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  attention,
  ConsoleError,
  clickRate,
  consoleRequester,
  daysSince,
  isFinal,
  utc,
} from '../src/console/session.ts';

type Call = { url: string; method: string; body?: string };

/** A fetch that answers from a script, and remembers what it was asked. */
function scripted(answers: Record<string, number[]>) {
  const calls: Call[] = [];
  const fetcher = async (url: string, init: RequestInit = {}) => {
    calls.push({ url, method: init.method ?? 'GET', body: init.body as string });
    const status = answers[url]?.shift() ?? 500;
    return new Response(status === 204 ? null : JSON.stringify({ url }), { status });
  };
  return { calls, fetcher: fetcher as typeof fetch };
}

test('a request without a session signs in with initData, then goes through', async () => {
  const { calls, fetcher } = scripted({
    '/api/stats/home': [401, 200],
    '/api/auth/webapp': [200],
  });
  const get = consoleRequester(fetcher, () => 'user=1&hash=x');

  assert.deepEqual(await get('/api/stats/home'), { url: '/api/stats/home' });
  assert.deepEqual(
    calls.map((c) => `${c.method} ${c.url}`),
    ['GET /api/stats/home', 'POST /api/auth/webapp', 'GET /api/stats/home'],
  );
  assert.deepEqual(JSON.parse(calls[1]?.body ?? '{}'), { init_data: 'user=1&hash=x' });
});

test('a refused sign-in is the answer, not a loop', async () => {
  const { calls, fetcher } = scripted({
    '/api/stats/home': [401],
    '/api/auth/webapp': [403],
  });
  const get = consoleRequester(fetcher, () => 'user=2&hash=x');

  await assert.rejects(get('/api/stats/home'), (error: unknown) => {
    assert.ok(error instanceof ConsoleError);
    assert.equal(error.status, 403);
    assert.equal(error.reason, 'refused');
    return true;
  });
  assert.equal(calls.length, 2);
});

test('an initData too old to sign in with says so, apart from any other failure', async () => {
  const { fetcher } = scripted({
    '/api/stats/home': [401],
    '/api/auth/webapp': [401],
  });
  const get = consoleRequester(fetcher, () => 'user=2&auth_date=1&hash=x');

  await assert.rejects(get('/api/stats/home'), (error: unknown) => {
    assert.ok(error instanceof ConsoleError);
    assert.equal(error.reason, 'stale');
    return true;
  });
});

test('a session that is not kept is its own outcome, and signs in once', async () => {
  // Signed in, and the cookie did not stick: the retry meets the same 401.
  const { calls, fetcher } = scripted({
    '/api/stats/home': [401, 401],
    '/api/chats': [401],
    '/api/auth/webapp': [200],
  });
  const get = consoleRequester(fetcher, () => 'user=1&hash=x');

  await assert.rejects(get('/api/stats/home'), (error: unknown) => {
    assert.ok(error instanceof ConsoleError);
    assert.equal(error.reason, 'not-kept');
    return true;
  });
  assert.equal(calls.filter((c) => c.url === '/api/auth/webapp').length, 1);

  // And the next request does not open another session that would not stick.
  await assert.rejects(get('/api/chats'), (error: unknown) => {
    assert.ok(error instanceof ConsoleError);
    assert.equal(error.reason, 'not-kept');
    return true;
  });
  assert.equal(calls.filter((c) => c.url === '/api/auth/webapp').length, 1);
});

test('a failure that is none of those may be tried again', async () => {
  const { fetcher } = scripted({ '/api/stats/home': [502] });
  const get = consoleRequester(fetcher, () => 'user=1&hash=x');

  await assert.rejects(get('/api/stats/home'), (error: unknown) => {
    assert.ok(error instanceof ConsoleError);
    assert.equal(error.reason, 'failed');
    assert.equal(isFinal(error), false);
    return true;
  });
  assert.equal(isFinal(new ConsoleError(403, 'refused')), true);
  // A request the server understood and refused (404, 422) is not a hiccup.
  assert.equal(isFinal(new ConsoleError(404)), true);
  assert.equal(isFinal(new ConsoleError(502)), false);
  assert.equal(isFinal(new ConsoleError(500)), false);
});

test('without initData there is nothing to sign in with', async () => {
  const { calls, fetcher } = scripted({ '/api/stats/home': [401] });
  const get = consoleRequester(fetcher, () => undefined);

  await assert.rejects(get('/api/stats/home'), (error: unknown) => {
    assert.ok(error instanceof ConsoleError);
    assert.equal(error.reason, 'stale');
    return true;
  });
  assert.equal(calls.length, 1);
});

test('requests that meet a missing session together sign in once', async () => {
  const { calls, fetcher } = scripted({
    '/api/stats/home': [401, 200],
    '/api/chats': [401, 200],
    '/api/auth/webapp': [200],
  });
  const get = consoleRequester(fetcher, () => 'user=1&hash=x');

  await Promise.all([get('/api/stats/home'), get('/api/chats')]);
  assert.equal(calls.filter((c) => c.url === '/api/auth/webapp').length, 1);
});

test('what needs attention is what has a number above zero', () => {
  const items = attention({
    adsToday: 7,
    chats: [
      { resource_status: 'discovered' },
      { resource_status: 'approved' },
      { resource_status: 'discovered' },
    ],
    profilesWeek: 0,
  });
  assert.deepEqual(items, [
    { key: 'ads', count: 7 },
    { key: 'review', count: 2 },
  ]);
});

test('the click rate is a percentage with one decimal, and nothing without views', () => {
  assert.equal(clickRate(1204, 38), '3,2 %');
  assert.equal(clickRate(311, 19), '6,1 %');
  assert.equal(clickRate(0, 0), null);
});

test('days since counts whole days, today being zero', () => {
  const now = new Date('2026-09-30T12:00:00Z');
  assert.equal(daysSince('2026-09-30T01:00:00Z', now), 0);
  assert.equal(daysSince('2026-09-27T13:00:00Z', now), 2);
});

test('webapi times without a zone are read as UTC, the zone they were written in', () => {
  assert.equal(utc('2026-09-30T15:40:00'), '2026-09-30T15:40:00Z');
  assert.equal(utc('2026-09-30T15:40:00.123456'), '2026-09-30T15:40:00.123456Z');
  assert.equal(utc('2026-09-30T15:40:00+02:00'), '2026-09-30T15:40:00+02:00');
  assert.equal(utc('2026-09-30T15:40:00Z'), '2026-09-30T15:40:00Z');
});

test("a refusal carries webapi's code for it, and none when the detail is not one", async () => {
  const answers = [
    new Response(JSON.stringify({ detail: 'already_known' }), { status: 409 }),
    new Response(JSON.stringify({ detail: [{ msg: 'field required' }] }), {
      status: 422,
    }),
    new Response('<html>502</html>', { status: 502 }),
  ];
  const fetcher = (async () => answers.shift() as Response) as typeof fetch;
  const get = consoleRequester(fetcher, () => 'user=1&hash=x');

  const details: (string | null)[] = [];
  for (let n = 0; n < 3; n++) {
    await assert.rejects(get('/api/chats/external'), (error: unknown) => {
      assert.ok(error instanceof ConsoleError);
      details.push(error.detail);
      return true;
    });
  }
  assert.deepEqual(details, ['already_known', null, null]);
});
