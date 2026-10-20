/**
 * A chat's preview sheet, kept in the router's history.
 *
 * Opening it pushes an entry for the same address carrying the chat's link,
 * so Back — Telegram's button, or Android's own, which on the first screen
 * would otherwise close the whole Mini App — closes the sheet and nothing
 * else. Every way out of the sheet goes back one entry rather than forward,
 * or the entry would stay behind and Back would reopen it — except on an
 * entry with nothing behind it (the app opened on a link to a preview), where
 * going back would close the Mini App, so the entry is replaced instead.
 */

interface Place {
  pathname: string;
  search: string;
  hash: string;
  state: unknown;
  /** react-router's "default" is the entry the app started on. */
  key: string;
}

interface Router {
  navigate: {
    (delta: number): unknown;
    (
      to: { pathname: string; search: string; hash: string },
      options: { state: unknown; replace?: boolean },
    ): unknown;
  };
  /**
   * The entry's state as it is now, not as it was rendered: two taps in one
   * frame both render closed, and only history knows the first one landed.
   */
  stateNow: () => unknown;
  /** Leaves for Telegram. Only `join`, the sheet's button, calls it. */
  openLink: (link: string) => unknown;
}

function previewOf(state: unknown): string | null {
  if (state === null || typeof state !== 'object') return null;
  const { preview } = state as { preview?: unknown };
  return typeof preview === 'string' ? preview : null;
}

export function chatPreview(
  link: string,
  place: Place,
  { navigate, openLink, stateNow }: Router,
) {
  const open = previewOf(place.state) === link;
  const { pathname, search, hash } = place;
  const leave = () => {
    if (place.key === 'default') {
      navigate({ pathname, search, hash }, { replace: true, state: null });
    } else {
      navigate(-1);
    }
  };
  return {
    open,
    show: () => {
      // A second entry would leave one Back short of closing the sheet.
      if (open || previewOf(stateNow()) === link) return;
      navigate({ pathname, search, hash }, { state: { preview: link } });
    },
    close: leave,
    join: () => {
      leave();
      openLink(link);
    },
  };
}
