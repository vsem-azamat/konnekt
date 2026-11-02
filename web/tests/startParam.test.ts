import assert from 'node:assert/strict';
import { test } from 'node:test';

import { startRoute } from '../src/lib/startParam.ts';

test('a link that names the offer screen opens it, saying it came from a link', () => {
  assert.deepEqual(startRoute('offer'), { path: '/offer', state: { from: 'link' } });
});

test('a start parameter that only says where somebody came from opens nothing', () => {
  // `welcome` is what the chat greeting sends today: a source for the
  // audience, not a screen.
  assert.equal(startRoute('welcome'), null);
  assert.equal(startRoute(undefined), null);
  assert.equal(startRoute(''), null);
});

test("a university's link opens its chats by its code", () => {
  assert.deepEqual(startRoute('uni-cvut'), {
    path: '/chats/cvut',
    state: { from: 'link' },
  });
});

test('a university link with anything but a plain code opens nothing', () => {
  assert.equal(startRoute('uni-'), null);
  assert.equal(startRoute('uni-../console'), null);
  assert.equal(startRoute('uni-ČVUT'), null);
});

test('a university code with an underscore is a code too', () => {
  assert.deepEqual(startRoute('uni-uk_fsv'), {
    path: '/chats/uk_fsv',
    state: { from: 'link' },
  });
});
