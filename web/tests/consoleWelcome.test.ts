import assert from 'node:assert/strict';
import { test } from 'node:test';

import { welcomeHtml, welcomePlain } from '../src/console/welcome.ts';

test('typed text is escaped for Telegram, and reads back as typed', () => {
  const typed = 'Q&A в теме #вопросы <3';
  assert.equal(welcomeHtml(typed), 'Q&amp;A в теме #вопросы &lt;3');
  assert.equal(welcomePlain(welcomeHtml(typed)), typed);
});

test('text written by !welcome reads without its tags', () => {
  assert.equal(
    welcomePlain('<b>Правила</b> — <a href="https://t.me/x">тут</a> &amp; там'),
    'Правила — тут & там',
  );
});

test('an entity is decoded once, so an escaped ampersand stays as typed', () => {
  assert.equal(welcomePlain('&amp;lt;'), '&lt;');
  assert.equal(welcomePlain(null), '');
});
