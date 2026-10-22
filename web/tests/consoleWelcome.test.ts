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

test('a raw «<…>» that is not a Telegram tag stays in the text', () => {
  assert.equal(welcomePlain('Пишите <имя> в анкете'), 'Пишите <имя> в анкете');
  assert.equal(welcomePlain('Q&A <3 и -> туда'), 'Q&A <3 и -> туда');
  assert.equal(hasFormatting('Пишите <имя> в анкете'), false);
  assert.equal(
    welcomeChange('Пишите <имя> в анкете', 'Пишите <имя> в анкете'),
    'Пишите &lt;имя&gt; в анкете',
  );
});

test('quotes and numeric entities read as characters and are not resaved', () => {
  const html = 'Читайте &quot;Правила&quot; &#33; &#x1F44B;';
  assert.equal(welcomePlain(html), 'Читайте "Правила" ! 👋');
  assert.equal(welcomeChange(html, welcomePlain(html)), null);
  assert.equal(welcomePlain('&#99999999;'), '&#99999999;');
});

test('formatted text with a bare ampersand is repaired, losing its tags', () => {
  assert.equal(welcomeChange('<b>Q&A</b>', 'Q&A'), 'Q&amp;A');
});

test('spaces around the stored text do not count as an edit', () => {
  assert.equal(welcomeChange('  Правила тут\n', 'Правила тут'), null);
});
