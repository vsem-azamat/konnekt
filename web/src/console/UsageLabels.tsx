import { useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';

import { type FunnelKey, sourceKind, tapDetail } from '@/console/usage';
import { institutionsQuery } from '@/lib/api';

/**
 * The words for what «Использование» and «Источники» count: screens by their
 * route pattern, taps by event and detail, launch sources, funnel steps. A
 * key nobody named yet shows as itself rather than not at all.
 */
export function useUsageLabels() {
  const { t } = useLingui();
  // A school by the name the rest of the app gives it (ČVUT), not its code (cvut).
  const institutions = useQuery(institutionsQuery).data ?? [];
  const school = (code: string) => {
    const found = institutions.find((i) => i.code === code);
    return found?.short_name ?? found?.name ?? code.toUpperCase();
  };

  const screens: Record<string, string> = {
    '/home': t`Главная`,
    '/chats': t`Чаты`,
    '/chats/:group': t`Раздел чатов`,
    '/results': t`Поиск, результаты`,
    '/mine': t`Мои заявки`,
    '/profile': t`Профиль`,
    '/ads': t`Реклама`,
    '/ads/chats': t`Реклама в чатах`,
    '/ads/app': t`Реклама в приложении`,
    '/ask': t`Новая заявка`,
    '/helper/:id': t`Карточка помощника`,
    '/join': t`Вход в чат`,
    '/request/:id': t`Заявка и ответы`,
    '/offer': t`Стать помощником`,
    '/offer/prices': t`Стать помощником: цены`,
    '/my-helper': t`Мои услуги`,
    '/my-helper/about': t`Мои услуги: о себе`,
    '/life': t`Жизнь в Чехии`,
    '/partner/:id': t`Партнёр`,
  };
  const tabs: Record<string, string> = {
    home: t`Помощь`,
    chats: t`Чаты`,
    mine: t`Заявки`,
    profile: t`Профиль`,
  };
  // Where a tap came from (lib/track.ts): a way in, or the screen before.
  const froms: Record<string, string> = {
    home: t`с главной`,
    results: t`из поиска`,
    ask: t`из заявки`,
    request: t`из заявки`,
    chats: t`из чатов`,
    profile: t`из профиля`,
    'my-helper': t`из «Моих услуг»`,
    tab: t`кнопка «+»`,
    link: t`по ссылке`,
    helper: t`с карточки`,
    partner: t`страница партнёра`,
    block: t`блок на экране`,
    other: t`другое`,
  };
  const filters: Record<string, string> = {
    sort: t`сортировка`,
  };
  const taps: Record<string, string> = {
    search_submit: t`Найти`,
    helper_open: t`Открыть помощника`,
    contact_tap: t`Написать`,
    offer_start: t`Стать помощником`,
    request_send: t`Отправить заявку`,
    chat_open: t`Вступить в чат`,
    partner_tap: t`Партнёр`,
  };
  const links: Record<string, string> = {
    welcome: t`Кнопка в приветствии чата`,
    captcha: t`Сообщение капчи`,
    captcha_passed: t`Капча пройдена`,
    chats: t`Кнопка «Чаты» в боте`,
    offer: t`Ссылка «Предложить помощь»`,
  };
  const places: Record<string, string> = {
    hero: t`первый экран`,
    header: t`шапка`,
    footer: t`подвал`,
    chats: t`блок чатов`,
    chats_empty: t`пустой поиск чатов`,
    tutors: t`репетиторы`,
    university: t`страница вуза`,
    helper: t`страница репетитора`,
  };
  const steps: Record<FunnelKey, Record<string, string>> = {
    find: {
      opened: t`Открыли приложение`,
      searched: t`Искали`,
      found: t`Нашли кого-то`,
      helper: t`Открыли карточку`,
      contact: t`Нажали «Написать»`,
    },
    chats: {
      opened: t`Открыли приложение`,
      chats: t`Открыли «Чаты»`,
      section: t`Открыли раздел`,
      joined: t`Нажали «Вступить»`,
    },
    offer: {
      opened: t`Открыли приложение`,
      offer: t`Начали «Стать помощником»`,
      prices: t`Дошли до цен`,
    },
  };

  return {
    screen(pattern: string): string {
      if (pattern.startsWith('/console')) return t`Консоль`;
      return screens[pattern] ?? pattern;
    },
    tap(name: string, detail: string | null): string {
      if (name === 'tab_tap') {
        const tab = detail ? (tabs[detail] ?? detail) : '—';
        return t`Вкладка «${tab}»`;
      }
      if (name === 'filter_change') {
        const filter = detail ? (filters[detail] ?? detail) : '—';
        return t`Фильтр: ${filter}`;
      }
      const base = taps[name] ?? name;
      const about = tapDetail(name, detail);
      switch (about.kind) {
        case 'none':
          return base;
        case 'school':
          return `${base} · ${school(about.code)}`;
        case 'general':
          return `${base} · ${t`общие`}`;
        case 'from':
          return `${base} · ${froms[about.key] ?? about.key}`;
      }
    },
    source(source: string | null): string {
      const kind = sourceKind(source);
      switch (kind.kind) {
        case 'none':
          return t`Без метки`;
        case 'article': {
          const slug = kind.slug;
          return t`Статья на сайте: ${slug}`;
        }
        case 'site': {
          const place = places[kind.place] ?? kind.place;
          return t`Сайт: ${place}`;
        }
        case 'university': {
          const name = school(kind.code);
          return t`Чаты вуза ${name}`;
        }
        case 'link':
          return links[kind.key] ?? kind.key;
      }
    },
    step(funnel: FunnelKey, key: string): string {
      return steps[funnel][key] ?? key;
    },
    funnel: {
      find: t`Поиск помощника`,
      chats: t`Чаты`,
      offer: t`Стать помощником`,
    } satisfies Record<FunnelKey, string>,
  };
}
