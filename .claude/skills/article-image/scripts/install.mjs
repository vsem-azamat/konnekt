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
const field = (head, name) => {
  if (new RegExp(`^${name}:[ \\t]*$`, 'm').test(head)) throw new Error(`${name} is written in block style; put it on one line first`);
  return head.match(new RegExp(`^${name}: (.*)$`, 'm'))?.[1];
};
const keyOf = (h, file) => (field(h, 'translationKey') ?? file.slice(0, -3)).replace(/^["']|["']$/g, '');

const md = join(ARTICLES, lang, `${slug}.md`);
const { head, body } = split(readFileSync(md, 'utf8'));
if (!/^author: /m.test(head)) throw new Error(`${md}: no author field to put the cover before`);
const key = keyOf(head, `${slug}.md`);

// The article's other languages: same translationKey, one cover file.
const siblings = readdirSync(ARTICLES).filter((l) => l !== lang && existsSync(join(ARTICLES, l)))
  .flatMap((l) => readdirSync(join(ARTICLES, l)).filter((f) => f.endsWith('.md')).map((f) => join(ARTICLES, l, f)))
  .map((file) => ({ file, ...split(readFileSync(file, 'utf8')) }))
  .filter(({ file, head: h }) => keyOf(h, file.split('/').pop()) === key);
// The same cover field of a sibling language, when this one has none.
const sibling = (name) => siblings.map(({ head: h }) => field(h, name)).find(Boolean);
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
const fieldsFor = (alt) => [
  `cover: ../../../assets/covers/${key}.jpg`,
  `coverAlt: ${alt}`,
  `coverFocus: ${focus}`,
  logos && `coverLogos: ${logos}`,
  credit && `coverCredit: ${credit}`,
].filter(Boolean);
const write = (file, h, b, alt) => {
  const fields = fieldsFor(alt);
  const nh = `${h}\n`.replace(/^cover(Alt|Focus|Logos|Credit)?:.*\n(?:(?:[ \t]+|- ).*\n)*/gm, '').replace(/\n$/, '')
    .replace(/^author: /m, `${fields.join('\n')}\nauthor: `);
  writeFileSync(file, `---\n${nh}\n---\n${b}`);
  console.log(`${file.replace(REPO, '')}: ${fields.map((f) => f.split(':')[0]).join(', ')}`);
};

if (fresh) console.log(`cover → web/site/src/assets/covers/${key}.jpg`);
write(md, head, body, yaml(v.alt));
// A new image changes what every language shows: their focus, logos and credit follow it,
// each keeping its own alt. A language with no cover yet gets one when run with "-".
if (fresh) {
  for (const s of siblings) {
    const alt = field(s.head, 'coverAlt');
    if (alt) write(s.file, s.head, s.body, alt);
    else console.log(`${s.file.replace(REPO, '')}: no coverAlt yet, run install.mjs for it with "-"`);
  }
}
