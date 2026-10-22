/**
 * How much of the window the on-screen keyboard covers, for what is pinned to
 * the bottom of it.
 *
 * On iOS the keyboard leaves the layout alone: the window keeps its height,
 * `100dvh` with it, and only the visual viewport shrinks. A sheet fixed to the
 * bottom stays where it was, under the keyboard, with the field the person is
 * typing into and the button that sends it. What the keyboard covers is the
 * part of the window below the visual viewport, panned or not.
 *
 * Android resizes the whole webview instead, so the window and the visual
 * viewport shrink together and nothing is covered: the layout already follows.
 */

/** `window.visualViewport`, as far as the rule reads it. */
interface VisualView extends EventTarget {
  readonly height: number;
  readonly offsetTop: number;
}

/** Publish the covered height, in px, whenever it changes; returns the way to stop. */
export function followKeyboard(
  view: VisualView,
  layoutHeight: () => number,
  publish: (covered: number) => void,
): () => void {
  // Nothing is covered until something says so, which is also what the CSS
  // assumes before the first publish.
  let last = 0;
  const measure = (): void => {
    const covered = Math.max(
      0,
      Math.round(layoutHeight() - view.height - view.offsetTop),
    );
    if (covered === last) return;
    last = covered;
    publish(covered);
  };
  view.addEventListener('resize', measure);
  view.addEventListener('scroll', measure);
  return () => {
    view.removeEventListener('resize', measure);
    view.removeEventListener('scroll', measure);
  };
}
