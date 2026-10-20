import { Trans } from '@lingui/react/macro';
import { useLocation } from 'react-router';

import { loginProblem } from './browser';
import css from './Login.module.css';

/**
 * Where a browser starts. Not a console screen: it has to open for someone who
 * is not signed in, so it carries no `ConsoleGate`.
 *
 * The button is a link to webapi, which sends the browser to Telegram and
 * brings it back with a session or with `?error=`.
 */
export default function LoginPage() {
  const { search } = useLocation();
  const problem = loginProblem(search);

  return (
    <main className={css.page}>
      <div className={css.box}>
        <span className={css.wordmark}>Konnekt</span>
        <h1 className={css.title}>
          <Trans>Вход в консоль</Trans>
        </h1>

        {problem === 'not_admin' ? (
          <p className={css.problem} role="alert">
            <Trans>
              Этого аккаунта нет среди администраторов. Войдите другим аккаунтом Telegram
              или попросите владельца добавить вас.
            </Trans>
          </p>
        ) : null}
        {problem === 'failed' ? (
          <p className={css.problem} role="alert">
            <Trans>Войти не получилось. Попробуйте ещё раз.</Trans>
          </p>
        ) : null}

        <a className={css.cta} href="/api/auth/telegram/login">
          <Trans>Войти через Telegram</Trans>
        </a>

        <p className={css.note}>
          <Trans>
            Откроется страница Telegram, где нужно подтвердить вход. Пароль мы не просим и
            не храним. В приложении Telegram консоль открывается без этого шага.
          </Trans>
        </p>
      </div>
    </main>
  );
}
