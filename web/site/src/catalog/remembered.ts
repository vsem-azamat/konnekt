/**
 * An answer kept for `ttl`, and past it for as long as its source fails.
 *
 * The catalog pages are rendered per request and Cloudflare keeps each for
 * ten minutes, so a source is asked at most once a minute however many pages
 * miss at once. When it fails, the last good answer stands: the API being
 * down is not the catalogue being empty, and a page of yesterday's chats is
 * better than an error. Only with nothing to fall back on does the failure
 * reach the page.
 */
export function remembered<T>(
  load: () => Promise<T>,
  { ttl, now = Date.now }: { ttl: number; now?: () => number },
): () => Promise<T> {
  let kept: { value: T; at: number } | null = null;
  let pending: Promise<T> | null = null;
  return async () => {
    if (kept && now() - kept.at < ttl) return kept.value;
    // One request at a time: a burst of misses waits for the same answer.
    pending ??= load()
      .then((value) => {
        kept = { value, at: now() };
        return value;
      })
      .finally(() => {
        pending = null;
      });
    try {
      return await pending;
    } catch (error) {
      if (kept) return kept.value;
      throw error;
    }
  };
}
