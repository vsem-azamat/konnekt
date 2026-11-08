// Finds and downloads a real photo from Wikimedia Commons with its credit.
//   node commons.mjs search "České vysoké učení technické Dejvice budova"
//   node commons.mjs get "File:Name.jpg" <out.jpg>
// Only licences that allow reuse with credit are accepted: CC0, public domain, CC BY, CC BY-SA.
import { writeFileSync } from 'node:fs';

const API = 'https://commons.wikimedia.org/w/api.php';
// Wikimedia asks automated clients to identify themselves.
const UA = { 'User-Agent': 'konnekt-article-image/1.0 (https://konnekt.cz)' };
const OK = /^(CC0|Public domain|PD|CC BY(-SA)? [\d.]+)/i;
const text = (html = '') => html.replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();

async function api(params) {
  const res = await fetch(`${API}?${new URLSearchParams({ format: 'json', origin: '*', ...params })}`, { headers: UA });
  if (!res.ok) throw new Error(`commons: HTTP ${res.status}`);
  return res.json();
}

function credit(page) {
  const ii = page.imageinfo?.[0];
  const m = ii?.extmetadata ?? {};
  return {
    title: page.title,
    width: ii?.width, height: ii?.height,
    licence: text(m.LicenseShortName?.value),
    // Commons gives some licence links as http://; the site takes https only.
    licenceUrl: text(m.LicenseUrl?.value).replace(/^http:\/\//, 'https://'),
    // trademarked, personality (identifiable people) and the like: not for a cover
    restrictions: text(m.Restrictions?.value),
    author: text(m.Artist?.value) || text(m.Credit?.value),
    source: ii?.descriptionurl,
    url: ii?.url,
    usable: OK.test(text(m.LicenseShortName?.value)) && !text(m.Restrictions?.value) && !!(text(m.Artist?.value) || text(m.Credit?.value)) && (ii?.width ?? 0) >= 1536 && (ii?.height ?? 0) >= 1024,
  };
}

const [cmd, arg, out] = process.argv.slice(2);
if (cmd === 'search') {
  const r = await api({ action: 'query', generator: 'search', gsrsearch: `${arg} filetype:bitmap`, gsrnamespace: '6', gsrlimit: '20', prop: 'imageinfo', iiprop: 'url|size|extmetadata' });
  const rows = Object.values(r.query?.pages ?? {}).map(credit);
  for (const c of rows) console.log(`${c.usable ? 'OK ' : '-- '}${c.title} | ${c.width}×${c.height} | ${c.licence}${c.restrictions ? ` | restricted: ${c.restrictions}` : ''} | ${c.author}`);
} else if (cmd === 'get') {
  const r = await api({ action: 'query', titles: arg, prop: 'imageinfo', iiprop: 'url|size|extmetadata' });
  const c = credit(Object.values(r.query.pages)[0]);
  if (!c.usable) throw new Error(`not usable: ${c.licence}, ${c.width}×${c.height}${c.restrictions ? `, restricted: ${c.restrictions}` : ''}${c.author ? '' : ', no author'}`);
  const img = await fetch(c.url, { headers: UA });
  if (!img.ok) throw new Error(`download: HTTP ${img.status}`);
  writeFileSync(out, Buffer.from(await img.arrayBuffer()));
  writeFileSync(`${out}.credit.json`, JSON.stringify({ author: c.author, licence: c.licence, licenceUrl: c.licenceUrl, source: c.source }, null, 1));
  console.log(JSON.stringify({ file: out, author: c.author, licence: c.licence, source: c.source }));
} else {
  throw new Error('usage: commons.mjs search <query> | get <File:…> <out>');
}
