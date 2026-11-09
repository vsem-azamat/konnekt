/**
 * The blocks of a university's or a faculty's text (content.config.ts), as
 * its Markdown marks them, done on the Markdown tree (mdast) before it
 * becomes HTML. A mark is a class on a second-level heading, the same in
 * every language, so renaming a heading moves nothing:
 *
 * - `## Коротко {.brief}`: the list under it is the page's facts in brief.
 * - `## Что спрашивают в чате {.questions}`: each paragraph under it that
 *   opens with a bold «question» is one question and its answer.
 * - `## Поступление {.chats}`: the page's chats come before this section on
 *   a phone; on a wide screen they ride beside the text.
 * - `## Факты {.end}`: from here on is the reference part, the facts table
 *   and the notes, which the chats beside the text stop before.
 *
 * The text is split at the last two into three parts, `part-top`, `part-rest` and
 * `part-end`, always all three, so the page can lay its chats out against them.
 *
 * A photo, an image alone in its paragraph, becomes a figure with its
 * caption (the image's title) and its credit (articles/credit.ts) from the
 * text's `photos`. A photo without a credit, a credit without its photo, an
 * image anywhere else (in a list, in a line of text), an unknown mark, one
 * twice or one below the top level (in a quote) stops the build: the page
 * would silently lose the block, or the credit its photo.
 *
 * The mark itself is gone from the HTML: it says where a block is, and as a
 * class on the heading it could meet a style of the same name.
 *
 * An article takes no marks: one anywhere in it stops the build too.
 *
 * Written against the shape of the tree alone, as articles/reading.ts is,
 * so the tests build that shape by hand.
 */

import { type Credit, creditLine } from '../articles/credit.ts';
import { LANGS, type Lang } from '../paths.ts';

export interface MdNode {
  type: string;
  children?: MdNode[];
  data?: { hName?: string; hProperties?: Record<string, unknown> };
  depth?: number;
  url?: string;
  title?: string | null;
  value?: string;
}

export interface Photo extends Credit {
  src: string;
}

/** The marks a heading may carry, and what each does. */
export const MARKS = ['brief', 'questions', 'chats', 'end'] as const;
type Mark = (typeof MARKS)[number];

/** The heading's mark, if it has one; any other attribute on it is an error. */
function markOf(node: MdNode): Mark | null {
  const props = node.data?.hProperties;
  if (!props || Object.keys(props).length === 0) return null;
  const classes = props.className;
  const keys = Object.keys(props);
  if (
    keys.length !== 1 ||
    !Array.isArray(classes) ||
    classes.length !== 1 ||
    !MARKS.includes(classes[0] as Mark)
  ) {
    throw new Error(
      `a heading marked ${JSON.stringify(props)}: a mark is one of ${MARKS.map((m) => `{.${m}}`).join(' ')}`,
    );
  }
  if (node.depth !== 2) throw new Error(`{.${classes[0]}} marks a second-level heading`);
  return classes[0] as Mark;
}

function headingText(node: MdNode): string {
  return (node.children ?? []).map((child) => child.value ?? headingText(child)).join('');
}

/** Every node under these, depth first. */
function* descendants(nodes: readonly MdNode[]): Generator<MdNode> {
  for (const node of nodes) {
    yield node;
    yield* descendants(node.children ?? []);
  }
}

function isMarked(node: MdNode): boolean {
  return node.type === 'heading' && Object.keys(node.data?.hProperties ?? {}).length > 0;
}

/** The heading without its mark. */
function unmarked(node: MdNode): MdNode {
  const { hProperties: _, ...data } = node.data ?? {};
  return { ...node, data };
}

function withClass(node: MdNode, name: string): MdNode {
  return {
    ...node,
    data: { ...node.data, hProperties: { ...node.data?.hProperties, className: [name] } },
  };
}

/** A block of its own in the HTML: a node the converter turns into `tag` with its children. */
function block(tag: string, className: string[], children: MdNode[]): MdNode {
  return {
    type: 'blockquote',
    data: { hName: tag, hProperties: { className } },
    children,
  };
}

function isPhoto(node: MdNode): boolean {
  if (node.type !== 'paragraph') return false;
  const children = (node.children ?? []).filter(
    (child) => !(child.type === 'text' && !child.value?.trim()),
  );
  return children.length === 1 && children[0]?.type === 'image';
}

function figure(
  lang: Lang,
  paragraph: MdNode,
  photos: readonly Photo[],
  used: Set<string>,
): MdNode {
  const image = (paragraph.children ?? []).find(
    (child) => child.type === 'image',
  ) as MdNode;
  const photo = photos.find((one) => one.src === image.url);
  if (!photo)
    throw new Error(`the photo ${image.url} has no credit in the text's photos`);
  used.add(photo.src);
  const caption: MdNode[] = image.title
    ? [{ type: 'text', value: `${image.title} ` }]
    : [];
  const credit = creditLine(lang, photo).map(
    (part): MdNode =>
      part.href
        ? { type: 'link', url: part.href, children: [{ type: 'text', value: part.text }] }
        : { type: 'text', value: part.text },
  );
  return block(
    'figure',
    ['photo'],
    [
      { ...image, title: null },
      {
        type: 'paragraph',
        data: { hName: 'figcaption' },
        children: [...caption, ...credit],
      },
    ],
  );
}

