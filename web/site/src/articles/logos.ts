/**
 * The schools' logos an article's cover may carry (`coverLogos`), as each
 * school publishes it: the file in assets/logos/ is the one downloaded from
 * `source`, unchanged but for the format where the school offers no SVG.
 * Never redrawn and never recoloured, and always on white, which is where
 * every one of these manuals puts it. An image model is never asked to draw
 * one: it would get it wrong.
 *
 * `rule` is what the school's own rules say about someone else using it, for
 * whoever decides whether a cover may; it is our record, not shown to readers.
 */
export const LOGOS = {
  uk: {
    name: 'Univerzita Karlova',
    file: 'uk.svg',
    source:
      'https://uk.brandcloud.pro/api/v2/document/shared/313815/element/5256475/download',
    page: 'https://cuni.cz/UK-16062.html',
    rule: 'Use by third parties needs the written consent of the rector or the vice-rector for external relations (Opatření rektora č. 45/2023, čl. 4: https://cuni.cz/UK-13122.html).',
  },
  cvut: {
    name: 'České vysoké učení technické v Praze',
    file: 'cvut.svg',
    source:
      'https://www.cvut.cz/sites/default/files/content/e254fb38-e72d-463b-8c9f-cb0435416f29/cs/20201110-symbol-a-logo-cvut-v-praze.zip',
    page: 'https://www.cvut.cz/logo-a-graficky-manual',
    rule: 'The manual is silent on third parties; Příkaz rektora č. 4/2016 (čl. I odst. 5) allows them the mark only under a written contract with ČVUT. Whether that order still stands is unchecked.',
  },
  'cvut-fit': {
    name: 'Fakulta informačních technologií ČVUT',
    file: 'cvut-fit.svg',
    source: 'https://fit.cvut.cz/media-a-pr/corporate-identity/logo-fit-cs-modra.svg',
    page: 'https://fit.cvut.cz/cs/media-a-pr/corporate-identity',
    rule: 'The faculty offers its logos to anyone linking to it, within the ČVUT manual; the university-wide order 4/2016 still asks for a contract.',
  },
  'cvut-fel': {
    name: 'Fakulta elektrotechnická ČVUT',
    file: 'cvut-fel.svg',
    source:
      'https://www.cvut.cz/sites/default/files/content/e254fb38-e72d-463b-8c9f-cb0435416f29/cs/20201110-loga-soucasti-cvut.zip',
    page: 'https://www.cvut.cz/logo-a-graficky-manual',
    rule: 'As ČVUT: a written contract under Příkaz rektora č. 4/2016.',
  },
  vse: {
    name: 'Vysoká škola ekonomická v Praze',
    file: 'vse.svg',
    source:
      'https://pr.vse.cz/wp-content/uploads/page/58/VSE_logo_CZ_horizontal_blue.pdf',
    page: 'https://pr.vse.cz/logo-vse/',
    rule: 'Free for media, only alongside editorial articles about VŠE; any other use needs the prior consent of its PR department. Offered as PDF only: this is its vector PDF converted to SVG.',
  },
  muni: {
    name: 'Masarykova univerzita',
    file: 'muni.svg',
    source: 'https://muni.brandcloud.pro/api/v2/document/157182/element/1891270/download',
    page: 'https://muni.brandcloud.pro/document/68042/157182',
    rule: 'The manual says nothing on third parties, only that the mark is never modified. Offered as PDF only: this is its screen PDF converted to SVG.',
  },
  vut: {
    name: 'Vysoké učení technické v Brně',
    file: 'vut.png',
    source: 'https://www.vut.cz/vut/media/logo-vut-zip-p287600',
    page: 'https://www.vut.cz/vut/media',
    rule: 'The 2015 manual says nothing on third parties, only that the mark sits best on white. Offered as PNG only.',
  },
  up: {
    name: 'Univerzita Palackého v Olomouci',
    file: 'up.svg',
    source: 'https://jvs.upol.cz/soubory_v2/logotypy/UP_logotypy.zip',
    page: 'https://jvs.upol.cz/logotypy.html',
    rule: 'The 2017 manual (https://jvs.upol.cz/soubory_v2/UP_manualJVS.pdf) says nothing on third parties. The pack has no SVG: this is PDF_tisk/UP_logo_horizont_cz.pdf converted to SVG, its empty margin trimmed and its two colours set to the screen RGB of the manual (blue #006FAD, grey #5D5E60, section 2.8), as in the PNG_web files of the pack; the CMYK of the print PDF had come out darker.',
  },
} as const;

export type LogoId = keyof typeof LOGOS;

export const LOGO_IDS = Object.keys(LOGOS) as [LogoId, ...LogoId[]];
