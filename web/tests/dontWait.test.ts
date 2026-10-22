import assert from 'node:assert/strict';
import { test } from 'node:test';

import { dontWait } from '../src/lib/dontWait.ts';

const open = { status: 'open', helpers_seeing: 4 } as const;

test('the catalog is asked for the request’s own service and subject, three at most, never the author', () => {
  assert.deepEqual(dontWait({ ...open, service_type_id: 4, subject_id: 12 }), {
    service_type_id: 4,
    subject_id: 12,
    exclude_self: true,
    limit: 3,
  });
});

test('without a subject the service alone is enough', () => {
  assert.deepEqual(dontWait({ ...open, service_type_id: 4, subject_id: null }), {
    service_type_id: 4,
    exclude_self: true,
    limit: 3,
  });
});

test('without a service the subject alone is enough, as the server counts it', () => {
  assert.deepEqual(dontWait({ ...open, service_type_id: null, subject_id: 12 }), {
    subject_id: 12,
    exclude_self: true,
    limit: 3,
  });
});

test('a request that names neither gets no suggestions: any helper would do, which is none in particular', () => {
  assert.equal(dontWait({ ...open, service_type_id: null, subject_id: null }), null);
});

test('nobody to suggest when the server says nobody sees it', () => {
  assert.equal(
    dontWait({ ...open, helpers_seeing: 0, service_type_id: 4, subject_id: 12 }),
    null,
  );
});

test('a closed request is not waiting for anyone', () => {
  const ids = { helpers_seeing: 4, service_type_id: 4, subject_id: 12 };
  assert.equal(dontWait({ ...ids, status: 'closed' }), null);
  assert.equal(dontWait({ ...ids, status: 'expired' }), null);
});
