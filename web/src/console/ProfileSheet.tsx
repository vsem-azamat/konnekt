import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import { Sheet } from '@/components/Sheet';
import { Action, Actions, Hint, Letters, Sub, Tile, ui } from '@/components/Ui';
import { FailureText } from '@/console/FailureText';
import { profileActions } from '@/console/profile';
import { adminCatalogQuery, adminProfileQuery } from '@/console/queries';
import { daysSince } from '@/console/session';
import { hapticSelection } from '@/hooks/useTelegram';
import { ApiError, api } from '@/lib/api';

/**
 * A catalog profile in the console, with what an operator does about it:
 * keep it, hide it (asked once more), or see it as students do. A hidden one
 * only comes back. The owner is told nothing either way.
 */
export function ProfileSheet({
  userId,
  onClose,
}: {
  userId: number;
  onClose: () => void;
}) {
  const { t } = useLingui();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const profile = useQuery(adminProfileQuery(userId));
  const [confirmHide, setConfirmHide] = useState(false);

  const change = useMutation({
    mutationFn: (action: 'keep' | 'hide' | 'restore') =>
      action === 'keep'
        ? api.keepProfile(userId)
        : action === 'hide'
          ? api.hideProfile(userId)
          : api.restoreProfile(userId),
    onSuccess: async (updated) => {
      queryClient.setQueryData(adminProfileQuery(userId).queryKey, updated);
      await queryClient.invalidateQueries({ queryKey: adminCatalogQuery.queryKey });
      onClose();
    },
    // Changed meanwhile, by its owner or another operator: show it as it is.
    onError: (error) => {
      if (!stale(error)) return;
      setConfirmHide(false);
      void queryClient.invalidateQueries({
        queryKey: adminProfileQuery(userId).queryKey,
      });
      void queryClient.invalidateQueries({ queryKey: adminCatalogQuery.queryKey });
    },
  });
  const failure = change.error ? (
    <Hint>
      {stale(change.error) ? (
        <Trans>Анкету уже изменили: вот какая она сейчас.</Trans>
      ) : (
        <FailureText error={change.error} />
      )}
    </Hint>
  ) : null;

  const data = profile.data;
  const name = data?.name ?? '';

  if (confirmHide && data) {
    return (
      <Sheet title={t`Скрыть анкету ${name}?`} closeLabel={t`Отмена`} onClose={onClose}>
        <Sub>
          <Trans>
            Она пропадёт из каталога и поиска, и автор не сможет опубликовать её снова.
            Вернуть её можно здесь же, в «Скрытых». Автору мы ничего не пишем.
          </Trans>
        </Sub>
        {failure}
        <Actions>
          <Action
            quiet
            onClick={() => {
              change.reset();
              setConfirmHide(false);
            }}
          >
            <Trans>Отмена</Trans>
          </Action>
          <Action disabled={change.isPending} onClick={() => change.mutate('hide')}>
            <Trans>Скрыть</Trans>
          </Action>
        </Actions>
      </Sheet>
    );
  }

  return (
    <Sheet title={t`Анкета`} closeLabel={t`Закрыть`} onClose={onClose}>
      {profile.isPending ? (
        <Hint>
          <Trans>Загружаем анкету…</Trans>
        </Hint>
      ) : !data ? (
        <Hint>
          <FailureText error={profile.error} />
        </Hint>
      ) : (
        <>
          <div className={ui.profileTop}>
            <Tile tone={2}>
              <Letters text={name.slice(0, 1).toUpperCase()} />
            </Tile>
            <div>
              <b>{name}</b>
              <Sub>
                {[data.services.join(', '), data.institution].filter(Boolean).join(' · ')}
                {data.status === 'published' && data.published_at ? (
                  <>
                    {data.services.length || data.institution ? ' · ' : null}
                    <Age
                      publishedAt={data.published_at}
                      reviewed={data.reviewed_at !== null}
                    />
                  </>
                ) : null}
              </Sub>
            </div>
          </div>
          {data.headline ? <b className={ui.profileHeadline}>{data.headline}</b> : null}
          {data.about ? <blockquote className={ui.quote}>{data.about}</blockquote> : null}
          {data.status === 'banned' ? (
            <Hint>
              <Trans>Скрыта из каталога: автор не может опубликовать её сам.</Trans>
            </Hint>
          ) : data.status !== 'published' ? (
            <Hint>
              <Trans>Автор сам снял анкету или ещё не опубликовал её.</Trans>
            </Hint>
          ) : null}
          {failure}
          <div className={ui.actionsStacked}>
            {profileActions(data).map((action) =>
              action === 'keep' ? (
                <Action
                  key={action}
                  disabled={change.isPending}
                  onClick={() => {
                    hapticSelection();
                    change.mutate('keep');
                  }}
                >
                  <Trans>Оставить</Trans>
                </Action>
              ) : action === 'hide' ? (
                <Action key={action} quiet onClick={() => setConfirmHide(true)}>
                  <Trans>Скрыть из каталога…</Trans>
                </Action>
              ) : action === 'view' ? (
                <Action key={action} quiet onClick={() => navigate(`/helper/${userId}`)}>
                  <Trans>Как видят ученики</Trans>
                </Action>
              ) : (
                <Action
                  key={action}
                  disabled={change.isPending}
                  onClick={() => change.mutate('restore')}
                >
                  <Trans>Вернуть в каталог</Trans>
                </Action>
              ),
            )}
          </div>
        </>
      )}
    </Sheet>
  );
}

const stale = (error: unknown) => error instanceof ApiError && error.status === 409;

/** «новая, вчера»: how long it has been out, and whether anyone looked. */
function Age({ publishedAt, reviewed }: { publishedAt: string; reviewed: boolean }) {
  const days = daysSince(publishedAt);
  const when =
    days === 0 ? (
      <Trans>сегодня</Trans>
    ) : days === 1 ? (
      <Trans>вчера</Trans>
    ) : (
      <Trans>{days} дн назад</Trans>
    );
  return reviewed ? when : <Trans>новая, {when}</Trans>;
}
