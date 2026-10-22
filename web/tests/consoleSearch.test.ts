import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  foundList,
  personTarget,
  type SearchPerson,
  searchPath,
  searchText,
} from '../src/console/search.ts';

function person(user_id: number, over: Partial<SearchPerson> = {}): SearchPerson {
  return {
    user_id,
    username: null,
    first_name: null,
    last_name: null,
    in_audience: false,
    blocked: false,
    ...over,
  };
}

test('nothing but spaces or an @ is not a search', () => {
  assert.equal(searchText('   '), null);
  assert.equal(searchText(' @ '), null);
  assert.equal(searchText(' @anna '), '@anna');
  assert.equal(searchPath('100% flood'), '/api/search?q=100%25+flood');
});

test('a person opens their card, else the blacklist, else nothing', () => {
  assert.equal(
    personTarget(person(1, { in_audience: true, blocked: true })),
    '/console/audience/1',
  );
  assert.equal(personTarget(person(2, { blocked: true })), '/console/blacklist');
  assert.equal(personTarget(person(3)), null);
});

test('chats come first, then people, each with where it opens', () => {
  const list = foundList({
    chats: [{ id: -5, title: 'Matfyz', resource_status: 'approved', public_link: null }],
    people: [person(3), person(1, { in_audience: true })],
  });
  assert.deepEqual(
    list.map((found) => found.to),
    ['/console/chats/-5', null, '/console/audience/1'],
  );
});
