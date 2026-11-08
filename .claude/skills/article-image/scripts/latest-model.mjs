// Prints the newest OpenAI image model this key can use, e.g. gpt-image-2.6-sunburst.
// Run through op-broker so the key is in OPENAI_API_KEY; the key is never printed.
// Newest = highest version number in the id; dated snapshots (…-2026-05-01) are skipped.
// IMAGE_MODEL=<id> overrides the pick.
export async function latestImageModel() {
  if (process.env.IMAGE_MODEL) return { model: process.env.IMAGE_MODEL, all: [process.env.IMAGE_MODEL] };
  const res = await fetch('https://api.openai.com/v1/models', {
    headers: { Authorization: `Bearer ${process.env.OPENAI_API_KEY}` },
  });
  if (!res.ok) throw new Error(`models: HTTP ${res.status}`);
  const models = (await res.json()).data.filter((m) => /^gpt-image-/.test(m.id) && !/\d{4}-\d{2}-\d{2}$/.test(m.id));
  if (!models.length) throw new Error('no gpt-image model available to this key');
  const version = (id) => (id.match(/^gpt-image-([\d.]+)/)?.[1] ?? '0').split('.').map(Number);
  // Newest first: highest version number, then latest release. A release comes as tiers
  // (2.6-flare is the fast one, 2.6-sunburst the detailed one); covers are final images,
  // so the fast tier ranks last within its version.
  const fast = (id) => (/-(flare|mini)\b/.test(id) ? 1 : 0);
  const cmp = (a, b) => {
    const [x, y] = [version(a.id), version(b.id)];
    for (let i = 0; i < Math.max(x.length, y.length); i++) if ((x[i] ?? 0) !== (y[i] ?? 0)) return (y[i] ?? 0) - (x[i] ?? 0);
    return fast(a.id) - fast(b.id) || b.created - a.created;
  };
  const all = models.sort(cmp).map((m) => m.id);
  return { model: all[0], all };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const { model, all } = await latestImageModel();
  console.log(model);
  console.error(`image models for this key: ${all.join(', ')}`);
}
