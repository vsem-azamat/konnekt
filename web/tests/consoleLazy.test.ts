import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { test } from 'node:test';

const src = join(import.meta.dirname, '..', 'src');

/** A static import's target, as vite would find it, or null for a package. */
function resolve(from: string, spec: string): string | null {
  let base: string;
  if (spec.startsWith('@/')) base = join(src, spec.slice(2));
  else if (spec.startsWith('.')) base = join(dirname(from), spec);
  else return null;
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`, join(base, 'index.ts')]) {
    if (/\.tsx?$/.test(candidate) && existsSync(candidate)) return candidate;
  }
  return null;
}

/** Every module the entry pulls in before anything is asked for: its first download. */
function staticGraph(entry: string): Set<string> {
  const seen = new Set<string>();
  const queue = [entry];
  for (let file = queue.pop(); file; file = queue.pop()) {
    if (seen.has(file)) continue;
    seen.add(file);
    const code = readFileSync(file, 'utf8');
    for (const [, spec] of code.matchAll(
      /^(?:import|export)\s+(?!type\b)[^;]*?from\s+'([^']+)'/gm,
    )) {
      const target = spec && resolve(file, spec);
      if (target) queue.push(target);
    }
  }
  return seen;
}

test('the Mini App opens without downloading the console', () => {
  const reached = [...staticGraph(join(src, 'main.tsx'))].map((file) =>
    relative(src, file),
  );
  const consoleScreens = reached.filter(
    (file) =>
      file.startsWith('console/pages/') ||
      ['console/BrowserShell.tsx', 'console/Login.tsx'].includes(file),
  );
  assert.deepEqual(consoleScreens, []);
});

test('the walk follows the imports it is meant to', () => {
  // Without this, a regex that matched nothing would pass the test above.
  const reached = [...staticGraph(join(src, 'main.tsx'))].map((file) =>
    relative(src, file),
  );
  assert.ok(reached.includes('router.tsx'));
  assert.ok(reached.includes('pages/Home.tsx'));
});