/** Does the above to a directory text's tree, and returns the new one. */
export function placeBlocks(
  root: MdNode,
  { lang, photos }: { lang: Lang; photos: readonly Photo[] },
): MdNode {
  const parts: Record<'top' | 'rest' | 'end', MdNode[]> = { top: [], rest: [], end: [] };
  // Definitions are not shown where they stand: they stay at the root.
  const kept: MdNode[] = [];
  const seen = new Set<Mark>();
  const used = new Set<string>();
  let part: keyof typeof parts = 'top';
  let questions = false;
  const children = root.children ?? [];
  // What only the top level may hold: below it, the walk here would miss it.
  for (const top of children) {
    const below = [...descendants(top.children ?? [])];
    const image = isPhoto(top) ? undefined : below.find((node) => node.type === 'image');
    if (image) {
      throw new Error(
        `the image ${image.url} is not alone in a paragraph of its own: a photo stands so, to take its credit`,
      );
    }
    const heading = below.find(isMarked);
    if (heading)
      throw new Error(`«${headingText(heading)}» is marked below the top level`);
  }
  for (let i = 0; i < children.length; i++) {
    let node = children[i] as MdNode;
    if (node.type === 'footnoteDefinition' || node.type === 'definition') {
      kept.push(node);
      continue;
    }
    if (node.type === 'heading') {
      const mark = markOf(node);
      if (node.depth === 2) questions = false;
      if (mark) {
        node = unmarked(node);
        if (seen.has(mark)) throw new Error(`{.${mark}} marks two headings`);
        seen.add(mark);
        if (mark === 'chats') {
          if (seen.has('end')) throw new Error('{.chats} comes after {.end}');
          part = 'rest';
        }
        if (mark === 'end') part = 'end';
        if (mark === 'questions') questions = true;
        if (mark === 'brief') {
          const next = children[i + 1];
          if (next?.type !== 'list') {
            throw new Error(`{.brief} on «${headingText(node)}» has no list under it`);
          }
          parts[part].push(node, withClass(next, 'brief'));
          i++;
          continue;
        }
      }
    } else if (isPhoto(node)) {
      node = figure(lang, node, photos, used);
    } else if (
      questions &&
      node.type === 'paragraph' &&
      node.children?.[0]?.type === 'strong'
    ) {
      node = withClass(node, 'question');
    }
    parts[part].push(node);
  }
  const unused = photos.filter((photo) => !used.has(photo.src)).map((photo) => photo.src);
  if (unused.length > 0) throw new Error(`no photo in the text is ${unused.join(', ')}`);
  return {
    ...root,
    children: [
      block('div', ['part', 'part-top'], parts.top),
      block('div', ['part', 'part-rest'], parts.rest),
      block('div', ['part', 'part-end'], parts.end),
      ...kept,
    ],
  };
}

/** An article's tree: a mark there would be lost, so it stops the build. */
export function checkUnmarked(root: MdNode): void {
  const heading = [...descendants(root.children ?? [])].find(isMarked);
  if (heading) {
    throw new Error(
      `the heading «${headingText(heading)}» is marked; only a directory text takes marks`,
    );
  }
}

/** What Sätteri hands a plugin factory, as much of it as this one reads. */
interface Document {
  fileURL: URL | undefined;
  data: { astro?: { frontmatter?: Record<string, unknown> } };
}

/** What Sätteri hands a hook: the one mutation this one makes. */
interface Context {
  replaceNode(node: unknown, replacement: unknown): void;
}

/**
 * The above as an mdast plugin of Sätteri: for a directory text
 * (`content/universities/<lang>/`) its blocks, for an article
 * (`content/articles/<lang>/`) the check that it has none. Other Markdown
 * is left alone.
 */
export function placeBlocksPlugin(document: Document) {
  const path = document.fileURL?.pathname ?? '';
  const [, kind, lang] =
    path.match(/content\/(articles|universities)\/([a-z]{2})\//) ?? [];
  if (!kind || !LANGS.includes(lang as Lang)) return null;
  const photos = (document.data.astro?.frontmatter?.photos ?? []) as Photo[];
  return {
    name: 'konnekt-place-blocks',
    after(root: MdNode, ctx: Context) {
      // A plain copy: the tree Sätteri hands over is read-only.
      const tree = JSON.parse(JSON.stringify(root)) as MdNode;
      try {
        if (kind === 'articles') {
          checkUnmarked(tree);
          return;
        }
        ctx.replaceNode(
          root,
          placeBlocks(tree, {
            lang: lang as Lang,
            // Each with its default: the frontmatter here is as the file writes it.
            photos: photos.map((photo) => ({ ...photo, cropped: photo.cropped ?? true })),
          }),
        );
      } catch (error) {
        throw new Error(`${path}: ${(error as Error).message}`);
      }
    },
  };
}
