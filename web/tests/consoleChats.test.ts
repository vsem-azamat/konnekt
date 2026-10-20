import assert from 'node:assert/strict';
import { test } from 'node:test';

import { consoleSections, isListed, statusCounts } from '../src/console/chats.ts';
import type { ConsoleChat } from '../src/console/session.ts';

function chat(id: number, title: string, over: Partial<ConsoleChat> = {}): ConsoleChat {
  return {
    id,
    title,
    resource_status: 'approved',
    member_count: null,
    public_link: null,
    parent_chat_id: null,
    institution_code: null,
    is_captcha_enabled: false,
    is_welcome_enabled: false,
    is_service_cleanup_enabled: false,
    ...over,
  };
}

const CHATS = [
  chat(1, 'ČVUT | ЧВУТ'),
  chat(2, 'ČVUT FIT', { parent_chat_id: 1 }),
  chat(3, 'VŠE FIS 2026', { resource_status: 'discovered' }),
  chat(4, 'Strahov blok 7', { resource_status: 'discovered', parent_chat_id: 1 }),
  chat(5, 'Flood', { resource_status: 'disabled' }),
  chat(6, 'ČVUT FS', { parent_chat_id: 1 }),
];

const titles = (sections: ReturnType<typeof consoleSections>) =>
  sections.map((section) => [section.key, section.title, section.chats.map((c) => c.id)]);

test('chats awaiting review come first, then one section per parent, then the rest', () => {
  assert.deepEqual(titles(consoleSections(CHATS, 'all', '')), [
    ['review', null, [3, 4]],
    ['group', 'ČVUT | ЧВУТ', [1, 2, 6]],
    ['rest', null, [5]],
  ]);
});

test('a status filter keeps only that status, still grouped', () => {
  assert.deepEqual(titles(consoleSections(CHATS, 'approved', '')), [
    ['group', 'ČVUT | ЧВУТ', [1, 2, 6]],
  ]);
  assert.deepEqual(titles(consoleSections(CHATS, 'discovered', '')), [
    ['review', null, [3, 4]],
  ]);
});

test('search finds a title without its diacritics, and an id', () => {
  assert.deepEqual(titles(consoleSections(CHATS, 'all', 'cvut fit')), [
    ['group', 'ČVUT | ЧВУТ', [2]],
  ]);
  assert.deepEqual(titles(consoleSections(CHATS, 'all', '5')), [['rest', null, [5]]]);
});

test('a chat whose parent is not listed goes with the rest', () => {
  const orphans = [chat(7, 'MUNI Law', { parent_chat_id: 99 })];
  assert.deepEqual(titles(consoleSections(orphans, 'all', '')), [['rest', null, [7]]]);
});

test('the parent leads its section, wherever it came in the list', () => {
  const late = [chat(2, 'ČVUT FIT', { parent_chat_id: 1 }), chat(1, 'ČVUT | ЧВУТ')];
  const [section] = consoleSections(late, 'all', '');
  assert.deepEqual(
    section?.chats.map((c) => c.id),
    [1, 2],
  );
  assert.equal(section?.key === 'group' ? section.root : null, 1);
});

test('two parents with the same title are two sections', () => {
  const twins = [
    chat(1, 'Общий'),
    chat(2, 'A', { parent_chat_id: 1 }),
    chat(3, 'Общий'),
    chat(4, 'B', { parent_chat_id: 3 }),
  ];
  const roots = consoleSections(twins, 'all', '').map((s) =>
    s.key === 'group' ? s.root : null,
  );
  assert.deepEqual(roots, [1, 3]);
});

test('digits find a title with them as well as an id', () => {
  const named = [chat(-100777, 'ČVUT 2025'), chat(-100555, 'Flood')];
  assert.deepEqual(titles(consoleSections(named, 'all', '2025')), [
    ['rest', null, [-100777]],
  ]);
  assert.deepEqual(titles(consoleSections(named, 'all', '555')), [
    ['rest', null, [-100555]],
  ]);
});

test('each status is counted, and all of them together', () => {
  assert.deepEqual(statusCounts(CHATS), {
    all: 6,
    discovered: 2,
    approved: 3,
    observed: 0,
    external: 0,
    disabled: 1,
  });
});

test('a chat we observe or only list is counted under its own status', () => {
  const counts = statusCounts([
    chat(1, 'NTK', { resource_status: 'observed' }),
    chat(2, 'ČVUT FJFI', { resource_status: 'external' }),
    chat(3, 'PODOLI', { resource_status: 'external' }),
  ]);
  assert.equal(counts.observed, 1);
  assert.equal(counts.external, 2);
});

test('an observed or external chat with a link is on the public tab', () => {
  const link = 'https://t.me/x';
  for (const status of ['observed', 'external'] as const) {
    assert.equal(
      isListed(chat(1, 'A', { public_link: link, resource_status: status })),
      true,
    );
  }
  assert.equal(
    isListed(chat(1, 'A', { public_link: link, resource_status: 'disabled' })),
    false,
  );
});

test('listed is what the public tab shows: decided, titled and linked', () => {
  const link = 'https://t.me/x';
  assert.equal(isListed(chat(1, 'A', { public_link: link })), true);
  assert.equal(
    isListed(chat(1, 'A', { public_link: link, resource_status: 'discovered' })),
    false,
  );
  assert.equal(isListed(chat(1, 'A', { public_link: null })), false);
  assert.equal(isListed(chat(1, '', { public_link: link })), false);
});
