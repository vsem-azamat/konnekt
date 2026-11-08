// Builds the page Azamat picks from: per article its candidates, each shown as
// the dark link card (as Telegram shows it) and as the cover on the article page.
//   node pick-page.mjs <manifest.json> <out-dir>
// manifest: { "cost": "≈ $0.25", "model": "gpt-image-…", "articles": [{ "slug", "title", "rubric",
//   "candidates": [{ "id": "A", "file": "/abs/a.png", "source": "generated"|"commons",
//   "credit"?: {author, licence, source}, "logos"?: ["cvut"], "focus"?: 0.5, "note": "…" }] }] }
// Then publish <out-dir>/index.html with the Artifact tool, with img/* as files.
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';

const REPO = new URL('../../../../', import.meta.url).pathname;
// LOGOS_DIR points elsewhere while the site has no logo registry yet.
const LOGOS = process.env.LOGOS_DIR ?? join(REPO, 'web/site/src/assets/logos');
const RUBRICS = { admission: 'Поступление', visa: 'Виза и ВНЖ', housing: 'Жильё', study: 'Учёба', work: 'Работа и деньги' };

const [manifestFile, out] = process.argv.slice(2);
if (!manifestFile || !out) throw new Error('usage: pick-page.mjs <manifest.json> <out-dir>');
const M = JSON.parse(readFileSync(manifestFile, 'utf8'));
mkdirSync(join(out, 'img'), { recursive: true });
const esc = (s = '') => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');

const files = [];
const jpg = (src, name) => {
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', src, '-vf', 'scale=1200:-2', '-q:v', '3', join(out, 'img', name)]);
  files.push(`img/${name}`);
  return `img/${name}`;
};
const logo = (id) => {
  for (const ext of ['svg', 'png']) {
    const f = join(LOGOS, `${id}.${ext}`);
    if (existsSync(f)) {
      writeFileSync(join(out, 'img', `logo-${id}.${ext}`), readFileSync(f));
      files.push(`img/logo-${id}.${ext}`);
      return `img/logo-${id}.${ext}`;
    }
  }
  throw new Error(`no logo file for ${id} in ${LOGOS}`);
};
const logos = (ids = []) => !ids.length ? '' : ids.length === 1
  ? `<span class="badge"><img src="${logo(ids[0])}" alt="${esc(ids[0])}"></span>`
  : `<span class="strip">${ids.map((id) => `<img src="${logo(id)}" alt="${esc(id)}">`).join('')}</span>`;
const glue = (s) => s.replace(/(^|\s)([А-ЯЁA-Z]?[а-яёa-z]{0,2}|[а-яё]{3})\s/g, (m, a, w) => (w ? `${a}${w} ` : m));

const cand = (a, c) => {
  const src = jpg(c.file, `${a.slug}-${c.id}.jpg`);
  // The site's card crop (web/site/src/articles/og.ts, framed): the frame filled, centred on
  // focus and clamped to the image. CSS object-position needs it as a share of the overflow.
  const W0 = 1536, H0 = 1024, PW = 540, PH = 590;
  const w = Math.max(PW, Math.round(W0 * Math.max(PW / W0, PH / H0)));
  const left = Math.min(w - PW, Math.max(0, (c.focus ?? 0.5) * w - PW / 2));
  const pos = `${w > PW ? ((left / (w - PW)) * 100).toFixed(1) : 50}% 50%`;
  return `
  <article class="cand">
    <h3>Вариант ${esc(c.id)}</h3>
    <p class="note">${esc(c.note)}${c.source === 'commons' ? ' Настоящее фото с Wikimedia Commons.' : ' Сгенерировано.'}</p>
    <div class="lbl">Превью ссылки</div>
    <div class="og">
      <div class="og-text">
        <b class="og-brand">Konnekt</b>
        <span class="og-chip">${esc(RUBRICS[a.rubric] ?? a.rubric)}</span>
        <b class="og-title">${esc(glue(a.title))}</b>
        <span class="og-site">konnekt.cz</span>
      </div>
      <div class="og-pic"><img src="${src}" alt="" style="object-position:${pos}">${logos(c.logos)}</div>
    </div>
    <div class="lbl">Обложка на странице статьи</div>
    <figure class="pagecover"><div class="pc"><img src="${src}" alt="">${logos(c.logos)}</div>
      ${c.credit ? `<figcaption>Фото: ${esc(c.credit.author)}, ${esc(c.credit.licence)}, <a href="${/^https:\/\//.test(c.credit.source) ? esc(c.credit.source) : '#'}">Wikimedia Commons</a></figcaption>` : ''}</figure>
  </article>`;
};

