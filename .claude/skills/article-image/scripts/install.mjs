// After Azamat's pick: puts the chosen image in the site and points the article at it.
//   node install.mjs <lang> <slug> <image> --alt "…" [--focus 0.5] [--logos cvut,cvut-fit] [--credit image.credit.json]
// Writes web/site/src/assets/covers/<translationKey>.jpg (1536 wide, JPEG) — one file shared by
// the article's languages — and sets cover, coverAlt, coverFocus, coverLogos, coverCredit in
// web/site/src/content/articles/<lang>/<slug>.md. Each other language gets its own coverAlt.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';
import { parseArgs } from 'node:util';

const REPO = new URL('../../../../', import.meta.url).pathname;
const { positionals: [lang, slug, image], values: v } = parseArgs({
  allowPositionals: true,
  options: { alt: { type: 'string' }, focus: { type: 'string' }, logos: { type: 'string' }, credit: { type: 'string' } },
});
if (!lang || !slug || !image || !v.alt) throw new Error('usage: install.mjs <lang> <slug> <image> --alt "…" [--focus] [--logos] [--credit]');

const md = join(REPO, 'web/site/src/content/articles', lang, `${slug}.md`);
let text = readFileSync(md, 'utf8');
const key = text.match(/^translationKey: (\S+)$/m)?.[1] ?? slug;
mkdirSync(join(REPO, 'web/site/src/assets/covers'), { recursive: true });
execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', image, '-vf', 'scale=1536:-2', '-q:v', '3', join(REPO, 'web/site/src/assets/covers', `${key}.jpg`)]);

const yaml = (s) => JSON.stringify(s); // a JSON string is a valid YAML scalar
const fields = [
  `cover: ../../../assets/covers/${key}.jpg`,
  `coverAlt: ${yaml(v.alt)}`,
  v.focus && `coverFocus: ${Number(v.focus)}`,
  v.logos && `coverLogos: [${v.logos.split(',').map((s) => s.trim()).join(', ')}]`,
  v.credit && (() => { const c = JSON.parse(readFileSync(v.credit, 'utf8')); return `coverCredit: { author: ${yaml(c.author)}, licence: ${yaml(c.licence)}, source: ${yaml(c.source)} }`; })(),
].filter(Boolean);

// drop old cover fields, then put the new ones right before `author:`
text = text.replace(/^cover(Alt|Focus|Logos|Credit)?: .*\n/gm, '');
text = text.replace(/^author: /m, `${fields.join('\n')}\nauthor: `);
writeFileSync(md, text);
console.log(`cover → web/site/src/assets/covers/${key}.jpg; ${md.replace(REPO, '')} updated`);
