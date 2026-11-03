import { Trans } from '@lingui/react/macro';

import { botEntry, siteEntry } from '@/lib/siteEntry';
import css from './OpenInTelegram.module.css';

/**
 * The app's host opened in a browser that is not sent on to the site, because
 * it was sent there moments ago (lib/siteEntry.ts). The app runs only inside
 * Telegram, so this says so and offers the two ways on: into the bot, or to
 * the site.
 */
export default function OpenInTelegram({ site }: { site: string }) {
  return (
    <main className={css.screen}>
      <div className={css.column}>
        <img className={css.logo} src="/favicon.svg" alt="Konnekt" />
        <h1 className={css.title}>
          <Trans>Konnekt открывается в Telegram</Trans>
        </h1>
        <div className={css.actions}>
          <a className={css.primary} href={botEntry(site)}>
            <Trans>Открыть Konnekt</Trans>
          </a>
          <a className={css.secondary} href={siteEntry(site)}>
            <Trans>На сайт</Trans>
          </a>
        </div>
      </div>
    </main>
  );
}
