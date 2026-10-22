import assert from 'node:assert/strict';
import { test } from 'node:test';

import { requestName, requestQuote } from '../src/lib/requestHeading.ts';

test('a subject and an institution make the name', () => {
  assert.equal(
    requestName({ subject: 'Математический анализ', institution: 'ČVUT' }),
    'Математический анализ, ČVUT',
  );
});

test('either one alone is the name', () => {
  assert.equal(requestName({ subject: 'Физика', institution: null }), 'Физика');
  assert.equal(requestName({ subject: null, institution: 'ČVUT' }), 'ČVUT');
});

test('a request with neither has no name, so its text is not repeated under one', () => {
  assert.equal(requestName({ subject: null, institution: null }), null);
  assert.equal(requestName({ subject: '', institution: '' }), null);
});

test('the quote in the answer sheet names the request before its words', () => {
  assert.equal(
    requestQuote({
      subject: 'Линейная алгебра',
      institution: 'ČVUT',
      text: 'Не понимаю собственные значения.',
    }),
    'Линейная алгебра, ČVUT. Не понимаю собственные значения.',
  );
});

test('a request without a name is quoted as written', () => {
  assert.equal(
    requestQuote({ subject: null, institution: null, text: 'Нужен переводчик' }),
    'Нужен переводчик',
  );
});
