import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import { HIDE_REASONS, HideReasonText } from '@/components/HideReasonText';
import { Sheet } from '@/components/Sheet';
import { Action, Actions, Hint, Letters, Sub, Tile, ui } from '@/components/Ui';
import { FailureText } from '@/console/FailureText';
import { HIDE_NOTE_MAX, hideBody, profileActions } from '@/console/profile';
import { adminCatalogQuery, adminProfileQuery } from '@/console/queries';
import { daysSince } from '@/console/session';
import { hapticSelection } from '@/hooks/useTelegram';
import { ApiError, api } from '@/lib/api';
import type { AdminHide, HideReason } from '@/lib/generated/types.gen';

/**
 * A catalog profile in the console, with what an operator does about it:
 * keep it, hide it (asked once more, and why), or see it as students do. A
 * hidden one comes back, or, once its owner has changed it, stays hidden on
 * purpose. Nobody messages the owner; «Моя анкета» shows them it was hidden
 * and why.
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
  const [reason, setReason] = useState<HideReason | null>(null);
  const [note, setNote] = useState('');
  const why = hideBody(reason, note);

  const change = useMutation({
    // Keeping and restoring approve what is on screen: an owner's save since
    // is a 409, and the sheet then shows the profile as it is now.
    mutationFn: (action: 'keep' | { hide: AdminHide } | 'restore') =>
      action === 'keep'
        ? api.keepProfile(userId, { seen: profile.data?.updated_at })
        : action === 'restore'
          ? api.restoreProfile(userId, { seen: profile.data?.updated_at })
          : api.hideProfile(userId, action.hide),
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
            Вернуть её можно здесь же, в «Скрытых». Автору мы не пишем, но в «Моей анкете»
            будет видно, что её скрыли, и причина.
          </Trans>
        </Sub>
        <fieldset
          className={ui.banChoices}
          disabled={change.isPending}
          aria-label={t`Причина`}
        >
          {HIDE_REASONS.map((option) => (
            <label key={option} className={ui.banOption}>
              <input
                type="radio"
                name="hide-reason"
                checked={reason === option}
                onChange={() => setReason(option)}
              />
              <span>
                <b>
                  <HideReasonText reason={option} />
                </b>
              </span>
            </label>
          ))}
          {reason === 'other' ? (
            <div className={ui.field}>
              <input
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder={t`Что не так, своими словами`}
                aria-label={t`Причина своими словами`}
                maxLength={HIDE_NOTE_MAX}
                style={{ all: 'unset', width: '100%' }}
              />
            </div>
          ) : null}
        </fieldset>
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
          <Action
            disabled={change.isPending || why === null}
            onClick={() => why && change.mutate({ hide: why })}
          >
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
              {data.hidden_reason === 'other' && data.hidden_note ? (
                <Trans>Скрыта из каталога: «{data.hidden_note}».</Trans>
              ) : data.hidden_reason ? (
                <Trans>
                  Скрыта из каталога: <HideReasonText reason={data.hidden_reason} />.
                </Trans>
              ) : (
                <Trans>Скрыта из каталога.</Trans>
              )}{' '}
              {data.reviewed_at === null ? (
                <Trans>Автор изменил её после этого: вернуть или оставить скрытой?</Trans>
              ) : (
                <Trans>Автор может её править, но не опубликовать сам.</Trans>
              )}
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
                  // Next to «Вернуть», leaving it hidden is the second choice.
                  quiet={data.status === 'banned'}
                  disabled={change.isPending}
                  onClick={() => {
                    hapticSelection();
                    change.mutate('keep');
                  }}
                >
                  {data.status === 'banned' ? (
                    <Trans>Оставить скрытой</Trans>
                  ) : (
                    <Trans>Оставить</Trans>
                  )}
                </Action>
              ) : action === 'hide' ? (
                <Action
                  key={action}
                  quiet
                  onClick={() => {
                    setReason(null);
                    setNote('');
                    setConfirmHide(true);
                  }}
                >
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
