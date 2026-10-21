/**
 * The height the app is allowed to occupy, as Telegram reports it.
 *
 * Telegram's number rather than the webview's. On iOS and Android the SDK does
 * not trust `window.innerHeight` either — it asks the client and waits for
 * `viewport_changed` — so `100dvh`, which is that same untrusted number, can
 * be taller than what the person can actually see. An app sized to the webview
 * then puts its last rows below the visible edge with nothing able to scroll
 * to them, and `index.css` has deliberately left the document unable to.
 *
 * Two of Telegram's numbers, because neither is enough alone. `stableHeight`
 * is the one to trust when it comes: the live `height` follows a drag frame by
 * frame and would make everything pinned to the bottom jitter. But a stable
 * height is only as fresh as the last event Telegram marked stable. Minimised
 * on Android, the app stayed the height of the bottom bar after it was
 * expanded again: a heading and nothing under it. The sequence that reproduces
 * it is a stable height for the bar, then only moving heights on the way back
 * up. So the app ends at the live height once it has held still for
 * {@link SETTLE_MS}, and a stable height only gets it there sooner.
 *
 * Zero is not an answer. The signals read 0 until the client has reported, and
 * a variable set to `0px` is *defined* — `var(--app-height, 100dvh)` would
 * resolve to zero rather than fall back, and the app would be one frame of
 * nothing.
 */

/** How long the live height has to hold still to count: longer than a frame of a drag. */
export const SETTLE_MS = 250;

/** A number signal, as the SDK's viewport hands one out. */
interface Signal {
  (): number;
  sub(fn: (value: number) => void): () => void;
}

/** Publish the app's height now and on every change; returns the way to stop. */
export function followAppHeight(
  viewport: { height: Signal; stableHeight: Signal },
  publish: (height: number) => void,
): () => void {
  const offer = (height: number): void => {
    if (height > 0) publish(height);
  };

  let settling: ReturnType<typeof setTimeout> | undefined;
  const settle = (height: number): void => {
    clearTimeout(settling);
    // Telegram calls this height stable: nothing to wait for. Not left to the
    // stable signal, which says nothing when the sheet springs back to the
    // stable height it already had.
    if (height === viewport.stableHeight()) offer(height);
    else settling = setTimeout(() => offer(height), SETTLE_MS);
  };

  offer(viewport.stableHeight());
  const stopStable = viewport.stableHeight.sub(offer);
  const stopLive = viewport.height.sub(settle);
  return () => {
    clearTimeout(settling);
    stopStable();
    stopLive();
  };
}
