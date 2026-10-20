/**
 * A chat's preview sheet, kept in the router's history.
 *
 * Opening it pushes an entry for the same address carrying the chat's link,
 * so Back — Telegram's button, or Android's own, which on the first screen
 * would otherwise close the whole Mini App — closes the sheet and nothing
 * else. Every way out of the sheet goes back one entry rather than forward,
 * or the entry would stay behind and Back would reopen it.
 */

interface Place {
  pathname: string;
  search: string;
  hash: string;
  state: unknown;
}

interface Router {
  navigate: {
    (delta: number): unknown;
    (
      to: { pathname: string; search: string; hash: string },
      options: { state: unknown },
    ): unknown;
  };
  /** Leaves for Telegram. Only `join`, the sheet's button, calls it. */
  openLink: (link: string) => unknown;
}

function previewOf(state: unknown): string | null {
  if (state === null || typeof state !== 'object') return null;
  const { preview } = state as { preview?: unknown };
  return typeof preview === 'string' ? preview : null;
}

export function chatPreview(link: string, place: Place, { navigate, openLink }: Router) {
  return {
    open: previewOf(place.state) === link,
    show: () => {
      const { pathname, search, hash } = place;
      navigate({ pathname, search, hash }, { state: { preview: link } });
    },
    close: () => {
      navigate(-1);
    },
    join: () => {
      navigate(-1);
      openLink(link);
    },
  };
}
