import assert from 'node:assert/strict';
import { test } from 'node:test';

import { catalogThroughConsole } from '../src/console/catalogDoor.ts';

test('in a browser webapi is asked, under its session, in the console language', () => {
  assert.deepEqual(catalogThroughConsole('/admin/profiles/7/hide', '', 'cs'), {
    url: '/api/catalog/admin/profiles/7/hide?lang=cs',
    initData: false,
  });
  assert.deepEqual(catalogThroughConsole('/admin/catalog', '?a=b', 'en'), {
    url: '/api/catalog/admin/catalog?a=b&lang=en',
    initData: false,
  });
  // No language yet: webapi and the catalog fall back on their own.
  assert.deepEqual(catalogThroughConsole('/admin/partners', ''), {
    url: '/api/catalog/admin/partners',
    initData: false,
  });
});

test('a language the console does not speak is not sent', () => {
  assert.equal(
    catalogThroughConsole('/admin/partners', '', 'de').url,
    '/api/catalog/admin/partners',
  );
});
