import { Trans } from '@lingui/react/macro';
import { Link } from 'react-router';

import css from './Login.module.css';

/**
 * The browser's catch-all. Not the Mini App's: that one draws the Telegram
 * header, which asks the catalog who is looking, and a browser has no answer.
 */
export default function BrowserNotFound() {
  return (
    <main className={css.page}>
      <div className={css.box}>
        <h1 className={css.title}>
          <Trans>Такой страницы нет</Trans>
        </h1>
        <p className={css.note}>
          <Trans>Ссылка устарела или в ней опечатка.</Trans>
        </p>
        <Link className={css.cta} to="/console">
          <Trans>В консоль</Trans>
        </Link>
      </div>
    </main>
  );
}
