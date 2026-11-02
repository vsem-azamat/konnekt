import { Trans, useLingui } from '@lingui/react/macro';
import type { ReactNode } from 'react';
import { CheckIcon, WarningIcon } from '@/components/icons';
import { Sheet } from '@/components/Sheet';
import { Chevron, Hint, Row, Rows, ui } from '@/components/Ui';
import css from '@/console/BotInChat.module.css';
import {
  type BotRights,
  botStanding,
  missingRights,
  rightsChange,
  type Standing as StandingKind,
  type UsedRight,
} from '@/console/botState';
import { PersonFace } from '@/console/Faces';
import {
  type BotChange,
  type ChatAdmin,
  type ConsoleChatDetail,
  personName,
  utc,
} from '@/console/session';

/** Each right the bot works with: its name in Telegram's settings, and what stops without it. */
function RightName({ right }: { right: UsedRight }) {
  switch (right) {
    case 'can_delete_messages':
      return <Trans>Удалять сообщения</Trans>;
    case 'can_restrict_members':
      return <Trans>Блокировать участников</Trans>;
    case 'can_invite_users':
      return <Trans>Пригласительные ссылки</Trans>;
    case 'can_pin_messages':
      return <Trans>Закреплять сообщения</Trans>;
    case 'can_change_info':
      return <Trans>Изменять профиль группы</Trans>;
  }
}

function WithoutIt({ right }: { right: UsedRight }) {
  switch (right) {
    case 'can_delete_messages':
      return <Trans>Реклама и «вошёл/вышел» останутся в чате.</Trans>;
    case 'can_restrict_members':
      return <Trans>Бан не сработает, капча в чате не выключит новичку сообщения.</Trans>;
    case 'can_invite_users':
      return <Trans>Бот не одобрит заявки и не сделает ссылку для каталога.</Trans>;
    case 'can_pin_messages':
      return (
        <Trans>
          Команда /pin не сработает, и бот не закрепит список чатов факультетов.
        </Trans>
      );
    case 'can_change_info':
      return <Trans>Описание чата не обновится по шаблону.</Trans>;
  }
}

function useDay() {
  const { i18n } = useLingui();
  return (iso: string) => i18n.date(utc(iso), { day: 'numeric', month: 'short' });
}

