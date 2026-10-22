import { Trans } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { openTelegramLink } from '@tma.js/sdk-react';
import { useNavigate } from 'react-router';
import { AppHeader } from '@/components/AppHeader';
import {
  ChatIcon,
  DocumentIcon,
  LanguageIcon,
  PersonIcon,
  SealIcon,
} from '@/components/icons';
import {
  AvatarView,
  Chips,
  ChipView,
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

/**
 * Settings, and the way in to offering help.
 *
 * The languages someone speaks are not decoration here — they filter the
 * catalog. A Ukrainian first-year cannot work with a Czech-only tutor, so the
 * question is asked plainly rather than inferred.
 */
export default function ProfilePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: me, isPending } = useQuery({
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
      {isPending || !me ? (
        <>
          <Title>
            <Trans>Профиль</Trans>
          </Title>
          <div style={{ height: 16 }} />
          <SkeletonRows count={4} />
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

          {/* The interface language and the palette live in the header, on
                every screen. What stays here is the one language question that
                is not a setting: which languages you can be taught in. */}
          <Label>
            <Trans>На каких языках тебе удобно</Trans>
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
            <Trans>Помогать другим</Trans>
          </Label>
          <Rows>
            <Row
              // `/offer`, not the route that used to be here: `/become-helper`
              // was deleted with the screen behind it, and a bare string is
              // not something the compiler can catch.
              onClick={() => navigate(me.is_helper ? '/my-helper' : '/offer')}
              leading={
                <Tile tone={0}>
                  <PersonIcon size={19} />
                </Tile>
              }
              title={
                me.is_helper ? (
                  <Trans>Мои услуги</Trans>
                ) : (
                  <Trans>Предлагать услуги</Trans>
                )
              }
              hint={
                me.helper_status === 'published' ? (
                  <Trans>в каталоге</Trans>
                ) : me.helper_status === 'hidden' ? (
                  <Trans>скрыта — в каталоге её не видно</Trans>
                ) : me.helper_status === 'banned' ? (
                  <Trans>скрыта администратором</Trans>
                ) : me.is_helper ? (
                  <Trans>черновик — не видна в каталоге</Trans>
                ) : (
                  <Trans>расскажи своими словами, анкету соберём сами</Trans>
                )
              }
            />
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
