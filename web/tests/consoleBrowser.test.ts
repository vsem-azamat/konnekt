import assert from 'node:assert/strict';
import { test } from 'node:test';

import { isBrowserConsolePath, loginProblem } from '../src/console/browser.ts';

test('the sign-in page names a failure only when the server did', () => {
  assert.equal(loginProblem(''), null);
  assert.equal(loginProblem('?error=failed'), 'failed');
  assert.equal(loginProblem('?error=not_admin'), 'not_admin');
});

test('an error code the server never sends is not shown as a message', () => {
  // The query string is whatever somebody linked; echoing it would let a link write the page.
  assert.equal(loginProblem('?error=<b>hi</b>'), null);
  assert.equal(loginProblem('?error=denied'), null);
  assert.equal(loginProblem('?other=failed'), null);
});

test('a browser gets the console and its sign-in, and the landing page everywhere else', () => {
  assert.equal(isBrowserConsolePath('/login'), true);
  assert.equal(isBrowserConsolePath('/console'), true);
  assert.equal(isBrowserConsolePath('/console/chats/-100123'), true);
  assert.equal(isBrowserConsolePath('/'), false);
  assert.equal(isBrowserConsolePath('/chats'), false);
  assert.equal(isBrowserConsolePath('/consoles'), false);
  assert.equal(isBrowserConsolePath('/login/extra'), false);
});