const html = `<title>Обложки: выбор</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;800&display=swap">
<style>
:root { --bg:#f7f6f3; --card:#fffefc; --hair:#e7e5df; --ink:#141312; --soft:#4a4640; --muted:#6b665e; --font:'Inter Tight',system-ui,sans-serif; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#121110; --card:#1b1a18; --hair:#2a2825; --ink:#f4f2ee; --soft:#cfcac1; --muted:#8e8a83; color-scheme:dark; } }
:root[data-theme="dark"] { --bg:#121110; --card:#1b1a18; --hair:#2a2825; --ink:#f4f2ee; --soft:#cfcac1; --muted:#8e8a83; color-scheme:dark; }
body { background:var(--bg); color:var(--ink); font-family:var(--font); font-size:16px; line-height:1.5; }
.page { max-width:1180px; margin:0 auto; padding-block:36px 64px; padding-left:max(16px,env(safe-area-inset-left,0px)); padding-right:max(16px,env(safe-area-inset-right,0px)); display:grid; gap:28px; }
h1 { font-size:clamp(26px,4vw,38px); line-height:1.1; letter-spacing:-0.03em; margin:0; text-wrap:balance; }
h2 { font-size:22px; letter-spacing:-0.02em; margin:0; text-wrap:balance; }
h3 { font-size:17px; margin:0; }
p { margin:0; max-width:70ch; } .note { color:var(--soft); font-size:15px; }
.lbl { font-size:12px; font-weight:600; letter-spacing:.06em; text-transform:uppercase; color:var(--muted); }
section { background:var(--card); border:1px solid var(--hair); border-radius:18px; padding:20px 22px 24px; display:grid; gap:16px; min-width:0; }
.cands { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:18px; }
@media (max-width:980px) { .cands { grid-template-columns:1fr; max-width:560px; } }
.cand { display:grid; gap:8px; align-content:start; min-width:0; }
/* the dark link card, drawn after the site's og:image template */
.og { container-type:inline-size; aspect-ratio:1200/630; max-width:100%; display:flex; border-radius:10px; overflow:hidden; color:#fffefc;
  background:#141312 radial-gradient(ellipse 47% 40% at 6% 110%, rgba(63,107,184,.62), transparent) , radial-gradient(ellipse 47% 40% at 58% 112%, rgba(178,58,63,.55), transparent); background-color:#141312; }
.og-text { width:53.3%; padding:4.5cqw 3.7cqw 4.2cqw 5.3cqw; display:flex; flex-direction:column; justify-content:space-between; align-items:flex-start; }
.og-brand { font-size:2.5cqw; font-weight:800; }
.og-chip { font-size:1.8cqw; font-weight:600; color:#e9e6df; border:1px solid rgba(255,254,252,.16); background:rgba(255,254,252,.08); border-radius:.8cqw; padding:.4cqw 1.1cqw; margin-top:auto; }
.og-title { font-size:4.6cqw; line-height:1.06; letter-spacing:-.03em; font-weight:800; margin:1.8cqw 0 auto; text-wrap:balance; }
.og-site { font-size:1.8cqw; color:#a8a39a; }
.og-pic { position:relative; width:46.7%; padding:1.7cqw 1.7cqw 1.7cqw 0; display:flex; }
.og-pic img { width:100%; height:100%; object-fit:cover; border-radius:1.8cqw; border:1px solid rgba(255,254,252,.14); }
.og .badge { left:3.2cqw; bottom:3.2cqw; padding:1cqw 1.4cqw; border-radius:1.1cqw; } .og .badge img { height:5cqw; border:0; border-radius:0; width:auto; }
.og .strip { left:0; right:1.7cqw; bottom:1.7cqw; border-radius:0 0 1.8cqw 1.8cqw; padding:1.2cqw; gap:1.2cqw; } .og .strip img { height:4.2cqw; width:auto; border:0; border-radius:0; }
.badge, .strip { position:absolute; background:#fff; display:flex; flex-wrap:wrap; justify-content:space-around; align-items:center; }
.pagecover { margin:0; display:grid; gap:6px; } .pc { position:relative; container-type:inline-size; }
.pc > img { display:block; width:100%; height:auto; border-radius:14px; }
.pc .badge { left:2.5cqw; bottom:2.5cqw; padding:1.2cqw 1.6cqw; border-radius:1.4cqw; } .pc .badge img { height:7cqw; }
.pc .strip { left:0; right:0; bottom:0; padding:1.6cqw; gap:1.6cqw; border-radius:0 0 14px 14px; } .pc .strip img { height:6cqw; }
figcaption { font-size:13px; color:var(--muted); } figcaption a { color:inherit; }
</style>
<div class="page">
  <header style="display:grid;gap:10px">
    <span class="lbl">konnekt.cz · статьи · для Azamat</span>
    <h1>Обложки: выбери по одной на статью</h1>
    <p class="note">По три варианта на статью. Каждый показан так, как его увидят: превью ссылки (тёмная карточка) и обложка на странице статьи. Ответь буквой для каждой статьи, например «${M.articles.map((a, i) => `${i + 1} — A`).join(', ')}». Модель: ${esc(M.model)}. Стоимость: ${esc(M.cost)}.</p>
  </header>
  ${M.articles.map((a, i) => `<section><h2>${i + 1}. ${esc(a.title)}</h2><div class="cands">${a.candidates.map((c) => cand(a, c)).join('')}</div></section>`).join('')}
</div>`;
writeFileSync(join(out, 'index.html'), html);
writeFileSync(join(out, 'files.json'), JSON.stringify(Object.fromEntries([...new Set(files)].map((f) => [f, join(out, f)])), null, 1));
console.log(`page ${join(out, 'index.html')}, ${new Set(files).size} files listed in files.json`);
