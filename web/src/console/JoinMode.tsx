import { Trans, useLingui } from '@lingui/react/macro';

import { Segmented, ui } from '@/components/Ui';

import { joinsDirectly } from './chats';
import css from './JoinMode.module.css';
import type { ConsoleChatDetail, JoinMode } from './session';

/**
 * Who lets a person into the chat: everyone, the captcha or the admins, with
 * what the choice means under it.
 *
 * A public chat that does not approve new members sends no request to decide
 * on, so there is nothing to choose there until Telegram's setting changes.
 */
export function JoinModeRow({
  chat,
  busy,
  onChange,
}: {
  chat: Pick<ConsoleChatDetail, 'join_mode' | 'join_by_request' | 'public_link'>;
  busy: boolean;
  onChange: (mode: JoinMode) => void;
}) {
  const { t } = useLingui();
  if (joinsDirectly(chat)) {
    return (
      <div className={`${ui.row} ${css.row}`}>
        <div className={css.line}>
          <span className={ui.rowName}>
            <Trans>Вступление</Trans>
          </span>
          <span className={css.value}>
            <Trans>Входят сразу</Trans>
          </span>
        </div>
        <p className={ui.hint}>
          <Trans>
            Капча и «Решают админы» работают только с заявками: включите «Одобрение новых
            участников» в настройках чата в Telegram.
          </Trans>
        </p>
      </div>
    );
  }
  return (
    <div className={`${ui.row} ${css.row}`}>
      <span className={ui.rowName}>
        <Trans>Вступление</Trans>
      </span>
      <Segmented<JoinMode>
        value={chat.join_mode}
        label={t`Вступление`}
        disabled={busy}
        onChange={(mode) => mode !== chat.join_mode && onChange(mode)}
        options={[
          { value: 'open', label: <Trans>Пускать всех</Trans> },
          { value: 'captcha', label: <Trans>Капча</Trans> },
          { value: 'admins', label: <Trans>Решают админы</Trans> },
        ]}
      />
      <p className={ui.hint}>
        {chat.join_mode === 'open' ? (
          <Trans>
            Входят без проверки: заявки бот одобряет сразу, а его ссылка в чат — без
            заявки.
          </Trans>
        ) : chat.join_mode === 'captcha' ? (
          <Trans>
            Бот задаёт в личке вопрос и одобряет заявку за верный ответ. Кто прошёл капчу
            за последние 90 дней, входит без вопроса.
          </Trans>
        ) : (
          <Trans>Бот заявки не трогает: их одобряют админы в Telegram.</Trans>
        )}
      </p>
    </div>
  );
}
