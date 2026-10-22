import { Trans } from '@lingui/react/macro';

import { AppHeader } from '@/components/AppHeader';
import { Row, Rows, Screen } from '@/components/Ui';

/**
 * What a screen that threw while rendering shows in its place.
 *
 * Without it React Router shows its own page, meant for developers, in English.
 * The error is already reported: React tells `createRoot`'s `onCaughtError` of
 * every error a boundary catches, this one's included.
 *
 * Asking again reloads the app rather than the screen. A render error is
 * rarely a fluke, and the likeliest one that is — a bundle older than the API
 * it reads — is what a reload fixes.
 */
export function RouteError() {
  return (
    <Screen>
      <AppHeader />
      <div style={{ height: 16 }} />
      <Rows>
        <Row
          title={<Trans>Не удалось загрузить</Trans>}
          hint={<Trans>Нажми, чтобы попробовать ещё раз</Trans>}
          onClick={() => window.location.reload()}
        />
      </Rows>
    </Screen>
  );
}
