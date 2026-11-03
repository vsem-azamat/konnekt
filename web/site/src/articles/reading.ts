/**
 * What an article's Markdown needs beyond what remark gives it, done on the
 * HTML tree (hast) as a rehype step:
 *
 * - GFM footnotes are the article's sources. Each note links to one of the
 *   `sources` in its frontmatter and says when that source was checked; the
 *   notes' heading reads «Источники» in the article's language, visibly, and
 *   their way back is in that language too. A note linking to no listed
 *   source, or a listed source no note cites, stops the build: the list and
 *   the text would disagree about what the article rests on.
 * - A table goes in a box of its own, which scrolls on a narrow screen
 *   instead of the page.
 *
 * Written against the shape of the tree alone, with no hast library, so the
 * tests build that shape by hand.
 */

import { LANGS, type Lang } from '../paths.ts';
import { longDate, TEXTS } from '../texts.ts';

export interface Text {
  type: 'text';
  value: string;
}

export interface El {
  type: 'element' | 'root';
  tagName: string;
  properties: Record<string, unknown>;
  children: (El | Text | { type: string })[];
}

export interface Source {
  url: string;
  checked_at: Date;
}

function isEl(node: { type: string }): node is El {
  return node.type === 'element';
}

function walk(node: El, visit: (el: El, parent: El, index: number) => void): void {
  node.children.forEach((child, index) => {
    if (!isEl(child)) return;
    visit(child, node, index);
    walk(child, visit);
  });
}

function all(node: El, test: (el: El) => boolean): El[] {
  const found: El[] = [];
  walk(node, (el) => {
    if (test(el)) found.push(el);
  });
  return found;
}

/** Two addresses of one page: Markdown percent-encodes a link, the frontmatter keeps it as written. */
function same(a: string, b: string): boolean {
  try {
    return new URL(a).href === new URL(b).href;
  } catch {
    return a === b;
  }
}

function notes(section: El, lang: Lang, sources: readonly Source[]): void {
  const t = TEXTS[lang];
  for (const heading of all(section, (el) => el.tagName === 'h2')) {
    heading.children = [{ type: 'text', value: t.sources }];
    delete heading.properties.className;
  }
  const cited = new Set<string>();
  // The notes are the items of the section's own list; a list inside a note is part of it.
  const list = section.children.find(
    (child): child is El => isEl(child) && child.tagName === 'ol',
  );
  const items = (list?.children ?? []).filter(
    (child): child is El => isEl(child) && child.tagName === 'li',
  );
  for (const item of items) {
    const link = all(item, (el) => el.tagName === 'a').find((a) =>
      /^https?:/.test(String(a.properties.href)),
    );
    const url = String(link?.properties.href ?? '');
    const source = sources.find((one) => same(one.url, url));
    if (!source) {
      throw new Error(
        `footnote ${String(item.properties.id)} links to ${url || 'nothing'}, not to a listed source`,
      );
    }
    cited.add(source.url);
    const paragraph = all(item, (el) => el.tagName === 'p').at(-1) ?? item;
    const index = paragraph.children.findIndex(
      (child) => isEl(child) && 'dataFootnoteBackref' in child.properties,
    );
    const [back] = index === -1 ? [] : paragraph.children.splice(index, 1);
    // A line of its own under the note: when its source was checked, then the way back.
    paragraph.children.push({
      type: 'element',
      tagName: 'span',
      properties: { className: ['checked'] },
      children: [
        { type: 'text', value: `${t.checked} ${longDate(lang, source.checked_at)} ` },
        ...(back ? [back] : []),
      ],
    });
  }
  for (const back of all(section, (el) => 'dataFootnoteBackref' in el.properties)) {
    back.properties.ariaLabel = t.backToText;
    // The text presentation selector: without it iOS draws the arrow as an emoji.
    back.children = [{ type: 'text', value: '↩\uFE0E' }];
  }
  const uncited = sources.filter((one) => !cited.has(one.url)).map((one) => one.url);
  if (uncited.length > 0) {
    throw new Error(`no footnote cites ${uncited.join(', ')}`);
  }
}

/** Does the above to `root`; says whether the article has notes, which then stand for its sources. */
export function reading(
  root: El,
  { lang, sources }: { lang: Lang; sources: readonly Source[] },
): { notes: boolean } {
  let found = false;
  walk(root, (el, parent, index) => {
    if (el.tagName === 'table') {
      parent.children[index] = {
        type: 'element',
        tagName: 'div',
        properties: { className: ['table'] },
        children: [el],
      };
    }
    if (el.tagName === 'section' && el.properties.dataFootnotes) {
      notes(el, lang, sources);
      found = true;
    }
  });
  return { notes: found };
}

/** What Sätteri hands a plugin factory, as much of it as this one reads. */
interface Document {
  fileURL: URL | undefined;
  data: { astro?: { frontmatter?: Record<string, unknown> } };
}

/** What Sätteri hands a visitor: the mutations it may make. */
interface Visit {
  data: Document['data'];
  wrapNode(node: unknown, parent: El): void;
}

/**
 * `reading` as a hast plugin of Sätteri, Astro's Markdown processor: for an
 * article (`content/articles/<lang>/`), its language from its path, its
 * sources from its frontmatter. Whether it has notes goes back into the
 * frontmatter Astro hands the page. Other Markdown is left alone.
 */
export function readingPlugin(document: Document) {
  const path = document.fileURL?.pathname ?? '';
  const lang = path.match(/content\/articles\/([a-z]{2})\//)?.[1] as Lang | undefined;
  if (!lang || !LANGS.includes(lang)) return null;
  const sources = (
    (document.data.astro?.frontmatter?.sources ?? []) as {
      url: string;
      checked_at: string | Date;
    }[]
  ).map((source) => ({ url: source.url, checked_at: new Date(source.checked_at) }));
  return {
    name: 'konnekt-reading',
    element: [
      {
        filter: ['table'],
        visit(node: unknown, ctx: Visit) {
          ctx.wrapNode(node, {
            type: 'element',
            tagName: 'div',
            properties: { className: ['table'] },
            children: [],
          });
        },
      },
      {
        filter: ['section'],
        visit(node: El, ctx: Visit) {
          if (!node.properties?.dataFootnotes) return;
          // A plain copy: the node Sätteri hands over is read-only.
          const section = JSON.parse(JSON.stringify(node)) as El;
          try {
            reading(
              { type: 'root', tagName: '', properties: {}, children: [section] },
              { lang, sources },
            );
          } catch (error) {
            throw new Error(`${path}: ${(error as Error).message}`);
          }
          const frontmatter = ctx.data.astro?.frontmatter;
          if (frontmatter) frontmatter.notes = true;
          return section;
        },
      },
    ],
  };
}
