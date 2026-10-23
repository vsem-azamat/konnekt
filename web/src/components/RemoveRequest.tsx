import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { hapticSuccess } from '@/hooks/useTelegram';
import { ApiError, api } from '@/lib/api';
import type { HelpRequest } from '@/lib/types';

import { CloseIcon, TrashIcon } from './icons';
import { Pick, Sheet } from './Sheet';
import { Action, Actions, Reason, Tile } from './Ui';

/**
 * «Убрать заявку»: close it, or delete it for good.
 *
 * Two answers because they leave different things behind. A closed request
 * leaves the feed but keeps its responses, and the people who answered can
 * still be written to; a deleted one takes the responses with it. The same
 * sheet opens from the card in the list and from «⋯» on the request.
 */
export function RemoveRequest({
  requestId,
  canClose,
  onClose,
  onDeleted,
}: {
  requestId: number;
  /** Only an open request can be closed; any can be deleted. */
  canClose: boolean;
  onClose: () => void;
  /** The request is gone, and a screen showing it has nothing left to show. */
  onDeleted?: () => void;
}) {
  const { t } = useLingui();
  const queryClient = useQueryClient();

  // The list is changed here rather than only refetched: until the refetch
  // lands, a closed card would still offer «Закрыть». A request already gone
  // (deleted on another device) is treated as deleted.
  const remove = useMutation({
    mutationFn: async (how: 'close' | 'delete'): Promise<HelpRequest | null> => {
      if (how === 'close') return api.closeRequest(requestId);
      try {
        await api.deleteRequest(requestId);
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 404)) throw error;
      }
      return null;
    },
    onSuccess: (closed) => {
      hapticSuccess();
      queryClient.setQueryData<HelpRequest[]>(['requests'], (rows) =>
        closed
          ? rows?.map((row) => (row.id === closed.id ? closed : row))
          : rows?.filter((row) => row.id !== requestId),
      );
      if (!closed) queryClient.removeQueries({ queryKey: ['responses', requestId] });
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['requests'] }),
  });

  // Per call rather than on the mutation: these touch the screen, and the
  // person may have left it (Telegram's Back still works) before the answer.
  const run = (how: 'close' | 'delete') =>
    remove.mutate(how, {
      onSuccess: () => {
        onClose();
        if (how === 'delete') onDeleted?.();
      },
    });

  return (
    <Sheet
      title={t`Убрать заявку`}
      closeLabel={t`Отмена`}
      // Not while the answer is on its way: closing then would look like a
      // cancel, and the request would be gone anyway.
      onClose={() => {
        if (!remove.isPending) onClose();
      }}
    >
      {canClose ? (
        <Pick
          leading={
            <Tile tone={1}>
              <CloseIcon size={19} />
            </Tile>
          }
          name={<Trans context="request">Закрыть</Trans>}
          hint={<Trans>уйдёт из ленты, отклики и переписка сохранятся</Trans>}
          disabled={remove.isPending}
          onClick={() => run('close')}
        />
      ) : null}
      <Pick
        leading={
          <Tile tone={4}>
            <TrashIcon size={19} />
          </Tile>
        }
        name={<Trans>Удалить насовсем</Trans>}
        hint={<Trans>заявка и отклики пропадут, вернуть нельзя</Trans>}
        disabled={remove.isPending}
        danger
        onClick={() => run('delete')}
      />
      {remove.isError ? (
        <Reason weak>
          <Trans>Не получилось связаться. Попробуй ещё раз.</Trans>
        </Reason>
      ) : null}
      <Actions>
        <Action quiet onClick={onClose} disabled={remove.isPending}>
          <Trans>Отмена</Trans>
        </Action>
      </Actions>
    </Sheet>
  );
}
