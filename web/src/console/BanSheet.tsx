import { Trans, useLingui } from '@lingui/react/macro';
import { type ReactNode, useId, useState } from 'react';

import { Sheet } from '@/components/Sheet';
import { Action, Actions, Hint, Sub, ui } from '@/components/Ui';
import { type BanChoice, revokeMessages } from '@/console/ban';

/**
 * A ban in every chat the bot moderates, as /banall is. Keeping the messages
 * is the default; deleting them cannot be undone, so it is the red choice
 * and goes only once the word is typed.
 */
export function BanSheet({
  name,
  note,
  busy,
  error,
  onBan,
  onClose,
}: {
  name: string;
  /** What the screen that asks knows about them, under the title. */
  note?: ReactNode;
  busy: boolean;
  error?: ReactNode;
  onBan: (revokeMessages: boolean) => void;
  onClose: () => void;
}) {
  const { t } = useLingui();
  const [choice, setChoice] = useState<BanChoice>('ban');
  const [typed, setTyped] = useState('');
  const hintId = useId();
  const word = t`стереть`;
  const wipe = choice === 'wipe';
  const revoke = revokeMessages(choice, typed, word);

  return (
    <Sheet title={t`Забанить ${name}?`} closeLabel={t`Отмена`} onClose={onClose}>
      <Sub>
        <Trans>Бан во всех наших чатах. Снять можно в «Чёрном списке».</Trans>
        {note ? <> {note}</> : null}
      </Sub>
      {/* A fieldset, so a ban on its way holds every choice in it. */}
      <fieldset className={ui.banChoices} disabled={busy} aria-label={t`Как забанить`}>
        <label className={ui.banOption}>
          <input
            type="radio"
            name="ban"
            checked={!wipe}
            onChange={() => {
              // The word confirms one wipe; it does not wait for the next.
              setChoice('ban');
              setTyped('');
            }}
          />
          <span>
            <b>
              <Trans>Только забанить</Trans>
            </b>
            <span className={ui.banOptionHint}>
              <Trans>Сообщения останутся.</Trans>
            </span>
          </span>
        </label>
        <label className={`${ui.banOption} ${ui.banOptionDanger}`}>
          <input
            type="radio"
            name="ban"
            checked={wipe}
            onChange={() => setChoice('wipe')}
          />
          <span>
            <b>
              <Trans>Забанить и стереть все его сообщения</Trans>
            </b>
            <span className={ui.banOptionHint}>
              <Trans>Во всех чатах, за всё время. Отменить нельзя.</Trans>
            </span>
          </span>
        </label>
        {wipe ? (
          <>
            <Hint>
              <span id={hintId}>
                <Trans>
                  Для стирания: введите <b>{word}</b>, чтобы подтвердить.
                </Trans>
              </span>
            </Hint>
            <div className={ui.field}>
              <input
                value={typed}
                onChange={(event) => setTyped(event.target.value)}
                placeholder={word}
                aria-label={t`Подтверждение`}
                aria-describedby={hintId}
                autoCapitalize="off"
                autoComplete="off"
                autoCorrect="off"
                spellCheck={false}
                style={{ all: 'unset', flex: 1, minWidth: 0 }}
              />
            </div>
          </>
        ) : null}
      </fieldset>
      {error ? <Hint>{error}</Hint> : null}
      <Actions>
        <Action quiet onClick={onClose}>
          <Trans>Отмена</Trans>
        </Action>
        <Action
          danger={wipe}
          disabled={busy || revoke === null}
          onClick={() => {
            if (revoke !== null) onBan(revoke);
          }}
        >
          {wipe ? <Trans>Забанить и стереть</Trans> : <Trans>Забанить</Trans>}
        </Action>
      </Actions>
    </Sheet>
  );
}
