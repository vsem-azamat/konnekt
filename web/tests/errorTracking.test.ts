import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { ErrorEvent } from '@sentry/react';
import { scrubBreadcrumb, scrubEvent } from '../src/lib/errorTracking.ts';

const PAGE =
  'https://konnekt.cz/chats#tgWebAppData=user%3D%7B%22id%22%3A268388996%7D&tgWebAppVersion=8';

test('the page address loses its fragment everywhere, frames included', () => {
  const event = scrubEvent({
    type: undefined,
    request: { url: PAGE },
    exception: {
      values: [
        {
          type: 'TypeError',
          value: `failed at ${PAGE}`,
          stacktrace: { frames: [{ filename: PAGE, lineno: 1, colno: 123456 }] },
        },
      ],
    },
  } as ErrorEvent);

  const text = JSON.stringify(event);
  assert.ok(!text.includes('tgWebAppData'));
  assert.ok(!text.includes('268388996'));
  assert.equal(event.exception?.values?.[0]?.stacktrace?.frames?.[0]?.colno, 123456);
});

test('a bundle file name is kept as it is, for the source map', () => {
  const file = 'https://konnekt.cz/assets/index-B123456x.js';
  const event = scrubEvent({
    type: undefined,
    exception: { values: [{ stacktrace: { frames: [{ filename: file }] } }] },
  } as ErrorEvent);

  assert.equal(event.exception?.values?.[0]?.stacktrace?.frames?.[0]?.filename, file);
});

test('a breadcrumb of an API call keeps its path and loses its query', () => {
  const crumb = scrubBreadcrumb({
    category: 'fetch',
    data: { url: 'https://konnekt.cz/api/v1/helpers?tg_id=268388996', status_code: 500 },
  });

  assert.deepEqual(crumb.data, {
    url: 'https://konnekt.cz/api/v1/helpers',
    status_code: 500,
  });
});

test("the event's own ids are kept, a commit with a run of digits included", () => {
  const ids = {
    release: '0064152123456aa7711d0000000000000000abcd',
    event_id: '1234567890abcdef1234567890abcdef',
  };
  const event = scrubEvent({ type: undefined, ...ids } as ErrorEvent);

  assert.equal(event.release, ids.release);
  assert.equal(event.event_id, ids.event_id);
});
