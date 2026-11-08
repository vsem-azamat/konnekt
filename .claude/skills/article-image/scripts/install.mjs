// After Azamat's pick: puts the chosen image in the site and points the article at it.
//   node install.mjs <lang> <slug> <image> --alt "…" [--focus 0.5] [--logos cvut,cvut-fit] [--credit image.credit.json]
// Writes web/site/src/assets/covers/<translationKey>.jpg, cut to 1536×1024 around the focus —
// one file shared by the article's languages — and sets cover, coverAlt, coverFocus,
// coverLogos, coverCredit in web/site/src/content/articles/<lang>/<slug>.md.
// --focus is the point across the image you pass; the article gets it measured on the cut cover.
// Run it once per language with that language's --alt and "-" as the image, which keeps the
// cover file: then a flag left out keeps the article's own value, or a sibling language's
// with the same translationKey. A new image starts clean: no credit unless --credit, focus
// 0.5 unless --focus; logos are kept unless --logos is given ("" removes them).
import { readFileSync, writeFileSync, mkdirSync, readdirSync, existsSync } from 'node:fs';
import { cut } from './cut.mjs';
import { join } from 'node:path';
import { parseArgs } from 'node:util';

const REPO = new URL('../../../../', import.meta.url).pathname;
const ARTICLES = join(REPO, 'web/site/src/content/articles');
const { positionals: [lang, slug, image], values: v } = parseArgs({
  allowPositionals: true,
  options: { alt: { type: 'string' }, focus: { type: 'string' }, logos: { type: 'string' }, credit: { type: 'string' } },
});
if (!lang || !slug || !image || !v.alt) {
  throw new Error('usage: install.mjs <lang> <slug> <image|-> --alt "…" [--focus] [--logos] [--credit]');
}

// Only the frontmatter block is read and changed, never the article's body.
const split = (text) => {
  const m = text.match(/^---\n([\s\S]*?)\n---\n/);
  if (!m) throw new Error('no frontmatter');
  return { head: m[1], body: text.slice(m[0].length) };
};
const field = (head, name) => head.match(new RegExp(`^${name}: (.*)$`, 'm'))?.[1];

const md = join(ARTICLES, lang, `${slug}.md`);
const { head, body } = split(readFileSync(md, 'utf8'));
if (!/^author: /m.test(head)) throw new Error(`${md}: no author field to put the cover before`);
const key = (field(head, 'translationKey') ?? slug).replace(/^["']|["']$/g, '');

// The same cover fields of a sibling language, when this one has none.
const sibling = (name) => {
  for (const l of readdirSync(ARTICLES)) {
    if (l === lang) continue;
    for (const f of existsSync(join(ARTICLES, l)) ? readdirSync(join(ARTICLES, l)) : []) {
      if (!f.endsWith('.md')) continue;
      const h = split(readFileSync(join(ARTICLES, l, f), 'utf8')).head;
      if ((field(h, 'translationKey') ?? f.slice(0, -3)).replace(/^["']|["']$/g, '') === key && field(h, name)) return field(h, name);
    }
  }
};
const keep = (name) => field(head, name) ?? sibling(name);

const fresh = image !== '-';
let focus = v.focus !== undefined ? Number(v.focus) : fresh ? 0.5 : Number(keep('coverFocus') ?? 0.5);
if (!(focus >= 0 && focus <= 1)) throw new Error('--focus is from 0 to 1');

if (fresh) {
  mkdirSync(join(REPO, 'web/site/src/assets/covers'), { recursive: true });
  focus = cut(image, join(REPO, 'web/site/src/assets/covers', `${key}.jpg`), focus, ['-q:v', '3']);
}

const yaml = (s) => JSON.stringify(s); // a JSON string is a valid YAML scalar
let credit = fresh ? undefined : keep('coverCredit');
if (v.credit) {
  const c = JSON.parse(readFileSync(v.credit, 'utf8'));
  if (!c.author || !/^https:\/\//.test(c.source ?? '')) throw new Error(`${v.credit}: the credit needs an author and an https source`);
  const lu = /^https:\/\//.test(c.licenceUrl ?? '') ? c.licenceUrl : undefined;
  credit = `{ author: ${yaml(c.author)}, licence: ${yaml(c.licence)}${lu ? `, licenceUrl: ${yaml(lu)}` : ''}, source: ${yaml(c.source)} }`;
}
const logos = v.logos !== undefined ? (v.logos.trim() === '' ? undefined : `[${v.logos.split(',').map((s) => s.trim()).filter(Boolean).join(', ')}]`) : keep('coverLogos');
const fields = [
  `cover: ../../../assets/covers/${key}.jpg`,
  `coverAlt: ${yaml(v.alt)}`,
  `coverFocus: ${focus}`,
  logos && `coverLogos: ${logos}`,
  credit && `coverCredit: ${credit}`,
].filter(Boolean);

const newHead = `${head}\n`.replace(/^cover(Alt|Focus|Logos|Credit)?:.*\n(?:[ \t]+.*\n)*/gm, '').replace(/\n$/, '').replace(/^author: /m, `${fields.join('\n')}\nauthor: `);
writeFileSync(md, `---\n${newHead}\n---\n${body}`);
console.log(`cover → web/site/src/assets/covers/${key}.jpg; ${md.replace(REPO, '')}: ${fields.map((f) => f.split(':')[0]).join(', ')}`);
