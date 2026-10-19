import assert from 'node:assert/strict';
import { test } from 'node:test';

import { pickable } from '../src/lib/institutions.ts';
import type { Institution } from '../src/lib/types.ts';

function school(
  id: number,
  code: string,
  name: string,
  short_name: string | null,
  faculties: Institution[] = [],
  city: string | null = null,
): Institution {
  return { id, code, name, short_name, city, parent_id: null, faculties };
}

// FEL's code says nothing of ČVUT, so only the university's name can.
const CVUT = school(
  1,
  'cvut',
  'České vysoké učení technické v Praze',
  'ČVUT',
  [
    school(11, 'fel', 'Fakulta elektrotechnická', 'FEL'),
    school(12, 'cvut_fit', 'Fakulta informačních technologií', 'FIT'),
    school(13, 'cvut_fs', 'Fakulta strojní', 'FS'),
    school(14, 'cvut_fsv', 'Fakulta stavební', 'FSv'),
    school(15, 'cvut_fa', 'Fakulta architektury', 'FA'),
    school(16, 'cvut_fd', 'Fakulta dopravní', 'FD'),
    school(17, 'cvut_fbmi', 'Fakulta biomedicínského inženýrství', 'FBMI'),
  ],
  'Praha',
);
const VUT = school(
  2,
  'vut',
  'Vysoké učení technické v Brně',
  'VUT',
  [
    school(21, 'vut_fel', 'Fakulta elektrotechniky a komunikačních technologií', 'FEKT'),
    school(22, 'vut_fit', 'Fakulta informačních technologií', 'FIT'),
  ],
  'Brno',
);
const UK = school(
  3,
  'uk',
  'Univerzita Karlova',
  'UK',
  [school(31, 'uk_prf', 'Právnická fakulta', 'PrF')],
  'Praha',
);
const TAXONOMY = [CVUT, VUT, UK];

function picked(query: string, taken: number[] = []) {
  return pickable(TAXONOMY, query, new Set(taken)).map(
    ({ row, under }) => `${row.short_name}${under ? `@${under}` : ''}`,
  );
}

test('a faculty is found by its name and its university together', () => {
  assert.deepEqual(picked('fel чвут'), ['FEL@ČVUT']);
  assert.deepEqual(picked('фит'), ['FIT@ČVUT', 'FIT@VUT']);
  assert.deepEqual(picked('вут фит'), ['FIT@VUT']);
});

test('a university comes before its faculties', () => {
  assert.deepEqual(picked('вут'), ['VUT', 'FEKT@VUT', 'FIT@VUT']);
});

test('what the offer already has is not offered again', () => {
  assert.deepEqual(picked('фит', [12]), ['FIT@VUT']);
});

test('a city finds its universities and their faculties, spelled right', () => {
  assert.deepEqual(picked('брно'), ['VUT', 'FEKT@VUT', 'FIT@VUT']);
  assert.deepEqual(picked('univerzita прага'), ['UK']);
  assert.deepEqual(picked('прага фел'), ['FEL@ČVUT']);
  // «права» is a letter from «praha»; the law faculty is what was meant.
  assert.deepEqual(picked('права'), ['PrF@UK']);
});

test('six rows at most', () => {
  assert.equal(picked('чвут').length, 6);
});

test('one letter asks for nothing yet', () => {
  assert.deepEqual(picked('f'), []);
  assert.deepEqual(picked(' ч '), []);
});
