import { Plural, Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router';
import { AppHeader } from '@/components/AppHeader';
import { Incoming } from '@/components/Incoming';
import { DocumentIcon, iconForService } from '@/components/icons';
import { formatDay } from '@/components/Phrase';
import {
  Action,
  AvatarStack,
  Card,
  Cards,
  CLAMP_TWO_LINES,
  Empty,
  Reason,
  Screen,
  Segmented,
  SkeletonRows,
  Tile,
  Title,
  ui,
} from '@/components/Ui';
import { hapticSelection } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import { requestName } from '@/lib/requestHeading';
import type { HelpRequest } from '@/lib/types';

type Tab = 'mine' | 'incoming';

/**
 * Both directions of the same relationship.
 *
 * What you asked for, and — if you are also a helper — what other people are
 * asking for. One screen rather than two tabs: the two are the same person's
 * business, and most people will only ever see the first.
 *
 * The title names what is on the screen. "Мои" answers neither "whose" nor
 * "what", and a tab label is the one place there is no room to explain.
 */
export default function MinePage() {
  const navigate = useNavigate();
  const { i18n } = useLingui();
  // In the URL, so the notification that brings a helper back can land on the
  // right half and a reload does not lose it.
  const [params, setParams] = useSearchParams();

  const me = useQuery({ queryKey: ['me'], queryFn: ({ signal }) => api.getMe(signal) });
  const isHelper = me.data?.is_helper ?? false;

  // Forced back to 'mine' for someone who is not a helper: the control that
  // switches back is only rendered for helpers, so /mine?tab=incoming would
  // otherwise strand them on "fill in your profile" with no way out.
  const tab: Tab = isHelper && params.get('tab') === 'incoming' ? 'incoming' : 'mine';

  const switchTo = (next: Tab) => {
    // Rebuilt from the current params rather than replaced: a wholesale
    // object drops every other search parameter on the screen.
    const updated = new URLSearchParams(params);
    if (next === 'mine') updated.delete('tab');
    else updated.set('tab', next);
    setParams(updated, { replace: true });
  };

  const { data, isPending, isError } = useQuery({
    queryKey: ['requests'],
    queryFn: ({ signal }) => api.getRequests(signal),
  });

  return (
    <Screen>
      <AppHeader />
      <Title>
        <Trans>Заявки</Trans>
      </Title>

      {isHelper ? (
        <div style={{ marginTop: 14 }}>
          <Segmented<Tab>
            value={tab}
            onChange={switchTo}
            options={[
              { value: 'mine', label: <Trans>Мои заявки</Trans> },
              { value: 'incoming', label: <Trans>Входящие</Trans> },
            ]}
          />
        </div>
      ) : null}

      {/* The title already says «Заявки»; a section label repeating it under
            the same words told the reader nothing. */}
      <div style={{ height: 14 }} />

      {tab === 'incoming' ? (
        <Incoming />
      ) : isPending ? (
        <SkeletonRows count={2} />
      ) : isError ? (
        <Empty title={<Trans>Не получилось загрузить</Trans>} />
      ) : data.length === 0 ? (
        <Empty
          title={<Trans>Заявок пока нет</Trans>}
          body={
            <Trans>
              Опиши, что нужно, и получай отклики — вместо того чтобы искать самому.
            </Trans>
          }
          action={
            <Action
              onClick={() => {
                hapticSelection();
                navigate('/ask');
              }}
            >
              <Trans>Мне нужна помощь</Trans>
            </Action>
          }
        />
      ) : (
        <Cards>
          {data.map((request) => (
            <RequestCard
              key={request.id}
              request={request}
              locale={i18n.locale}
              onClick={() => navigate(`/request/${request.id}`)}
            />
          ))}
        </Cards>
      )}
    </Screen>
  );
}

function RequestCard({
  request,
  locale,
  onClick,
}: {
  request: HelpRequest;
  locale: string;
  onClick: () => void;
}) {
  const Icon = request.service_type ? iconForService('tutoring') : DocumentIcon;
  const title = requestName(request) ?? request.text;

  return (
    <Card onClick={onClick}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        <Tile tone={request.id % 6}>
          <Icon size={19} />
        </Tile>
        <div style={{ minWidth: 0 }}>
          <div
            style={{
              fontSize: 14.5,
              fontWeight: 680,
              letterSpacing: '-0.015em',
              // A request with no subject is titled by its own text, which can
              // run to a thousand characters; the card opens to the whole of it.
              ...CLAMP_TWO_LINES,
            }}
          >
            {title}
          </div>
          <div style={{ marginTop: 2, fontSize: 12, color: 'var(--muted)' }}>
            {request.deadline_on ? (
              <Trans>до {formatDay(request.deadline_on, locale)}</Trans>
            ) : (
              <Trans>без срока</Trans>
            )}
          </div>
        </div>
      </div>

      {request.responses_count > 0 ? (
        <div className={ui.reasonRow}>
          <Reason>
            <Plural
              value={request.responses_count}
              one="# отклик"
              few="# отклика"
              many="# откликов"
              other="# отклика"
            />
          </Reason>
          <AvatarStack avatars={request.responders} />
        </div>
      ) : (
        <Reason weak>
          <Trans>Пока без откликов</Trans>
        </Reason>
      )}
    </Card>
  );
}
