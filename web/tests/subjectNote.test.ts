import assert from 'node:assert/strict';
import { test } from 'node:test';

import { splitNote } from '../src/lib/subjectNote.ts';

test('a name with a note in brackets keeps the name in front', () => {
  assert.deepEqual(splitNote('Чешский язык B2 (для вуза и нострификации)'), {
    name: 'Чешский язык B2',
    note: 'для вуза и нострификации',
  });
});

test('a name without one is all name', () => {
  assert.deepEqual(splitNote('Математический анализ'), {
    name: 'Математический анализ',
    note: null,
  });
});

test('brackets inside the name are not a note', () => {
  assert.deepEqual(splitNote('C (язык) для начинающих'), {
    name: 'C (язык) для начинающих',
    note: null,
  });
});

test('a name that is only brackets stays as it is', () => {
  assert.deepEqual(splitNote('(без названия)'), { name: '(без названия)', note: null });
});
