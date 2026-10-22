import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { hapticSuccess } from '@/hooks/useTelegram';
import { api } from '@/lib/api';

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
  open,
  onClose,
  onDeleted,
}: {
  requestId: number;
  /** Only an open request can be closed; any can be deleted. */
  open: boolean;
  onClose: () => void;
  /** The request is gone, and a screen showing it has nothing left to show. */
  onDeleted?: () => void;
}) {
  const { t } = useLingui();
  const queryClient = useQueryClient();

  const remove = useMutation({
    mutationFn: async (how: 'close' | 'delete') => {
      if (how === 'close') await api.closeRequest(requestId);
      else await api.deleteRequest(requestId);
    },
    onSuccess: (_, how) => {
      hapticSuccess();
      void queryClient.invalidateQueries({ queryKey: ['requests'] });
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
      {open ? (
        <Pick
          leading={
            <Tile tone={1}>
              <CloseIcon size={19} />
            </Tile>
          }
          name={<Trans>Закрыть</Trans>}
          hint={<Trans>уйдёт из ленты, отклики и переписка сохранятся</Trans>}
          disabled={remove.isPending}
          onClick={() => remove.mutate('close')}
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
        onClick={() => remove.mutate('delete')}
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
