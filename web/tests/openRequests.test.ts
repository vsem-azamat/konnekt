import assert from 'node:assert/strict';
import { test } from 'node:test';

import { openRequests } from '../src/lib/openRequests.ts';
import type { HelpRequest, RequestStatus } from '../src/lib/types.ts';

function request(status: RequestStatus, responses_count = 0): HelpRequest {
  return {
    id: 1,
    text: 'нужен репетитор',
    subject: null,
    institution: null,
    service_type: null,
    deadline_on: null,
    status,
    responses_count,
    responders: [],
    created_at: '2026-10-22T10:00:00Z',
    expires_at: null,
    closed_at: null,
    helpers_seeing: 0,
  };
}

test('the open requests are counted, with the answers they have', () => {
  assert.deepEqual(openRequests([request('open', 2), request('open', 0)]), {
    requests: 2,
    responses: 2,
  });
});

test('closed, expired and draft requests are not waiting for anyone', () => {
  assert.deepEqual(
    openRequests([request('closed', 3), request('expired', 1), request('draft')]),
    { requests: 0, responses: 0 },
  );
});

test('none at all is nothing open', () => {
  assert.deepEqual(openRequests([]), { requests: 0, responses: 0 });
});
