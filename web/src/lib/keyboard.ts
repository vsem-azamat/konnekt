/**
 * How much of the window the on-screen keyboard covers, for what is pinned to
 * the bottom of it.
 *
 * On iOS the keyboard leaves the layout alone: the window keeps its height,
 * `100dvh` with it, and only the visual viewport shrinks. A sheet fixed to the
 * bottom stays where it was, under the keyboard, with the field the person is
 * typing into and the button that sends it. What the keyboard covers is the
 * part of the window below the visual viewport.
 *
 * iOS also pans the visual viewport down the window to bring a low field into
 * view, and then the top of the window is out of sight as well. Both are
 * published: a sheet between them is between the keyboard and the top of what
 * can be seen.
 *
 * Android resizes the whole webview instead, so the window and the visual
 * viewport shrink together and nothing is covered: the layout already follows.
 */

/** `window.visualViewport`, as far as the rule reads it. */
interface VisualView extends EventTarget {
  readonly height: number;
  readonly offsetTop: number;
}

/** What is out of sight, in px: `covered` at the bottom of the window, `panned` at its top. */
export interface Cover {
  covered: number;
  panned: number;
}

/** Publish the cover whenever it changes; returns the way to stop. */
export function followKeyboard(
  view: VisualView,
  layoutHeight: () => number,
  publish: (cover: Cover) => void,
): () => void {
  // Nothing is out of sight until something says so, which is also what the
  // CSS assumes before the first publish.
  let last: Cover = { covered: 0, panned: 0 };
  const measure = (): void => {
    const panned = Math.max(0, Math.round(view.offsetTop));
    const covered = Math.max(
      0,
      Math.round(layoutHeight() - view.height - view.offsetTop),
    );
    if (covered === last.covered && panned === last.panned) return;
    last = { covered, panned };
    publish(last);
  };
  view.addEventListener('resize', measure);
  view.addEventListener('scroll', measure);
  return () => {
    view.removeEventListener('resize', measure);
    view.removeEventListener('scroll', measure);
  };
}
