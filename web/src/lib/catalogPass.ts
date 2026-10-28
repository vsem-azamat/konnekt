/**
 * Opens a catalog chat's link, after telling supervisor who is going.
 *
 * Telegram signed who is asking, which is all the join captcha wants to know,
 * so the join request that follows is let in without one. The call is sent
 * first and never waited on: a failure, or no initData, only means the captcha
 * is asked as it always was. A chat we do not run has nothing to skip.
 */
export function joinFromCatalog(
  chat: { link: string; external: boolean },
  {
    initData,
    claim,
    openLink,
  }: {
    initData: () => string | undefined;
    claim: (initData: string, link: string) => Promise<unknown>;
    openLink: (link: string) => unknown;
  },
): void {
  const raw = initData();
  if (raw && !chat.external) {
    try {
      void claim(raw, chat.link).catch(() => undefined);
    } catch {
      // Opening the link matters more than the pass.
    }
  }
  openLink(chat.link);
}
