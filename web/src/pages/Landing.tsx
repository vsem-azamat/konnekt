import { Trans } from '@lingui/react/macro';

import css from './Landing.module.css';

/**
 * What the domain shows a browser.
 *
 * The catalog itself only works inside Telegram — that is where the accounts,
 * the conversations and the notifications are — so a page that tried to be a
 * second front door would be a page that lies. This one has a single job:
 * say what is behind the door and open it.
 *
 * The button points at the API rather than at a `t.me` address of its own.
 * The handle then exists in exactly one place, the bot token the server is
 * already running with, instead of being copied into the frontend and into
 * the build.
 */
export default function LandingPage() {
  return (
    <main className={css.page}>
      <span className={css.wordmark}>Konnekt</span>

      <h1 className={css.headline}>
        <Trans>Кто поможет с учёбой в Чехии</Trans>
      </h1>

      <p className={css.sub}>
        <Trans>
          Репетиторы, подготовка к вступительным экзаменам, помощь на экзамене и
          нострификация — от студентов, которые это уже прошли.
        </Trans>
      </p>

      <div className={css.chips}>
        <span
          className={css.chip}
          style={{ background: 'var(--tone-0-bg)', color: 'var(--tone-0-fg)' }}
        >
          <Trans>Репетиторы</Trans>
        </span>
        <span
          className={css.chip}
          style={{ background: 'var(--tone-3-bg)', color: 'var(--tone-3-fg)' }}
        >
          <Trans>Вступительные экзамены</Trans>
        </span>
        <span
          className={css.chip}
          style={{ background: 'var(--tone-1-bg)', color: 'var(--tone-1-fg)' }}
        >
          <Trans>Нострификация</Trans>
        </span>
        <span
          className={css.chip}
          style={{ background: 'var(--tone-2-bg)', color: 'var(--tone-2-fg)' }}
        >
          <Trans>Работы</Trans>
        </span>
      </div>

      {/* A plain link, not a fetch and a redirect: it works before the bundle
          has finished loading, and it is what a browser knows how to do. */}
      <a className={css.cta} href="/api/v1/open">
        <Trans>Открыть в Telegram</Trans>
      </a>

      <p className={css.foot}>
        <Trans>
          Регистрации нет — заходишь своим аккаунтом Telegram. Помогать другим можно
          оттуда же.
        </Trans>
      </p>
    </main>
  );
}