function useMoment() {
  const { i18n } = useLingui();
  return (iso: string) =>
    i18n.date(utc(iso), {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
}

/** The status in words, with since when. */
function Standing({ chat }: { chat: ConsoleChatDetail }) {
  const day = useDay();
  const bot = chat.bot;
  switch (botStanding(bot, chat.bot_absent_at)) {
    case 'unknown':
      return <Trans>Бота ещё не проверяли</Trans>;
    case 'ok':
      return <Trans>Бот — админ, все права есть</Trans>;
    case 'lacking':
      return <Trans>Бот — админ, но не хватает прав</Trans>;
    case 'not_admin':
      return <Trans>Бот в чате, но не админ · с {day(bot?.changed_at ?? '')}</Trans>;
    case 'removed':
      return <Trans>Бота удалили из чата · {day(bot?.changed_at ?? '')}</Trans>;
    case 'left':
      return <Trans>Бот вышел из чата · {day(bot?.changed_at ?? '')}</Trans>;
    case 'absent':
      // The mark is stamped again at every daily ask: it is not since when.
      return <Trans>Бота нет в чате</Trans>;
  }
}

function StandingHint({ chat }: { chat: ConsoleChatDetail }) {
  const moment = useMoment();
  switch (botStanding(chat.bot, chat.bot_absent_at)) {
    case 'unknown':
      return <Trans>Бот спросит Telegram в течение суток.</Trans>;
    case 'not_admin':
      return <Trans>Без прав админа бот не модерирует.</Trans>;
    case 'removed':
    case 'left':
      return <Trans>Ничего из настроек ниже не работает, пока бота не вернут.</Trans>;
    case 'absent':
      return (
        <Trans>
          Telegram не пускает бота в чат, последняя проверка{' '}
          {moment(chat.bot_absent_at ?? '')}. Ничего из настроек ниже не работает, пока
          бота не вернут.
        </Trans>
      );
    default:
      return chat.bot ? <Trans>Проверено {moment(chat.bot.known_at)}</Trans> : null;
  }
}

/** Where in Telegram the problem is mended. */
function HowToFix({ standing }: { standing: StandingKind }) {
  switch (standing) {
    case 'lacking':
      return (
        <Trans>
          Как исправить: Telegram → чат → Администраторы → Konnekt → включите право.
        </Trans>
      );
    case 'not_admin':
      return (
        <Trans>
          Как исправить: Telegram → чат → Администраторы → Добавить администратора →
          Konnekt.
        </Trans>
      );
    default:
      return (
        <Trans>
          Как исправить: добавьте Konnekt в чат заново и назначьте администратором.
        </Trans>
      );
  }
}

const PROBLEMS = new Set<StandingKind>([
  'lacking',
  'not_admin',
  'removed',
  'left',
  'absent',
]);

/**
 * The bot's place in the chat: whether it is there and an administrator,
 * what each missing right breaks and how to mend it, and where its history is.
 * Anything wrong is a warning, so it is not read past as one more grey row.
 */
export function BotRows({
  chat,
  onHistory,
}: {
  chat: ConsoleChatDetail;
  onHistory: () => void;
}) {
  const standing = botStanding(chat.bot, chat.bot_absent_at);
  const missing = chat.bot && standing === 'lacking' ? missingRights(chat.bot) : [];
  return (
    <>
      {PROBLEMS.has(standing) ? (
        <div className={`${ui.notice} ${css.problem}`} role="note">
          <span className={`${ui.noticeTitle} ${css.title}`}>
            <WarningIcon size={18} strokeWidth={2} />
            <Standing chat={chat} />
          </span>
          {missing.length ? (
            <ul className={css.rights}>
              {missing.map((right) => (
                <li key={right}>
                  <b>
                    <Trans>
                      Нет права «<RightName right={right} />»
                    </Trans>
                  </b>
                  <span>
                    <WithoutIt right={right} />
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <span>
              <StandingHint chat={chat} />
            </span>
          )}
          <span className={css.fix}>
            <HowToFix standing={standing} />
          </span>
        </div>
      ) : null}
      <Rows>
        {PROBLEMS.has(standing) ? null : (
          <Row
            wrap
            title={<Standing chat={chat} />}
            hint={<StandingHint chat={chat} />}
            trailing={
              standing === 'ok' ? (
                <span className={css.ok}>
                  <CheckIcon size={18} strokeWidth={2} />
                </span>
              ) : null
            }
          />
        )}
        {chat.bot_history.length ? (
          <Row
            title={<Trans>История прав бота</Trans>}
            hint={<HistoryHint latest={chat.bot_history[0]} />}
            trailing={<Chevron />}
            onClick={onHistory}
          />
        ) : null}
      </Rows>
    </>
  );
}

function HistoryHint({ latest }: { latest: BotChange | undefined }) {
  const day = useDay();
  if (!latest) return null;
  return <Trans>последнее изменение {day(latest.changed_at)}</Trans>;
}

function StatusWord({ status }: { status: string }) {
  switch (status) {
    case 'creator':
      return <Trans>владелец</Trans>;
    case 'administrator':
      return <Trans>админ</Trans>;
    case 'kicked':
      return <Trans>удалён</Trans>;
    case 'left':
      return <Trans>вышел</Trans>;
    case 'restricted':
      return <Trans>ограничен</Trans>;
    default:
      return <Trans>участник</Trans>;
  }
}

function RightsList({ rights }: { rights: UsedRight[] }) {
  return (
    <>
      {rights.map((right, index) => (
        <span key={right}>
          {index ? ', ' : ''}
          <RightName right={right} />
        </span>
      ))}
    </>
  );
}

/** Every change of the bot's status or rights, newest first, with who made it. */
export function BotHistorySheet({
  history,
  onClose,
}: {
  history: BotChange[];
  onClose: () => void;
}) {
  const { t } = useLingui();
  const moment = useMoment();
  return (
    <Sheet
      title={<Trans>История прав бота</Trans>}
      onClose={onClose}
      closeLabel={t`Закрыть`}
    >
      <Rows>
        {history.map((change, index) => {
          const before: BotRights | null = history[index + 1] ?? null;
          const { gained, lost } = rightsChange(before, change);
          const by = change.changed_by;
          const parts: ReactNode[] = [];
          if (gained.length) {
            parts.push(
              <span key="gained">
                <Trans>
                  дали: <RightsList rights={gained} />
                </Trans>
              </span>,
            );
          }
          if (lost.length) {
            parts.push(
              <span key="lost">
                <Trans>
                  забрали: <RightsList rights={lost} />
                </Trans>
              </span>,
            );
          }
          return (
            <Row
              key={change.id}
              wrap
              title={
                <>
                  <StatusWord status={change.status} /> · {moment(change.changed_at)}
                </>
              }
              hint={
                <>
                  {parts.length ? <>{parts.reduce((a, b) => [a, '; ', b])} · </> : null}
                  {by ? personName(by) : <Trans>замечено при проверке</Trans>}
                </>
              }
            />
          );
        })}
      </Rows>
    </Sheet>
  );
}

/** The chat's people with admin rights, as the bot last heard; another bot shows here when its updates did. */
export function AdminRows({ admins }: { admins: ChatAdmin[] }) {
  if (!admins.length) {
    return (
      <Hint>
        <Trans>Список админов появится после первой проверки бота.</Trans>
      </Hint>
    );
  }
  return (
    <Rows>
      {admins.map((admin) => (
        <Row
          key={admin.user_id}
          leading={<PersonFace person={admin} size={32} />}
          title={personName(admin)}
          hint={
            <>
              <StatusWord status={admin.status} />
              {admin.username ? ` · @${admin.username}` : null}
            </>
          }
        />
      ))}
    </Rows>
  );
}
