/**
 * Where keyboard focus goes when a sheet opens and closes.
 *
 * A sheet is a dialog, so a keyboard or screen-reader user has to land in it
 * and come back to where they were. The element types are the two methods this
 * needs, so the rules can be tested without a DOM.
 */

interface Focusable {
  focus(options?: { preventScroll?: boolean }): void;
  readonly isConnected: boolean;
}

/** Into the sheet, without the page behind it scrolling to follow. */
export function focusInto(panel: Focusable | null): void {
  panel?.focus({ preventScroll: true });
}

/**
 * Back to what opened the sheet, if it is still on the page: a choice made in
 * the sheet can remove the very button that opened it.
 */
export function giveFocusBack(opener: Focusable | null | undefined): void {
  if (opener?.isConnected) opener.focus({ preventScroll: true });
}
