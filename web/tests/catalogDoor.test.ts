import assert from 'node:assert/strict';
import { test } from 'node:test';

import { catalogCall } from '../src/lib/catalogDoor.ts';

test('inside Telegram the catalog is asked itself, with initData', () => {
  assert.deepEqual(catalogCall('init-data', '/admin/catalog', ''), {
    url: '/api/v1/admin/catalog',
    initData: true,
  });
  assert.deepEqual(catalogCall('init-data', '/taxonomy/institutions', '?x=1', 'cs'), {
    url: '/api/v1/taxonomy/institutions?x=1',
    initData: true,
  });
});

test('in a browser webapi is asked instead, under its session, in the console language', () => {
  assert.deepEqual(catalogCall('console-session', '/admin/profiles/7/hide', '', 'cs'), {
    url: '/api/catalog/admin/profiles/7/hide?lang=cs',
    initData: false,
  });
  assert.deepEqual(catalogCall('console-session', '/admin/catalog', '?a=b', 'en'), {
    url: '/api/catalog/admin/catalog?a=b&lang=en',
    initData: false,
  });
  // No language yet: webapi and the catalog fall back on their own.
  assert.deepEqual(catalogCall('console-session', '/admin/partners', ''), {
    url: '/api/catalog/admin/partners',
    initData: false,
  });
});

test('a language the console does not speak is not sent', () => {
  assert.equal(
    catalogCall('console-session', '/admin/partners', '', 'de').url,
    '/api/catalog/admin/partners',
  );
});
