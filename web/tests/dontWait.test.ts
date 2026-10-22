import assert from 'node:assert/strict';
import { test } from 'node:test';

import { dontWait } from '../src/lib/dontWait.ts';

test('the catalog is asked for the request’s own service and subject, three at most, never the author', () => {
  assert.deepEqual(dontWait({ status: 'open', service_type_id: 4, subject_id: 12 }), {
    service_type_id: 4,
    subject_id: 12,
    exclude_self: true,
    limit: 3,
  });
});

test('without a subject the service alone is enough', () => {
  assert.deepEqual(dontWait({ status: 'open', service_type_id: 4, subject_id: null }), {
    service_type_id: 4,
    exclude_self: true,
    limit: 3,
  });
});

test('a request that names no service gets no suggestions: any helper would do, which is none in particular', () => {
  assert.equal(dontWait({ status: 'open', service_type_id: null, subject_id: 12 }), null);
});

test('a closed request is not waiting for anyone', () => {
  assert.equal(dontWait({ status: 'closed', service_type_id: 4, subject_id: 12 }), null);
  assert.equal(dontWait({ status: 'expired', service_type_id: 4, subject_id: 12 }), null);
});
