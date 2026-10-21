import assert from 'node:assert/strict';
import { test } from 'node:test';

import { offerChipText } from '../src/lib/offerChip.ts';

test('an offer with a subject reads subject and university', () => {
  assert.equal(
    offerChipText({
      subject: 'Matematika',
      institution: 'ČVUT',
      service_type_name: 'Doučování',
    }),
    'Matematika · ČVUT',
  );
});

test('an offer without a subject keeps the service in front of the university', () => {
  assert.equal(
    offerChipText({
      subject: null,
      institution: 'ČVUT',
      service_type_name: 'Помощь на экзамене',
    }),
    'Помощь на экзамене · ČVUT',
  );
});

test('an offer with neither is the service alone', () => {
  assert.equal(
    offerChipText({ subject: null, institution: null, service_type_name: 'Doučování' }),
    'Doučování',
  );
});

test('an offer with a subject and no university is the subject alone', () => {
  assert.equal(
    offerChipText({
      subject: 'Fyzika',
      institution: null,
      service_type_name: 'Doučování',
    }),
    'Fyzika',
  );
});
