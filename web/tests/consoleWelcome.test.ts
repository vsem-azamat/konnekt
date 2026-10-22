import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  hasFormatting,
  welcomeChange,
  welcomeHtml,
  welcomePlain,
} from '../src/console/welcome.ts';

test('typed text is escaped for Telegram, and reads back as typed', () => {
  const typed = 'Q&A в теме #вопросы <3 и -> туда';
  assert.equal(welcomeHtml(typed), 'Q&amp;A в теме #вопросы &lt;3 и -&gt; туда');
  assert.equal(welcomePlain(welcomeHtml(typed)), typed);
});

test('text written by !welcome reads without its tags', () => {
  const html = '<b>Правила</b> — <a href="https://t.me/x">тут</a> &amp; там';
  assert.equal(welcomePlain(html), 'Правила — тут & там');
  assert.equal(hasFormatting(html), true);
  assert.equal(hasFormatting('Правила &amp; там'), false);
});

test('an entity is decoded once, so an escaped ampersand stays as typed', () => {
  assert.equal(welcomePlain('&amp;lt;'), '&lt;');
  assert.equal(welcomePlain(null), '');
});

test('untouched text is not saved, and formatting from !welcome survives', () => {
  assert.equal(welcomeChange('Q&amp;A', 'Q&A'), null);
  assert.equal(welcomeChange('<b>Правила</b> тут', 'Правила тут'), null);
  assert.equal(welcomeChange(null, ''), null);
});

test('untouched text an older console stored raw is repaired', () => {
  assert.equal(welcomeChange('Q&A <3', 'Q&A <3'), 'Q&amp;A &lt;3');
});

test('an edit stores the typed text escaped, and clearing stores nothing', () => {
  assert.equal(welcomeChange('<b>Правила</b> тут', 'Правила там'), 'Правила там');
  assert.equal(welcomeChange('Правила', ''), '');
});
