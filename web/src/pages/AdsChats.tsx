import { Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';

import { AdsContact } from '@/components/AdsContact';
import { AppHeader } from '@/components/AppHeader';
import {
  Label,
  Letters,
  Row,
  Rows,
  Screen,
  SkeletonRows,
  Sub,
  Tile,
  Title,
  ui,
} from '@/components/Ui';
import { reachQuery } from '@/lib/api';
import { initials } from '@/lib/chats';
import { reachFigures } from '@/lib/reach';

/**
 * A post in the chats: where it goes and how many people are there.
 *
 * Per group: a sum is what an advertiser asks about. Each chat's own size is
 * in its preview on the Chats tab.
 */
export default function AdsChatsPage() {
  const { i18n } = useLingui();
  const { data, isPending, isError, refetch } = useQuery(reachQuery);
  const figures = data ? reachFigures(data) : null;
  const counted = figures?.members != null;

  return (
    <Screen>
      <AppHeader />
      <Title>
        <Trans>Пост в чатах</Trans>
      </Title>
      <div style={{ marginTop: 6 }}>
        <Sub>
          <Trans>Выходит в выбранных чатах один раз. Где он уместен, подскажем.</Trans>
        </Sub>
      </div>

      <Label aside={counted ? <Trans>чатов · людей</Trans> : <Trans>чатов</Trans>}>
        <Trans>Куда попадёт</Trans>
      </Label>
      {isPending ? (
        <SkeletonRows count={4} />
      ) : isError || !figures ? (
        <Rows>
          <Row
            title={<Trans>Не удалось загрузить охват</Trans>}
            hint={<Trans>Нажмите, чтобы попробовать ещё раз</Trans>}
            onClick={() => void refetch()}
          />
        </Rows>
      ) : (
        <Rows>
          {figures.groups.map((group, index) => (
            <Row
              key={group.name}
              leading={
                <Tile tone={index}>
                  <Letters text={initials(group.name)} />
                </Tile>
              }
              title={group.name}
              trailing={
                <span className={ui.figure}>
                  <b>{group.chats}</b>
                  {group.members != null ? (
                    <small>{group.members.toLocaleString(i18n.locale)}</small>
                  ) : null}
                </span>
              }
            />
          ))}
        </Rows>
      )}

      <Label>
        <Trans>Как это работает</Trans>
      </Label>
      <ol className={ui.steps}>
        <li>
          <Trans>Пишете, что хотите разместить.</Trans>
        </li>
        <li>
          <Trans>Отвечаем, в каких чатах это уместно и сколько стоит.</Trans>
        </li>
        <li>
          <Trans>Пост выходит, вы получаете ссылки на него.</Trans>
        </li>
      </ol>

      <AdsContact />
    </Screen>
  );
}
