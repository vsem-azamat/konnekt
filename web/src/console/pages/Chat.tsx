import { Plural, Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { type ReactNode, useState } from 'react';
import { useNavigate, useParams } from 'react-router';

import { CityName, TopicHeading } from '@/components/Place';
import { Pick, Sheet } from '@/components/Sheet';
import { Switch } from '@/components/Switch';
import {
  Action,
  Actions,
  Chevron,
  Hint,
  Label,
  Row,
  Rows,
  SkeletonRows,
  Sub,
  Title,
  ui,
} from '@/components/Ui';
import { parentChoices } from '@/console/activity';
import { BanOutcomeSheet, BanSheet } from '@/console/BanSheet';
import { type BanOutcome, banOutcome } from '@/console/ban';
import { Heatmap, MemberTrend } from '@/console/Charts';
import { ConsoleFailure, ConsoleGate } from '@/console/ConsoleGate';
import { isListed } from '@/console/chats';
import { ChatFace, PersonFace } from '@/console/Faces';
import { FailureText } from '@/console/FailureText';
import { JoinModeRow } from '@/console/JoinMode';
import { PingRows, PingSheet } from '@/console/Pings';
import {
  blockedQuery,
  chatDetailQuery,
  consoleChanges,
  consoleChatsQuery,
  consoleSignalsQuery,
  consoleStatsQuery,
  consoleSystemQuery,
} from '@/console/queries';
import {
  type ChatSender,
  type ChatUpdate,
  type ConsoleChat,
  type ConsoleChatDetail,
  ConsoleError,
  personName,
  type SpamPing,
} from '@/console/session';
import { hasFormatting, welcomeChange, welcomePlain } from '@/console/welcome';
import { hapticSelection } from '@/hooks/useTelegram';
import { chatsQuery, institutionsQuery } from '@/lib/api';
import { TOPICS } from '@/lib/chats';
import type { Institution } from '@/lib/types';

/**
 * One chat, for the people who run it: whether it is approved and listed, how
 * it is protected, and who wrote in it lately. Every switch saves itself.
 */
export default function ConsoleChatPage() {
  const { id } = useParams();
  const chatId = Number(id);
  return (
    <ConsoleGate>
      {/* Keyed: what the screen remembers (a taken-down link) is one chat's. */}
      {Number.isInteger(chatId) ? (
        <ChatScreen key={chatId} chatId={chatId} />
      ) : (
        <NoSuchChat />
      )}
    </ConsoleGate>
  );
}

function NoSuchChat() {
  return (
    <div style={{ marginTop: 16 }}>
      <Hint>
        <Trans>Такого чата нет.</Trans>
      </Hint>
    </div>
  );
}

type Sheets =
  | { kind: 'publish' }
  | { kind: 'unpublish' }
  | { kind: 'disable' }
  | { kind: 'mode'; to: 'approved' | 'observed' | 'external' }
  | { kind: 'welcome'; opened: string | null }
  | { kind: 'ban'; sender: ChatSender }
  | {
      kind: 'banOutcome';
      sender: ChatSender;
      outcome: Exclude<BanOutcome, 'done'>;
      failed: number;
    }
  | { kind: 'unban'; sender: ChatSender }
  | { kind: 'ping'; ping: SpamPing }
  | { kind: 'parent' }
  | { kind: 'institution' }
  | { kind: 'city' }
  | { kind: 'topic' }
  | null;

function ChatScreen({ chatId }: { chatId: number }) {
  const { t, i18n } = useLingui();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const detail = useQuery(chatDetailQuery(chatId));
  const chats = useQuery(consoleChatsQuery);
  const institutions = useQuery(institutionsQuery);
  const system = useQuery(consoleSystemQuery);
  const [sheet, setSheet] = useState<Sheets>(null);
  const [error, setError] = useState<unknown>(null);
  const [refreshed, setRefreshed] = useState(false);
  // The link a chat had before it was taken down, so publishing it again
  // does not mean finding an invite hash in Telegram once more.
  const [lastLink, setLastLink] = useState<string | null>(null);

  const open = (next: Sheets) => {
    setError(null);
    setSheet(next);
  };
  // A sheet's failure belongs to the sheet: it goes when the sheet does.
  const close = () => {
    setError(null);
    setSheet(null);
  };
  const settle = (changed: Partial<ConsoleChatDetail>) => {
    queryClient.setQueryData<ConsoleChatDetail>(
      chatDetailQuery(chatId).queryKey,
      (old) => (old ? { ...old, ...changed } : old),
    );
    void queryClient.invalidateQueries({ queryKey: consoleChatsQuery.queryKey });
    void queryClient.invalidateQueries({ queryKey: consoleSignalsQuery.queryKey });
  };

  const update = useMutation({
    mutationFn: (change: ChatUpdate) => consoleChanges.updateChat(chatId, change),
    onMutate: () => setError(null),
    onSuccess: (chat: ConsoleChat, change) =>
      // The answer is the list view; the welcome text is not in it.
      settle({ ...chat, ...('welcome_message' in change ? change : {}) }),
    onError: setError,
  });
  const refresh = useMutation({
    mutationFn: () => consoleChanges.refreshChat(chatId),
    onMutate: () => {
      setError(null);
      setRefreshed(false);
    },
    onSuccess: (chat) => {
      settle(chat);
      setRefreshed(true);
    },
    onError: setError,
  });
  const block = useMutation({
    mutationFn: ({ sender, revoke }: { sender: ChatSender; revoke: boolean | null }) =>
      revoke === null
        ? consoleChanges.unblock(sender.user_id)
        : consoleChanges.block(sender.user_id, revoke),
    onMutate: () => setError(null),
    onSuccess: (result, { sender, revoke }) => {
      // An unban's failures are not this sheet's news; a ban's are.
      const outcome = revoke === null ? 'done' : banOutcome(result);
      // A ban is every chat's: every chat's sender list and hits may show it.
      void queryClient.invalidateQueries({ queryKey: ['console', 'chat'] });
      void queryClient.invalidateQueries({ queryKey: ['console', 'spam'] });
      void queryClient.invalidateQueries({ queryKey: blockedQuery.queryKey });
      // A ban answers the person's waiting ad hits: the counts move too.
      void queryClient.invalidateQueries({ queryKey: consoleStatsQuery.queryKey });
      void queryClient.invalidateQueries({ queryKey: consoleSignalsQuery.queryKey });
      // Only the sheet this answer is for: another may have opened meanwhile.
      setSheet((current) =>
        (current?.kind === 'ban' || current?.kind === 'unban') &&
        current.sender.user_id === sender.user_id
          ? outcome === 'done'
            ? null
            : { kind: 'banOutcome', sender, outcome, failed: result.failed_chats.length }
          : current,
      );
    },
    onError: setError,
  });

  if (detail.isPending) {
    return (
      <div style={{ marginTop: 16 }}>
        <SkeletonRows count={5} />
      </div>
    );
  }
  if (detail.error instanceof ConsoleError && detail.error.status === 404) {
    return <NoSuchChat />;
  }
  if (detail.error || !detail.data) {
    return (
      <div style={{ marginTop: 16 }}>
        <ConsoleFailure error={detail.error} retry={() => void detail.refetch()} />
      </div>
    );
  }

  const chat = detail.data;
  const title = chat.title ?? String(chat.id);
  // One change at a time: a refresh answer landing after a switch's would
  // put the switch back.
  const busy = update.isPending || refresh.isPending;
  const save = (change: ChatUpdate, after?: () => void) => {
    hapticSelection();
    update.mutate(change, { onSuccess: after });
  };
  const approved = chat.resource_status === 'approved';
  // A decision was made about it, so the public tab may list it.
  const decided =
    chat.resource_status !== 'discovered' && chat.resource_status !== 'disabled';
  // What students see: the public tab lists decided chats with a link.
  const listed = isListed(chat);
  const pickMode = (mode: 'approved' | 'observed' | 'external') => {
    if (mode === chat.resource_status) return;
    // Every change between decided modes asks first: into moderation the bot
    // starts acting where another bot may be in charge, out of it a chat loses
    // its protection, and into external it is marked as not ours in public.
    // Bringing a disabled chat back asks only when it would be marked.
    if (decided || mode === 'external') open({ kind: 'mode', to: mode });
    else save({ resource_status: mode });
  };
  const admins = new Set(system.data?.super_admin_ids ?? []);
  const total = chat.recent_senders.reduce((sum, row) => sum + row.message_count, 0);
  const sheetError = sheet && error ? <FailureText error={error} /> : null;
  const parent = chats.data?.find((row) => row.id === chat.parent_chat_id);
  const universityName = (code: string) => {
    const university = institutions.data?.find((row) => row.code === code);
    return university ? (university.short_name ?? university.name) : code;
  };
  // The public catalogue files and filters by these, so it is asked again.
  const saveListing = (change: ChatUpdate) =>
    save(change, () => {
      void queryClient.invalidateQueries({ queryKey: chatsQuery.queryKey });
      close();
    });
  const goTo = (id: number) => {
    hapticSelection();
    navigate(`/console/chats/${id}`);
  };

  const head = (
    <>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 12 }}>
        <ChatFace chat={{ id: chat.id, title: chat.title }} size={56} />
        <Title>{title}</Title>
      </div>
      <div style={{ marginTop: 6 }}>
        <Sub>
          {chat.member_count !== null ? (
            <>
              <Plural
                value={chat.member_count}
                one="# участник"
                few="# участника"
                many="# участников"
                other="# участника"
              />
              {' · '}
            </>
          ) : null}
          {approved ? (
            <Trans>бот модерирует</Trans>
          ) : chat.resource_status === 'observed' ? (
            <Trans>бот наблюдает</Trans>
          ) : chat.resource_status === 'external' ? (
            <Trans>только ссылка, бота нет</Trans>
          ) : chat.resource_status === 'discovered' ? (
            <Trans>ждёт решения</Trans>
          ) : (
            <Trans>отключён</Trans>
          )}
          {chat.bot_absent_at && chat.resource_status !== 'external' ? (
            <>
              {' · '}
              <Trans>бот вышел</Trans>
            </>
          ) : null}
          {chat.public_link ? (
            <>
              {' · '}
              <a
                className={ui.inlineLink}
                href={chat.public_link}
                target="_blank"
                rel="noreferrer"
              >
                {chat.public_link.replace(/^https?:\/\//, '')}
              </a>
            </>
          ) : null}
        </Sub>
      </div>

      {error && !sheet ? (
        <div style={{ marginTop: 12 }}>
          <Hint>
            <FailureText error={error} />
          </Hint>
        </div>
      ) : null}
    </>
  );
  // The bot is no longer in a chat nobody decided on: there is nothing to
  // list, protect or watch, only switching it off. The rest would be settings
  // that change nothing and a promise of approval that cannot come.
  if (chat.resource_status === 'discovered' && chat.bot_absent_at) {
    return (
      <>
        {head}
        <div style={{ marginTop: 16 }}>
          <Hint>
            <Trans>
              Бота в этом чате уже нет. Решать здесь нечего, кроме как отключить.
            </Trans>
          </Hint>
          <Actions>
            <Action onClick={() => save({ resource_status: 'disabled' })} disabled={busy}>
              <Trans>Отключить</Trans>
            </Action>
          </Actions>
        </div>
      </>
    );
  }

  return (
    <>
      {head}
      {chat.resource_status === 'discovered' ? (
        <div style={{ marginTop: 16 }}>
          <Actions>
            <Action onClick={() => save({ resource_status: 'approved' })} disabled={busy}>
              <Trans>Одобрить</Trans>
            </Action>
            <Action
              quiet
              onClick={() => save({ resource_status: 'observed' })}
              disabled={busy}
            >
              <Trans>Только наблюдать</Trans>
            </Action>
            <Action
              quiet
              onClick={() => save({ resource_status: 'disabled' })}
              disabled={busy}
            >
              <Trans>Отключить</Trans>
            </Action>
          </Actions>
        </div>
      ) : (
        <>
          <Label>
            <Trans>Что бот делает в чате</Trans>
          </Label>
          <div className={ui.sheetList}>
            <Pick
              name={<Trans>Модерирует</Trans>}
              hint={
                <Trans>
                  Команды, чёрный список, приветствие, уборка, спам и реклама.
                </Trans>
              }
              selected={approved}
              disabled={busy}
              onClick={() => pickMode('approved')}
            />
            <Pick
              name={<Trans>Только наблюдает</Trans>}
              hint={
                <Trans>
                  Записывает историю и считает участников. Ничего не пишет, ни на что не
                  отвечает.
                </Trans>
              }
              selected={chat.resource_status === 'observed'}
              disabled={busy}
              onClick={() => pickMode('observed')}
            />
            <Pick
              name={<Trans>Внешний чат</Trans>}
              hint={
                <Trans>
                  Бота там нет. Только ссылка в каталоге, с пометкой «не наш».
                </Trans>
              }
              selected={chat.resource_status === 'external'}
              disabled={busy}
              onClick={() => pickMode('external')}
            />
          </div>
        </>
      )}

      <Label>
        <Trans>На публичной вкладке</Trans>
      </Label>
      <Rows>
        <Row
          title={
            listed ? (
              <Trans>Показан в «Чатах»</Trans>
            ) : chat.public_link && !decided ? (
              <Trans>Не виден: чат не одобрен</Trans>
            ) : chat.public_link ? (
              <Trans>Не виден: у чата нет названия</Trans>
            ) : (
              <Trans>Не показан</Trans>
            )
          }
          hint={
            chat.public_link && !decided ? (
              <Trans>появится после одобрения</Trans>
            ) : chat.public_link && !listed ? (
              <Trans>обновите его из Telegram</Trans>
            ) : chat.public_link ? null : (
              <Trans>нужна ссылка t.me</Trans>
            )
          }
          trailing={
            <Switch
              checked={Boolean(chat.public_link)}
              busy={busy}
              label={t`На публичной вкладке`}
              onChange={(on) => open({ kind: on ? 'publish' : 'unpublish' })}
            />
          }
        />
        {chat.public_link ? (
          <Row
            title={<Trans>Ссылка</Trans>}
            hint={chat.public_link}
            trailing={<Chevron />}
            onClick={() => open({ kind: 'publish' })}
          />
        ) : null}
      </Rows>

      <Label>
        <Trans>Защита</Trans>
      </Label>
      {!approved ? (
        // The bot ignores chats it is not approved in: nothing below runs there.
        <div style={{ marginBottom: 8 }}>
          <Hint>
            <Trans>Работает только в одобренном чате.</Trans>
          </Hint>
        </div>
      ) : null}
      <Rows>
        <JoinModeRow
          chat={chat}
          busy={busy}
          onChange={(mode) => save({ join_mode: mode })}
        />
        <Row
          title={<Trans>Приветствие</Trans>}
          trailing={
            <Switch
              checked={chat.is_welcome_enabled}
              busy={busy}
              label={t`Приветствие`}
              // The greeting stands without the chat's own text, so it is not asked for.
              onChange={(on) => save({ is_welcome_enabled: on })}
            />
          }
        />
        <Row
          title={<Trans>Текст приветствия</Trans>}
          hint={
            welcomePlain(chat.welcome_message) || (
              <Trans>Не задан: только общее приветствие</Trans>
            )
          }
          trailing={<Chevron />}
          onClick={() => open({ kind: 'welcome', opened: chat.welcome_message })}
        />
        <Row
          title={<Trans>Прятать «вошёл» и «вышел»</Trans>}
          trailing={
            <Switch
              checked={chat.is_service_cleanup_enabled}
              busy={busy}
              label={t`Прятать «вошёл» и «вышел»`}
              onChange={(on) => save({ is_service_cleanup_enabled: on })}
            />
          }
        />
      </Rows>

      <Label>
        <Trans>Место в списке</Trans>
      </Label>
      <Rows>
        <Row
          title={<Trans>Входит в</Trans>}
          hint={
            chat.parent_chat_id === null ? (
              <Trans>ни во что: стоит отдельно</Trans>
            ) : (
              (parent?.title ?? String(chat.parent_chat_id))
            )
          }
          trailing={<Chevron />}
          onClick={() => {
            if (!busy) open({ kind: 'parent' });
          }}
        />
        {chat.parent_chat_id === null ? (
          <Row
            title={<Trans>Вуз</Trans>}
            hint={
              chat.institution_code ? (
                universityName(chat.institution_code)
              ) : (
                <Trans>не указан: чаты под ним его студентам не поднимутся</Trans>
              )
            }
            trailing={<Chevron />}
            onClick={() => {
              if (!busy) open({ kind: 'institution' });
            }}
          />
        ) : (
          <Row
            title={<Trans>Вуз</Trans>}
            hint={
              parent?.institution_code ? (
                <Trans>как у родителя: {universityName(parent.institution_code)}</Trans>
              ) : (
                <Trans>задаётся у родителя</Trans>
              )
            }
          />
        )}
        <Row
          title={<Trans>Город</Trans>}
          hint={
            chat.city !== null ? (
              <CityName city={chat.city} />
            ) : chat.parent_chat_id === null ? (
              <CityName city={null} />
            ) : parent ? (
              <Trans>
                как у родителя: <CityName city={parent.city} />
              </Trans>
            ) : (
              <Trans>задаётся у родителя</Trans>
            )
          }
          trailing={<Chevron />}
          onClick={() => {
            if (!busy) open({ kind: 'city' });
          }}
        />
        <Row
          title={<Trans>Раздел каталога</Trans>}
          hint={
            chat.topic !== null ? (
              <TopicHeading topic={chat.topic} />
            ) : chat.parent_chat_id === null ? (
              chat.institution_code ? (
                <Trans>Вузы, по вузу</Trans>
              ) : (
                <Trans>не указан: стоит в «Общее»</Trans>
              )
            ) : !parent ? (
              <Trans>задаётся у родителя</Trans>
            ) : parent.topic ? (
              <Trans>
                как у родителя: <TopicHeading topic={parent.topic} />
              </Trans>
            ) : parent.institution_code ? (
              <Trans>Вузы, по вузу</Trans>
            ) : (
              <Trans>не указан: стоит в «Общее»</Trans>
            )
          }
          trailing={<Chevron />}
          onClick={() => {
            if (!busy) open({ kind: 'topic' });
          }}
        />
        {chat.children.map((child) => (
          <Row
            key={child.id}
            title={child.title ?? String(child.id)}
            hint={<Trans>входит в этот чат</Trans>}
            trailing={<Chevron />}
            onClick={() => goTo(child.id)}
          />
        ))}
      </Rows>

      <Label>
        <Trans>Активность</Trans>
      </Label>
      <div className={ui.column}>
        <MemberTrend snapshots={chat.member_snapshots} />
        <Heatmap cells={chat.heatmap} />
      </div>

      <Label>
        <Trans>Реклама</Trans>
      </Label>
      {chat.spam_pings.length > 0 ? (
        <PingRows
          pings={chat.spam_pings}
          showChat={false}
          onPick={(ping) => open({ kind: 'ping', ping })}
        />
      ) : (
        <Hint>
          <Trans>Детектор здесь ничего не находил.</Trans>
        </Hint>
      )}

      <Label aside={total > 0 ? <Trans>всего {i18n.number(total)}</Trans> : null}>
        <Trans>Кто писал за неделю</Trans>
      </Label>
      {chat.recent_senders.length > 0 ? (
        <Rows>
          {chat.recent_senders.map((sender) => {
            const admin = admins.has(sender.user_id);
            return (
              <Row
                key={sender.user_id}
                leading={<PersonFace person={sender} size={32} />}
                title={personName(sender)}
                hint={
                  <>
                    {sender.username && personName(sender) !== `@${sender.username}`
                      ? `@${sender.username} · `
                      : null}
                    <Plural
                      value={sender.message_count}
                      one="# сообщение"
                      few="# сообщения"
                      many="# сообщений"
                      other="# сообщения"
                    />
                    {admin ? (
                      <>
                        {' · '}
                        <Trans>администратор</Trans>
                      </>
                    ) : sender.blocked ? (
                      <>
                        {' · '}
                        <Trans>заблокирован</Trans>
                      </>
                    ) : null}
                  </>
                }
                onClick={
                  admin
                    ? undefined
                    : () => open({ kind: sender.blocked ? 'unban' : 'ban', sender })
                }
              />
            );
          })}
        </Rows>
      ) : (
        <Hint>
          <Trans>За неделю здесь никто не писал.</Trans>
        </Hint>
      )}

      <div style={{ marginTop: 16 }}>
        <Rows>
          <Row
            title={
              refresh.isPending ? (
                <Trans>Обновляем…</Trans>
              ) : (
                <Trans>Обновить из Telegram</Trans>
              )
            }
            hint={
              refreshed ? (
                <Trans>Обновлено</Trans>
              ) : (
                <Trans>название, фото и число участников</Trans>
              )
            }
            onClick={
              busy
                ? undefined
                : () => {
                    hapticSelection();
                    refresh.mutate();
                  }
            }
          />
        </Rows>
      </div>

      {decided ? (
        <div style={{ marginTop: 16 }}>
          <Actions>
            <Action quiet onClick={() => open({ kind: 'disable' })} disabled={busy}>
              <Trans>Отключить чат</Trans>
            </Action>
          </Actions>
        </div>
      ) : null}

      {sheet?.kind === 'publish' ? (
        <TextSheet
          title={t`Ссылка для публичной вкладки`}
          initial={chat.public_link ?? lastLink ?? 'https://t.me/'}
          placeholder="https://t.me/cvut_fit"
          busy={busy}
          error={sheetError}
          onClose={close}
          // Empty is not a link: taking the chat down is the switch's, and asks.
          canSave={(link) => link.length > 0}
          onSave={(link) => save({ public_link: link }, close)}
        />
      ) : null}
      {sheet?.kind === 'mode' ? (
        <Sheet
          title={
            sheet.to === 'approved'
              ? t`Включить модерацию?`
              : sheet.to === 'observed'
                ? t`Только наблюдать?`
                : t`Отметить чат как внешний?`
          }
          closeLabel={t`Отмена`}
          onClose={close}
        >
          <Sub>
            {sheet.to === 'approved' ? (
              <Trans>
                Бот начнёт отвечать на команды и удалять сообщения в этом чате. Если здесь
                порядок держит другой бот, они будут мешать друг другу.
              </Trans>
            ) : sheet.to === 'observed' ? (
              <Trans>
                Бот будет только записывать историю: ничего не пишет и ни на что не
                отвечает. В каталоге чат показан как наш.
              </Trans>
            ) : (
              <Trans>
                В каталоге чат будет помечен как не наш. Бот там ничего не делает; если он
                в чате, удалите его оттуда.
              </Trans>
            )}
            {approved ? (
              <>
                {' '}
                <Trans>
                  Капча, приветствие и чёрный список здесь перестанут работать.
                </Trans>
              </>
            ) : null}
          </Sub>
          {sheetError ? <Hint>{sheetError}</Hint> : null}
          <div className={ui.actionsStacked}>
            <Action
              disabled={busy}
              onClick={() => save({ resource_status: sheet.to }, close)}
            >
              {sheet.to === 'approved' ? (
                <Trans>Модерировать</Trans>
              ) : sheet.to === 'observed' ? (
                <Trans>Только наблюдать</Trans>
              ) : (
                <Trans>Отметить внешним</Trans>
              )}
            </Action>
            <Action quiet onClick={close}>
              <Trans>Отмена</Trans>
            </Action>
          </div>
        </Sheet>
      ) : null}
      {sheet?.kind === 'disable' ? (
        <Sheet title={t`Отключить чат?`} closeLabel={t`Отмена`} onClose={close}>
          <Sub>
            {approved ? (
              <Trans>
                Бот перестанет его модерировать: капча, приветствие и чёрный список там
                работать не будут. Включить можно здесь же.
              </Trans>
            ) : (
              <Trans>Чат будет отключён. Вернуть режим можно здесь же.</Trans>
            )}
            {listed ? (
              <>
                {' '}
                <Trans>Чат пропадёт с публичной вкладки.</Trans>
              </>
            ) : null}
          </Sub>
          {sheetError ? <Hint>{sheetError}</Hint> : null}
          <div className={ui.actionsStacked}>
            <Action
              disabled={busy}
              onClick={() => save({ resource_status: 'disabled' }, close)}
            >
              <Trans>Отключить</Trans>
            </Action>
            <Action quiet onClick={close}>
              <Trans>Отмена</Trans>
            </Action>
          </div>
        </Sheet>
      ) : null}
      {sheet?.kind === 'unpublish' ? (
        <Sheet
          title={t`Снять с публичной вкладки?`}
          closeLabel={t`Отмена`}
          onClose={close}
        >
          <Sub>
            <Trans>Ссылка сотрётся: {chat.public_link}</Trans>
          </Sub>
          {sheetError ? <Hint>{sheetError}</Hint> : null}
          <div className={ui.actionsStacked}>
            <Action
              disabled={busy}
              onClick={() => {
                const link = chat.public_link;
                save({ public_link: '' }, () => {
                  setLastLink(link);
                  setSheet(null);
                });
              }}
            >
              <Trans>Снять</Trans>
            </Action>
            <Action quiet onClick={close}>
              <Trans>Отмена</Trans>
            </Action>
          </div>
        </Sheet>
      ) : null}
      {sheet?.kind === 'welcome' ? (
        <TextSheet
          multiline
          title={t`Приветствие`}
          note={
            <>
              <Trans>
                Третья строка приветствия, под «добро пожаловать» и строкой про Konnekt.
                Можно оставить пустым.
              </Trans>
              {hasFormatting(sheet.opened) ? (
                <>
                  {' '}
                  <Trans>Жирный и ссылки из !welcome после правки здесь пропадут.</Trans>
                </>
              ) : null}
            </>
          }
          initial={welcomePlain(sheet.opened)}
          placeholder={t`Вопросы по поступлению — в тему #вопросы.`}
          busy={busy}
          error={sheetError}
          onClose={close}
          // Empty leaves the greeting on, with only the shared lines. Compared
          // with what the sheet opened on, not a text refetched meanwhile.
          onSave={(text) => {
            const html = welcomeChange(sheet.opened, text);
            if (html === null) close();
            else save({ welcome_message: html }, close);
          }}
        />
      ) : null}
      {sheet?.kind === 'ban' ? (
        <BanSheet
          // One person's choice and typed word are not the next one's.
          key={sheet.sender.user_id}
          name={personName(sheet.sender)}
          note={
            <Trans>
              Здесь за неделю{' '}
              <Plural
                value={sheet.sender.message_count}
                one="# сообщение"
                few="# сообщения"
                many="# сообщений"
                other="# сообщения"
              />
              .
            </Trans>
          }
          busy={block.isPending}
          error={sheetError}
          onBan={(revoke) => block.mutate({ sender: sheet.sender, revoke })}
          onClose={close}
        />
      ) : null}
      {sheet?.kind === 'banOutcome' ? (
        <BanOutcomeSheet
          name={personName(sheet.sender)}
          outcome={sheet.outcome}
          failed={sheet.failed}
          onClose={close}
        />
      ) : null}
      {sheet?.kind === 'ping' ? (
        <PingSheet key={sheet.ping.id} ping={sheet.ping} onClose={close} />
      ) : null}
      {sheet?.kind === 'institution' ? (
        <InstitutionSheet
          current={chat.institution_code}
          institutions={institutions.data}
          failed={institutions.error}
          retry={() => void institutions.refetch()}
          busy={busy}
          error={sheetError}
          onPick={(code) =>
            code === chat.institution_code
              ? close()
              : save({ institution_code: code }, () => {
                  // The public directory orders by it.
                  void queryClient.invalidateQueries({ queryKey: chatsQuery.queryKey });
                  close();
                })
          }
          onClose={close}
        />
      ) : null}
      {sheet?.kind === 'city' ? (
        <ChoiceSheet
          title={t`Город`}
          note={
            chat.parent_chat_id === null ? (
              <Trans>Пусто — вся Чехия: чат виден в каталоге при любом городе.</Trans>
            ) : (
              <Trans>
                Пусто — город родителя. Свой город нужен, только если он другой.
              </Trans>
            )
          }
          options={[
            {
              value: null,
              name:
                chat.parent_chat_id === null ? (
                  <CityName city={null} />
                ) : (
                  <Trans>как у родителя</Trans>
                ),
            },
            ...taxonomyCities(institutions.data ?? [], chat.city).map((city) => ({
              value: city,
              name: <CityName city={city} />,
            })),
          ]}
          loading={institutions.isPending}
          failed={institutions.error}
          retry={() => void institutions.refetch()}
          current={chat.city}
          busy={busy}
          error={sheetError}
          onPick={(city) => (city === chat.city ? close() : saveListing({ city }))}
          onClose={close}
        />
      ) : null}
      {sheet?.kind === 'topic' ? (
        <ChoiceSheet
          title={t`Раздел каталога`}
          note={
            <Trans>Чат вуза можно не указывать: он стоит в «Вузы» по своему вузу.</Trans>
          }
          options={[
            { value: null, name: <Trans>Не указан</Trans> },
            ...TOPICS.map((topic) => ({
              value: topic,
              name: <TopicHeading topic={topic} />,
            })),
          ]}
          current={chat.topic}
          busy={busy}
          error={sheetError}
          onPick={(topic) => (topic === chat.topic ? close() : saveListing({ topic }))}
          onClose={close}
        />
      ) : null}
      {sheet?.kind === 'parent' ? (
        <ParentSheet
          chat={chat}
          chats={chats.data}
          busy={busy}
          error={sheet && error ? <ParentFailure error={error} /> : null}
          onPick={(parentId) =>
            parentId === chat.parent_chat_id
              ? close()
              : save({ parent_chat_id: parentId }, () => {
                  // The old and the new parent list their children.
                  void queryClient.invalidateQueries({ queryKey: ['console', 'chat'] });
                  close();
                })
          }
          retry={() => void chats.refetch()}
          failed={chats.error}
          onClose={close}
        />
      ) : null}
      {sheet?.kind === 'unban' ? (
        <Sheet title={t`Снять бан во всех чатах?`} closeLabel={t`Отмена`} onClose={close}>
          <Sub>{personName(sheet.sender)}</Sub>
          {sheetError ? <Hint>{sheetError}</Hint> : null}
          <div className={ui.actionsStacked}>
            <Action
              disabled={block.isPending}
              onClick={() => block.mutate({ sender: sheet.sender, revoke: null })}
            >
              <Trans>Снять бан</Trans>
            </Action>
            <Action quiet onClick={close}>
              <Trans>Отмена</Trans>
            </Action>
          </div>
        </Sheet>
      ) : null}
    </>
  );
}

/**
 * Which chat this one is listed under. The console's and the public lists
 * group one level deep, so only a top-level chat is offered.
 */
function ParentSheet({
  chat,
  chats,
  failed,
  busy,
  error,
  onPick,
  retry,
  onClose,
}: {
  chat: ConsoleChatDetail;
  chats: ConsoleChat[] | undefined;
  failed: unknown;
  busy: boolean;
  error: ReactNode;
  onPick: (parentId: number | null) => void;
  retry: () => void;
  onClose: () => void;
}) {
  const { t } = useLingui();
  const choices = chats ? parentChoices(chats, chat.id) : [];
  const nested = chat.children.length > 0;
  return (
    <Sheet title={t`Входит в`} closeLabel={t`Отмена`} onClose={onClose}>
      {error ? <Hint>{error}</Hint> : null}
      {failed ? (
        <ConsoleFailure error={failed} retry={retry} />
      ) : !chats ? (
        <SkeletonRows count={3} />
      ) : (
        <>
          {nested ? (
            <Hint>
              <Trans>В этот чат входят другие, поэтому он сам стоит отдельно.</Trans>
            </Hint>
          ) : null}
          <div className={ui.sheetList}>
            {/* Offered whenever it is a change, so a chat nested against the rule can
                still be taken out. */}
            {!nested || chat.parent_chat_id !== null ? (
              <Pick
                name={<Trans>Ни во что</Trans>}
                selected={chat.parent_chat_id === null}
                disabled={busy}
                onClick={() => onPick(null)}
              />
            ) : null}
            {choices.map((choice) => (
              <Pick
                key={choice.id}
                name={choice.title ?? String(choice.id)}
                selected={chat.parent_chat_id === choice.id}
                disabled={busy}
                onClick={() => onPick(choice.id)}
              />
            ))}
          </div>
        </>
      )}
    </Sheet>
  );
}

/**
 * Which university a chat at the top belongs to, from the catalog's list, so
 * the public tab can put a student's own first. Universities only: a
 * faculty's students are found through their university.
 */
function InstitutionSheet({
  current,
  institutions,
  failed,
  retry,
  busy,
  error,
  onPick,
  onClose,
}: {
  current: string | null;
  institutions: Institution[] | undefined;
  failed: unknown;
  retry: () => void;
  busy: boolean;
  error: ReactNode;
  onPick: (code: string | null) => void;
  onClose: () => void;
}) {
  const { t } = useLingui();
  return (
    <Sheet title={t`Вуз`} closeLabel={t`Отмена`} onClose={onClose}>
      {error ? <Hint>{error}</Hint> : null}
      {failed ? (
        <ConsoleFailure error={failed} retry={retry} />
      ) : !institutions ? (
        <SkeletonRows count={3} />
      ) : (
        <div className={ui.sheetList}>
          <Pick
            name={<Trans>Не указан</Trans>}
            selected={current === null}
            disabled={busy}
            onClick={() => onPick(null)}
          />
          {institutions.map((university) => (
            <Pick
              key={university.code}
              name={university.short_name ?? university.name}
              hint={university.short_name ? university.name : undefined}
              selected={current === university.code}
              disabled={busy}
              onClick={() => onPick(university.code)}
            />
          ))}
        </div>
      )}
    </Sheet>
  );
}

/** One choice from a short list, the current one marked. */
function ChoiceSheet<T extends string>({
  title,
  note,
  options,
  loading = false,
  failed = null,
  retry,
  current,
  busy,
  error,
  onPick,
  onClose,
}: {
  title: string;
  note: ReactNode;
  options: { value: T | null; name: ReactNode }[];
  /** The list comes from a query: shown as loading, or failed with a retry. */
  loading?: boolean;
  failed?: unknown;
  retry?: () => void;
  current: T | null;
  busy: boolean;
  error: ReactNode;
  onPick: (value: T | null) => void;
  onClose: () => void;
}) {
  const { t } = useLingui();
  return (
    <Sheet title={title} closeLabel={t`Отмена`} onClose={onClose}>
      <Hint>{note}</Hint>
      {error ? <Hint>{error}</Hint> : null}
      {failed && retry ? (
        <ConsoleFailure error={failed} retry={retry} />
      ) : loading ? (
        <SkeletonRows count={3} />
      ) : (
        <div className={ui.sheetList}>
          {options.map((option) => (
            <Pick
              key={option.value ?? ''}
              name={option.name}
              selected={current === option.value}
              disabled={busy}
              onClick={() => onPick(option.value)}
            />
          ))}
        </div>
      )}
    </Sheet>
  );
}

/**
 * The cities a chat can be put in: those the catalog's universities are in,
 * spelled as it spells them, so a student's university matches. A city set
 * before and no longer among them stays pickable.
 */
function taxonomyCities(institutions: Institution[], current: string | null): string[] {
  const all = new Set(institutions.flatMap((row) => (row.city ? [row.city] : [])));
  if (current) all.add(current);
  return [...all].sort((a, b) => a.localeCompare(b, 'cs'));
}

/** Why a parent was refused: the list moved on under the sheet. */
function ParentFailure({ error }: { error: unknown }) {
  if (error instanceof ConsoleError && (error.status === 409 || error.status === 422)) {
    return (
      <Trans>Так вложить нельзя: список чатов изменился. Откройте экран заново.</Trans>
    );
  }
  return <FailureText error={error} />;
}

function TextSheet({
  title,
  note,
  initial,
  placeholder,
  multiline = false,
  busy,
  error,
  canSave = () => true,
  onClose,
  onSave,
}: {
  title: string;
  note?: ReactNode;
  initial: string;
  placeholder: string;
  multiline?: boolean;
  busy: boolean;
  error: ReactNode;
  canSave?: (value: string) => boolean;
  onClose: () => void;
  onSave: (value: string) => void;
}) {
  const { t } = useLingui();
  const [value, setValue] = useState(initial);
  return (
    <Sheet title={title} closeLabel={t`Отмена`} onClose={onClose}>
      {note ? <Sub>{note}</Sub> : null}
      <div
        className={ui.field}
        style={multiline ? { alignItems: 'flex-start' } : undefined}
      >
        {multiline ? (
          <textarea
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={placeholder}
            rows={4}
            maxLength={2000}
            style={{ all: 'unset', width: '100%', resize: 'none', lineHeight: 1.5 }}
          />
        ) : (
          <input
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={placeholder}
            maxLength={200}
            inputMode="url"
            style={{ all: 'unset', flex: 1, minWidth: 0 }}
          />
        )}
      </div>
      {error ? <Hint>{error}</Hint> : null}
      <Actions>
        <Action
          disabled={busy || !canSave(value.trim())}
          onClick={() => onSave(value.trim())}
        >
          <Trans>Сохранить</Trans>
        </Action>
      </Actions>
    </Sheet>
  );
}
