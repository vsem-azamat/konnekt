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
        <svg className={css.logo} viewBox="0 0 100 100" role="img" aria-label="Konnekt">
          <rect className={css.tile} width="100" height="100" rx="26" strokeWidth="3" />
          <path d="M0 50H100V74Q100 100 74 100H26Q0 100 0 74Z" fill="#d7141a" />
          <path d="M0 26Q0 0 26 0H30L62 50 30 100H26Q0 100 0 74Z" fill="#11457e" />
        </svg>
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
