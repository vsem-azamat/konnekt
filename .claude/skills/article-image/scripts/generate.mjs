// Generates the article's candidate images with the newest OpenAI image model.
//   op-broker run --reason "…" -e OPENAI_API_KEY="op://…" -- \
//     node generate.mjs <jobs.json> <out-dir>
// jobs.json: [{ "id": "a", "prompt": "…" }, …]  (the prompt already includes the rules)
// Writes <out-dir>/<id>.png (1536×1024) and <out-dir>/usage.json; prints cost.
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { latestImageModel } from './latest-model.mjs';

const [jobsFile, out] = process.argv.slice(2);
if (!jobsFile || !out) throw new Error('usage: generate.mjs <jobs.json> <out-dir>');
const jobs = JSON.parse(readFileSync(jobsFile, 'utf8'));
mkdirSync(out, { recursive: true });

const { model } = await latestImageModel();
// Output price per million image tokens; check https://developers.openai.com/api/docs/pricing
// when the model changes and update this number.
const USD_PER_M_OUTPUT = Number(process.env.IMAGE_USD_PER_M ?? 30);
console.log(`model ${model}`);

const usage = [];
// allSettled: one failed request must not lose the images already paid for.
await Promise.allSettled(jobs.map(async ({ id, prompt }) => { try {
  const file = `${out}/${id}.png`;
  if (existsSync(file)) return console.log(id, 'exists, skipped');
  const res = await fetch('https://api.openai.com/v1/images/generations', {
    method: 'POST',
    headers: { Authorization: `Bearer ${process.env.OPENAI_API_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, prompt, size: '1536x1024', quality: 'high', n: 1, output_format: 'png' }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) return console.log(id, 'ERROR', res.status, body.error?.message ?? '');
  writeFileSync(file, Buffer.from(body.data[0].b64_json, 'base64'));
  usage.push({ id, model, ...body.usage });
  console.log(id, 'ok', body.usage?.output_tokens, 'output tokens');
} catch (e) { console.log(id, 'ERROR', e.message); } }));
const tokens = usage.reduce((s, u) => s + (u.output_tokens ?? 0), 0);
writeFileSync(`${out}/usage.json`, JSON.stringify({ model, usage, usd: (tokens * USD_PER_M_OUTPUT) / 1e6 }, null, 1));
console.log(`total ${tokens} output tokens ≈ $${((tokens * USD_PER_M_OUTPUT) / 1e6).toFixed(2)}`);
