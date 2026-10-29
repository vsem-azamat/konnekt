import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  chatLetters,
  personLetters,
  personTone,
  profileLink,
} from '../src/console/faces.ts';

const person = (fields: Partial<Parameters<typeof personLetters>[0]>) => ({
  user_id: 1,
  first_name: null,
  last_name: null,
  username: null,
  ...fields,
});

test('a person is their first and last initials', () => {
  assert.equal(
    personLetters(person({ first_name: 'Дарина', last_name: 'Коваленко' })),
    'ДК',
  );
  assert.equal(personLetters(person({ first_name: 'anna' })), 'A');
});

test('a person without a name is their handle, then a sign', () => {
  assert.equal(personLetters(person({ username: 'ritik160' })), 'R');
  assert.equal(personLetters(person({})), '#');
});

test('the same person keeps one tone, a negative id included', () => {
  assert.equal(personTone(7), personTone(7));
  assert.ok(personTone(-1001) >= 0 && personTone(-1001) < 6);
});

test('a chat without a title is lettered by its id', () => {
  assert.equal(chatLetters({ id: -1001, title: 'Masarykova univerzita' }), 'MU');
  assert.ok(chatLetters({ id: -1001, title: null }).length > 0);
});

test('only a @username has a profile link a browser opens', () => {
  assert.equal(profileLink({ username: 'darina_k' }), 'https://t.me/darina_k');
  assert.equal(profileLink({ username: null }), null);
});
