import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  type ChatTab,
  catalogPlace,
  chatGuards,
  consoleSections,
  isListed,
  joinsDirectly,
  listedCount,
  tabCounts,
  tabOf,
} from '../src/console/chats.ts';
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
    city: null,
    topic: null,
    join_mode: 'admins',
    join_by_request: null,
    is_welcome_enabled: false,
    is_service_cleanup_enabled: false,
    bot_absent_at: null,
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
  assert.deepEqual(titles(consoleSections(CHATS, '')), [
    ['review', null, [3, 4]],
    ['group', 'ČVUT | ЧВУТ', [1, 2, 6]],
    ['rest', null, [5]],
  ]);
});

test('a filter keeps only what it lets through, still grouped', () => {
  const only = (status: string) => (each: ConsoleChat) => each.resource_status === status;
  assert.deepEqual(titles(consoleSections(CHATS, '', only('approved'))), [
    ['group', 'ČVUT | ЧВУТ', [1, 2, 6]],
  ]);
  assert.deepEqual(titles(consoleSections(CHATS, '', only('discovered'))), [
    ['review', null, [3, 4]],
  ]);
});

test('search finds a title without its diacritics, and an id', () => {
  assert.deepEqual(titles(consoleSections(CHATS, 'cvut fit')), [
    ['group', 'ČVUT | ЧВУТ', [2]],
  ]);
  assert.deepEqual(titles(consoleSections(CHATS, '5')), [['rest', null, [5]]]);
});

test('a chat whose parent is not listed goes with the rest', () => {
  const orphans = [chat(7, 'MUNI Law', { parent_chat_id: 99 })];
  assert.deepEqual(titles(consoleSections(orphans, '')), [['rest', null, [7]]]);
});

test('the parent leads its section, wherever it came in the list', () => {
  const late = [chat(2, 'ČVUT FIT', { parent_chat_id: 1 }), chat(1, 'ČVUT | ЧВУТ')];
  const [section] = consoleSections(late, '');
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
  const roots = consoleSections(twins, '').map((s) =>
    s.key === 'group' ? s.root : null,
  );
  assert.deepEqual(roots, [1, 3]);
});

test('digits find a title with them as well as an id', () => {
  const named = [chat(-100777, 'ČVUT 2025'), chat(-100555, 'Flood')];
  assert.deepEqual(titles(consoleSections(named, '2025')), [['rest', null, [-100777]]]);
  assert.deepEqual(titles(consoleSections(named, '555')), [['rest', null, [-100555]]]);
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

test('only a public chat that does not approve new members lets people straight in', () => {
  const direct = (public_link: string | null, join_by_request: boolean | null) =>
    joinsDirectly({ public_link, join_by_request });
  assert.equal(direct('https://t.me/karlov_chat', false), true);
  assert.equal(direct('https://t.me/karlov_chat', true), false);
  // Not asked yet: the mode stands.
  assert.equal(direct('https://t.me/karlov_chat', null), false);
  // The bot's invite link makes the chat private: requests come from the link.
  assert.equal(direct('https://t.me/+AbCdEf123', false), false);
  assert.equal(direct('https://t.me/joinchat/AbCdEf123', false), false);
  assert.equal(direct('https://t.me/+AbCdEf123/', false), false);
  assert.equal(direct(null, false), false);
});

test('only an approved chat has guards, and a captcha nobody meets is not one', () => {
  assert.equal(chatGuards(chat(1, 'A', { resource_status: 'discovered' })), null);
  assert.deepEqual(chatGuards(chat(1, 'A')), []);
  assert.deepEqual(
    chatGuards(chat(1, 'A', { join_mode: 'captcha', is_welcome_enabled: true })),
    ['captcha', 'welcome'],
  );
  assert.deepEqual(
    chatGuards(
      chat(1, 'A', {
        join_mode: 'captcha',
        public_link: 'https://t.me/karlov_chat',
        join_by_request: false,
      }),
    ),
    [],
  );
});

test('a chat says why students do or do not see it', () => {
  const linked = { public_link: 'https://t.me/x' };
  assert.equal(catalogPlace(chat(1, 'A', linked)), 'listed');
  assert.equal(
    catalogPlace(chat(1, 'A', { resource_status: 'external', ...linked })),
    'listed',
  );
  assert.equal(catalogPlace(chat(1, 'A')), 'no_link');
  assert.equal(catalogPlace(chat(1, '', linked)), 'no_title');
  assert.equal(
    catalogPlace(chat(1, 'A', { resource_status: 'discovered', ...linked })),
    'undecided',
  );
  assert.equal(
    catalogPlace(chat(1, 'A', { resource_status: 'disabled', ...linked })),
    'off',
  );
});

test('the count students see agrees with the listing rule', () => {
  const linked = { public_link: 'https://t.me/x' };
  const chats = [
    chat(1, 'A', linked),
    chat(2, 'B'),
    chat(3, 'C', { resource_status: 'observed', ...linked }),
    chat(4, 'D', { resource_status: 'disabled', ...linked }),
  ];
  assert.equal(listedCount(chats), 2);
  for (const each of chats) assert.equal(isListed(each), catalogPlace(each) === 'listed');
});

test('each chat sits in the one tab that answers a question about it', () => {
  const linked = { public_link: 'https://t.me/x' };
  const tab = (over: Partial<ConsoleChat>): ChatTab => tabOf(chat(1, 'A', over));
  assert.equal(tab({ resource_status: 'discovered' }), 'decide');
  assert.equal(tab({ ...linked }), 'listed');
  assert.equal(tab({ resource_status: 'external', ...linked }), 'listed');
  // Decided on, but students do not see it: the test chat without a link.
  assert.equal(tab({}), 'hidden');
  assert.equal(tab({ resource_status: 'disabled', ...linked }), 'off');
});

test('the tabs count every chat once, and all of them together', () => {
  const linked = { public_link: 'https://t.me/x' };
  const chats = [
    chat(1, 'A', linked),
    chat(2, 'B'),
    chat(3, 'C', { resource_status: 'discovered' }),
    chat(4, 'D', { resource_status: 'disabled' }),
    chat(5, 'E', { resource_status: 'observed', ...linked }),
  ];
  assert.deepEqual(tabCounts(chats), { all: 5, decide: 1, listed: 2, hidden: 1, off: 1 });
});

test('a tab keeps its chats grouped under their parents', () => {
  const linked = { public_link: 'https://t.me/x' };
  const chats = [chat(1, 'ČVUT', linked), chat(2, 'ČVUT FIT', { parent_chat_id: 1 })];
  assert.deepEqual(
    titles(consoleSections(chats, '', (each) => tabOf(each) === 'hidden')),
    [['group', 'ČVUT', [2]]],
  );
});
