import { Plural, Trans } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { openTelegramLink } from '@tma.js/sdk-react';
import { useNavigate } from 'react-router';
import { AppHeader } from '@/components/AppHeader';
import {
  BookmarkIcon,
  ChatIcon,
  DocumentIcon,
  InboxIcon,
  LanguageIcon,
  PersonIcon,
  SealIcon,
} from '@/components/icons';
import {
  Action,
  Actions,
  AvatarView,
  Card,
  Chips,
  ChipView,
  Count,
  Hint,
  Label,
  Row,
  Rows,
  Screen,
  SkeletonRows,
  Sub,
  Tile,
  Title,
} from '@/components/Ui';
import { hapticSelection } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import { allPaused, liveCount } from '@/lib/myServices';
import { openRequests } from '@/lib/openRequests';

/**
 * A person's own things first, then the one setting, then the rest.
 *
 * «Моё» is what a student and a helper come back for: their requests, and for
 * a helper their services and the requests to answer. Someone who is
 * not a helper yet gets one card that says what offering help means, rather
 * than a row that only names it.
 *
 * The languages someone speaks are not decoration here — they filter the
 * catalog. A Ukrainian first-year cannot work with a Czech-only tutor, so the
 * question is asked plainly rather than inferred.
 */
export default function ProfilePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const {
    data: me,
    isError,
    refetch,
  } = useQuery({
    queryKey: ['me'],
    queryFn: ({ signal }) => api.getMe(signal),
  });

  // The contact the ads pages offer too (`AdsContact`): the desk answers any
  // question, so it is here as well. Unset, the row is not drawn.
  const { data: ads } = useQuery({
    queryKey: ['ads'],
    queryFn: ({ signal }) => api.getAds(signal),
    staleTime: 60 * 60_000,
  });
  const contactUrl = ads?.contact_url;

  const { data: languages } = useQuery({
    queryKey: ['languages'],
    queryFn: ({ signal }) => api.getLanguages(signal),
    staleTime: 60 * 60 * 1000,
  });

  const { data: requests } = useQuery({
    queryKey: ['requests'],
    queryFn: ({ signal }) => api.getRequests(signal),
  });
  const waiting = openRequests(requests ?? []);

  const isHelper = me?.is_helper ?? false;
  const { data: helper } = useQuery({
    queryKey: ['my-helper'],
    queryFn: ({ signal }) => api.getMyHelper(signal),
    enabled: isHelper,
  });
  // Without those already answered: the number is what still waits for them.
  // A banned helper's feed is closed, and asking would only get a 403.
  const readsFeed = isHelper && me?.helper_status !== 'banned';
  const { data: facets } = useQuery({
    queryKey: ['request-feed', 'facets', false],
    queryFn: ({ signal }) => api.getFeedFacets(false, signal),
    enabled: readsFeed,
  });
  const waitingForMe = facets?.mine ?? 0;

  const update = useMutation({
    mutationFn: api.updateMe,
    onSuccess: (next) => {
      queryClient.setQueryData(['me'], next);
      // Names of subjects and faculties come back translated, so a language
      // change invalidates everything the server rendered.
      void queryClient.invalidateQueries();
    },
  });

  const toggleLanguage = (code: string) => {
    if (!me) return;
    hapticSelection();
    const spoken = new Set(me.spoken_langs);
    if (!spoken.delete(code)) spoken.add(code);
    update.mutate({ spoken_langs: [...spoken] });
  };

  return (
    <Screen>
      <AppHeader />
      {!me ? (
        <>
          <Title>
            <Trans>Профиль</Trans>
          </Title>
          <div style={{ height: 16 }} />
          {isError ? (
            <Rows>
              <Row
                title={<Trans>Не удалось загрузить</Trans>}
                hint={<Trans>Нажми, чтобы попробовать ещё раз</Trans>}
                onClick={() => void refetch()}
              />
            </Rows>
          ) : (
            <SkeletonRows count={4} />
          )}
        </>
      ) : (
        <>
          <div
            style={{
              display: 'flex',
              gap: 12,
              alignItems: 'center',
              marginTop: 14,
            }}
          >
            <AvatarView avatar={me.avatar} size={58} square />
            <div style={{ minWidth: 0 }}>
              <Title>{me.name}</Title>
              {me.username ? <Sub>@{me.username}</Sub> : null}
            </div>
          </div>

          <Label>
            <Trans>Моё</Trans>
          </Label>
          <Rows>
            <Row
              onClick={() => navigate('/mine')}
              leading={
                <Tile tone={2}>
                  <BookmarkIcon size={19} />
                </Tile>
              }
              title={<Trans>Мои заявки</Trans>}
              hint={
                !requests ? null : requests.length === 0 ? (
                  <Trans>своих заявок нет</Trans>
                ) : waiting.requests === 0 ? (
                  <Trans>открытых нет</Trans>
                ) : (
                  <>
                    <Plural
                      value={waiting.requests}
                      one="# заявка"
                      few="# заявки"
                      many="# заявок"
                      other="# заявки"
                    />
                    {' · '}
                    <Plural
                      value={waiting.responses}
                      one="# отклик"
                      few="# отклика"
                      many="# откликов"
                      other="# отклика"
                    />
                  </>
                )
              }
              trailing={waiting.requests ? <Count>{waiting.requests}</Count> : null}
            />
            {isHelper ? (
              <>
                <Row
                  onClick={() => navigate('/my-helper')}
                  leading={
                    <Tile tone={0}>
                      <PersonIcon size={19} />
                    </Tile>
                  }
                  title={<Trans>Мои услуги</Trans>}
                  hint={
                    <>
                      {me.helper_status === 'published' ? (
                        <Trans>в каталоге</Trans>
                      ) : me.helper_status === 'hidden' ? (
                        <Trans>скрыта — в каталоге её не видно</Trans>
                      ) : me.helper_status === 'banned' ? (
                        <Trans>скрыта администратором</Trans>
                      ) : (
                        <Trans>черновик — не видна в каталоге</Trans>
                      )}
                      {helper && allPaused(helper) ? (
                        <>
                          {' · '}
                          <Trans>все услуги выключены</Trans>
                        </>
                      ) : helper && liveCount(helper) ? (
                        <>
                          {' · '}
                          <Plural
                            value={liveCount(helper)}
                            one="# услуга"
                            few="# услуги"
                            many="# услуг"
                            other="# услуги"
                          />
                        </>
                      ) : null}
                    </>
                  }
                />
                {readsFeed ? (
                  <Row
                    onClick={() => navigate('/mine?tab=incoming')}
                    leading={
                      <Tile tone={3}>
                        <InboxIcon size={19} />
                      </Tile>
                    }
                    title={<Trans>Входящие</Trans>}
                    hint={
                      waitingForMe > 0 ? (
                        <Plural
                          value={waitingForMe}
                          one="# заявка по твоим услугам"
                          few="# заявки по твоим услугам"
                          many="# заявок по твоим услугам"
                          other="# заявки по твоим услугам"
                        />
                      ) : undefined
                    }
                    trailing={
                      waitingForMe > 0 ? <Count>{waitingForMe}</Count> : undefined
                    }
                  />
                ) : null}
              </>
            ) : null}
          </Rows>

          {isHelper ? null : (
            <>
              <Label>
                <Trans>Помогать другим</Trans>
              </Label>
              <div style={{ marginTop: 4 }}>
                <Card>
                  <div
                    style={{ fontSize: 14.5, fontWeight: 680, letterSpacing: '-0.015em' }}
                  >
                    <Trans>Умеешь то, что нужно другим?</Trans>
                  </div>
                  <p
                    style={{
                      margin: '4px 0 0',
                      fontSize: 13,
                      lineHeight: 1.45,
                      color: 'var(--ink-soft)',
                    }}
                  >
                    <Trans>
                      Занятия, работы, документы. Анкета в каталоге — две минуты, ничего
                      обязательного.
                    </Trans>
                  </p>
                  <Actions>
                    {/* `/offer`, not the route that used to be here: `/become-helper`
                        was deleted with the screen behind it, and a bare string is
                        not something the compiler can catch. */}
                    <Action onClick={() => navigate('/offer')}>
                      <Trans>Предложить услугу</Trans>
                    </Action>
                  </Actions>
                </Card>
              </div>
            </>
          )}

          {/* The interface language and the palette live in the header, on
                every screen. What stays here is the one language question that
                is not a setting: which languages you can be taught in. */}
          <Label>
            <Trans>Языки</Trans>
          </Label>
          <Chips>
            {(languages ?? []).map((language) => (
              <ChipView
                key={language.code}
                active={me.spoken_langs.includes(language.code)}
                onClick={() => toggleLanguage(language.code)}
              >
                {language.name}
              </ChipView>
            ))}
          </Chips>
          <div style={{ marginTop: 9 }}>
            <Hint>
              <Trans>Их видно на твоей странице.</Trans>
            </Hint>
          </div>

          <Label>
            <Trans>Ещё</Trans>
          </Label>
          <Rows>
            <Row
              onClick={() => navigate('/life')}
              leading={
                <Tile tone={3}>
                  <SealIcon size={19} />
                </Tile>
              }
              title={<Trans>Жизнь в Чехии</Trans>}
              hint={<Trans>страховка, виза, банк, переводы</Trans>}
            />
            <Row
              onClick={() => navigate('/results?service=language_tutoring')}
              leading={
                <Tile tone={2}>
                  <LanguageIcon size={19} />
                </Tile>
              }
              title={<Trans>Чешский для вуза</Trans>}
              hint={<Trans>B1, B2, нострификация</Trans>}
            />
            <Row
              onClick={() => navigate('/ads')}
              leading={
                <Tile tone={1}>
                  <DocumentIcon size={19} />
                </Tile>
              }
              title={<Trans>Реклама для студентов</Trans>}
              hint={<Trans>для компаний: посты в чатах и карточки</Trans>}
            />
            {contactUrl ? (
              <Row
                onClick={() => openTelegramLink(contactUrl)}
                leading={
                  <Tile tone={0}>
                    <ChatIcon size={19} />
                  </Tile>
                }
                title={<Trans>Написать нам</Trans>}
                hint={<Trans>по любому вопросу</Trans>}
              />
            ) : null}
          </Rows>
        </>
      )}
    </Screen>
  );
}
