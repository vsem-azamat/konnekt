import { Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';

import { HelperCardView } from '@/components/HelperCard';
import { ChevronIcon, SearchIcon } from '@/components/icons';
import { RequestSheet } from '@/components/RequestSheet';
import { Pick, Sheet } from '@/components/Sheet';
import {
  Action,
  Actions,
  Cards,
  Chips,
  ChipView,
  Empty,
  Label,
  Screen,
  SkeletonRows,
  Sub,
  ui,
} from '@/components/Ui';
import { useSearchFilters } from '@/hooks/useSearchFilters';
import { hapticSelection } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import { chipKey, chipLabel } from '@/lib/chips';
import { find } from '@/lib/search';
import type { HelperCard, SearchSort } from '@/lib/types';

/**
 * The results list.
 *
 * Every card carries the reason the person is on it. When that reason is
 * "cheaper than the rest, but has never seen your exam", it says so — which is
 * what makes the rows above it worth believing.
 */
export default function ResultsPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { t, i18n } = useLingui();
  const [sort, setSort] = useState<SearchSort>('relevance');
  const [sorting, setSorting] = useState(false);
  const [needle, setNeedle] = useState('');
  // Opened straight away when the search screen sent somebody here because it
  // found nobody: the button there said «Оставить заявку», and landing on an
  // empty list with the sheet still shut would be that promise unkept.
  const [asking, setAsking] = useState(params.get('ask') === '1');

  // The words behind the chips. A link somebody was sent may carry only the
  // ids, in which case the sheet opens on an empty field rather than not at
  // all — the request is the person's own sentence either way.
  const words = params.get('q') ?? '';

  // A subject the parser guessed at and would not search by. It never touches
  // the query above — the list stays the search the person asked for — and this
  // is a second, ordinary search shown under its own heading.
  const guess = Number(params.get('also_subject_id')) || null;

  // The same reading of the query string the search screen used to count and
  // preview this list, so the number it showed is the number that arrives here.
  const { filters, isError: filtersFailed } = useSearchFilters(params);

  // The service this list is for, handed to «Предложить услугу» so the tile is
  // already ticked there. By id: a tile sends its code, but /ask sends the id
  // of the service it read from the query, and both end up here.
  const serviceId = filters?.service_type_id ?? null;
  const types = useQuery({
    queryKey: ['service-types'],
    queryFn: ({ signal }) => api.getServiceTypes(signal),
    staleTime: 60 * 60 * 1000,
  });
  const serviceCode = types.data?.find((type) => type.id === serviceId)?.code;
  const offer = () =>
    navigate('/offer', {
      state: { picked: serviceCode ? [serviceCode] : [], from: 'results' },
    });
  // Somebody who already offers this is on the list, and «добавь себя» would
  // be asking them to do what they did. Not drawn until that is known, or a
  // helper sees it flash in and out.
  const mine = useQuery({
    queryKey: ['my-helper'],
    queryFn: ({ signal }) => api.getMyHelper(signal),
  });
  const offersThis =
    serviceId !== null &&
    (mine.data?.offers ?? []).some((offer) => offer.service_type_id === serviceId);
  const inviting = (mine.isSuccess || mine.isError) && !offersThis;

  // Nothing to filter on and only a guess to go by. There is no list to show
  // above the guess then, and running the search anyway would count the whole
  // catalog under somebody's question — which is exactly what `/ask` refuses to
  // do — and then subtract every one of those people from the guess's own list,
  // leaving it empty. So the guess is the screen.
  const onlyGuess =
    guess !== null &&
    filters !== null &&
    !filters.subject_id &&
    !filters.institution_id &&
    !filters.service_type_id &&
    !filters.max_price;

  // `filters` and not `{...filters}`: spread onto an object, a null — the
  // service code has not been resolved yet — becomes the same key as a search
  // with no filters at all. A warm cache from an unfiltered visit would then be
  // handed over as this query's answer, and the screen would show the whole
  // catalog under one person's query before quietly swapping it out.
  const { data, isPending, isError } = useQuery({
    queryKey: ['search', filters, sort],
    // The field above the list searches inside it, so it loads as much of it
    // as the API gives in one page rather than the first 20.
    queryFn: ({ signal }) => api.search({ ...filters, sort, limit: 50 }, signal),
    enabled: filters !== null && !onlyGuess,
  });

  const also = useQuery({
    queryKey: ['search-also', filters, guess, sort],
    // Every filter the parse *was* sure about still applies: the guess replaces
    // the subject and nothing else. A query that named a school and a budget
    // means them in this list too.
    queryFn: ({ signal }) =>
      // As many as the list itself loads: the top group is where the two
      // overlap, so a shorter page here would send its 21st person to «Также».
      api.search({ ...filters, subject_id: guess ?? undefined, sort, limit: 50 }, signal),
    enabled: guess !== null && filters !== null,
  });

  // Unknown filters are still loading, not loaded. The error takes precedence,
  // or a failed lookup would keep the skeleton up for ever.
  const failed = isError || filtersFailed;
  const loading = (isPending || filters === null) && !failed && !onlyGuess;

  const alsoProps = {
    cards: also.data?.results ?? [],
    named: also.data?.chips.find((chip) => chip.kind === 'subject')?.label ?? null,
    locale: i18n.locale,
    onOpen: (id: number) => navigate(`/helper/${id}`),
  };

  // The guess sorts the list it cannot filter.
  //
  // A second list was the obvious shape and the wrong one: the guess search is
  // this search plus a subject, so its people are a subset of these people and
  // a section that leaves out everyone already shown is always empty. What the
  // guess is actually good for is order — the people who teach the subject we
  // think was meant go first, and everybody else the search found goes under
  // «Также», which is the honest word for "these matched what you typed, but
  // not what we think you meant".
  const guessed = new Set((also.data?.results ?? []).map((card) => card.user_id));
  const matching = (data?.results ?? []).filter((card) => guessed.has(card.user_id));
  // Split only when the guess actually lifted somebody. It can match people the
  // main search ranked past its first page, and then the top group would be an
  // empty list under a heading counting everybody.
  const split = matching.length > 0;
  // The field above the list: narrows the people already loaded, by name or
  // school, matched as the chat search matches («чвут» finds ČVUT). Not a new
  // search — the service, subject and school are the chips above.
  const wanted = needle.trim() !== '';
  const kept = new Set(
    find(data?.results ?? [], (card) => [card.name, card.affiliation], needle).map(
      (card) => card.user_id,
    ),
  );
  const found = (card: HelperCard) => kept.has(card.user_id);
  const closest = (split ? matching : (data?.results ?? [])).filter(found);
  const rest = split
    ? (data?.results ?? []).filter((card) => !guessed.has(card.user_id)).filter(found)
    : [];

  return (
    <>
      <Screen>
        {data && data.chips.length > 0 ? (
          <div style={{ marginBottom: 12 }}>
            <Chips>
              {data.chips.map((chip) => (
                <ChipView key={chipKey(chip)} active>
                  {chipLabel(chip, i18n.locale)}
                </ChipView>
              ))}
              <ChipView ghost onClick={() => navigate('/ask')}>
                <Trans>изменить</Trans>
              </ChipView>
            </Chips>
          </div>
        ) : (
          <div style={{ height: 8 }} />
        )}

        {onlyGuess ? (
          // The guess *is* the list here, so it owns the states an ordinary
          // list has: a skeleton while it is in flight, and the load failure
          // when it fails. Without that the screen said «Не поняли запрос»
          // during the round trip, and kept saying it when the request failed.
          also.isPending ? (
            <>
              <Label>
                <Trans>Ищем…</Trans>
              </Label>
              <SkeletonRows count={3} />
            </>
          ) : also.isError ? (
            <Empty
              title={<Trans>Не получилось загрузить</Trans>}
              body={<Trans>Проверь соединение и попробуй ещё раз.</Trans>}
            />
          ) : (also.data?.results.length ?? 0) === 0 ? (
            // Nothing to filter by and nothing behind the guess either: the
            // honest thing is to say the query was not understood, which is
            // the one screen where that is true.
            <>
              <Empty
                title={<Trans>Не поняли запрос</Trans>}
                body={<Trans>Напиши иначе — или оставь заявку, и найдут тебя.</Trans>}
              />
              <AskInstead onClick={() => setAsking(true)} found={0} />
            </>
          ) : (
            <>
              <AlsoSection {...alsoProps} />
              <AskInstead
                onClick={() => setAsking(true)}
                found={alsoProps.cards.length}
              />
            </>
          )
        ) : loading ? (
          <>
            <Label>
              <Trans>Ищем…</Trans>
            </Label>
            <SkeletonRows count={4} />
          </>
        ) : failed || !data ? (
          <Empty
            title={<Trans>Не получилось загрузить</Trans>}
            body={<Trans>Проверь соединение и попробуй ещё раз.</Trans>}
          />
        ) : data.total === 0 ? (
          <>
            <Empty
              title={<Trans>Пока никого</Trans>}
              body={<Trans>Никто пока не предлагает то, что ты ищешь.</Trans>}
            />
            <AskInstead onClick={() => setAsking(true)} found={0} />
            {inviting ? <OfferYourself onClick={offer} /> : null}
          </>
        ) : (
          <>
            {data.total > 8 ? (
              // Not over a handful: four cards need no search, and the field
              // would only push them down.
              <div className={ui.field} style={{ marginTop: 4 }}>
                <SearchIcon size={18} className={ui.fieldIcon} />
                <input
                  type="search"
                  enterKeyHint="search"
                  aria-label={t`Поиск по имени или вузу`}
                  value={needle}
                  onChange={(event) => setNeedle(event.target.value)}
                  placeholder={t`Имя или вуз`}
                  maxLength={100}
                  style={{ all: 'unset', flex: 1, minWidth: 0 }}
                />
              </div>
            ) : null}
            <Label
              aside={
                <button
                  type="button"
                  className={`${ui.sortButton} ${ui.pressable}`}
                  aria-haspopup="dialog"
                  onClick={() => setSorting(true)}
                >
                  <SortName sort={sort} />
                  <ChevronIcon size={14} className={ui.sortChevron} />
                </button>
              }
            >
              {wanted && data.total > data.results.length ? (
                // Only the loaded page is searched; past it, «никого» would be
                // a claim about people it never looked at.
                <Trans>
                  Нашлось {closest.length + rest.length} среди первых{' '}
                  {data.results.length}
                </Trans>
              ) : wanted ? (
                <Trans>Нашлось {closest.length + rest.length}</Trans>
              ) : (
                <Trans>Кто может помочь · {data.total}</Trans>
              )}
            </Label>
            {/* Why these are first. Two unexplained groups is worse than one
                list: the reader is owed the guess that reordered them. */}
            {split && closest.length > 0 && alsoProps.named ? (
              <Sub>
                <Trans>Сверху — кто ведёт «{alsoProps.named}»</Trans>
              </Sub>
            ) : null}
            <Cards>
              {closest.map((card) => (
                <HelperCardView
                  key={card.user_id}
                  card={card}
                  locale={i18n.locale}
                  onClick={() => navigate(`/helper/${card.user_id}`)}
                />
              ))}
            </Cards>
            {rest.length > 0 ? (
              <>
                <Label>
                  <Trans>Также</Trans>
                </Label>
                <Cards>
                  {rest.map((card) => (
                    <HelperCardView
                      key={card.user_id}
                      card={card}
                      locale={i18n.locale}
                      onClick={() => navigate(`/helper/${card.user_id}`)}
                    />
                  ))}
                </Cards>
              </>
            ) : null}
            {/* Not only when the search failed. Choosing from a list and
                letting the list choose you are two ways of doing the same
                thing, and the second one is the whole other half of the
                product. */}
            <AskInstead onClick={() => setAsking(true)} found={data.total} />
            {inviting ? <OfferYourself onClick={offer} /> : null}
          </>
        )}
      </Screen>
      {sorting ? (
        <Sheet
          title={<Trans>Сначала показывать</Trans>}
          onClose={() => setSorting(false)}
          closeLabel={t`Закрыть`}
        >
          {(['relevance', 'price', 'available'] as const).map((value) => (
            <Pick
              key={value}
              name={<SortName sort={value} />}
              hint={<SortHint sort={value} />}
              selected={sort === value}
              onClick={() => {
                hapticSelection();
                setSort(value);
                setSorting(false);
              }}
            />
          ))}
        </Sheet>
      ) : null}
      {asking ? (
        <RequestSheet
          text={words}
          chips={data?.chips ?? []}
          // `ask=1` opens the sheet on the first render, before the search has
          // answered — and after it fails. Neither is "this query filters on
          // nothing", which is what an empty list would otherwise say.
          known={data !== undefined}
          onClose={() => setAsking(false)}
        />
      ) : null}
    </>
  );
}

/**
 * The other way out of a search.
 *
 * A dashed row rather than a card: it is not one of the results, and drawn
 * like one it would be read as a person. The wording changes with the count
 * because "nobody suits you" makes no sense on an empty list and "leave a
 * request" alone makes none under twelve.
 */
function AskInstead({ onClick, found }: { onClick: () => void; found: number }) {
  return (
    <button type="button" className={ui.instead} onClick={onClick}>
      <span>
        <b>
          {found > 0 ? (
            <Trans>Никто не подошёл?</Trans>
          ) : (
            <Trans>Пусть найдут тебя</Trans>
          )}
        </b>
        <Trans>Оставь заявку — ответят сами</Trans>
      </span>
      <span className={ui.insteadGo}>
        <Trans>Оставить</Trans>
      </span>
    </button>
  );
}

/** What the list is ordered by, in the same words on the button and in the sheet. */
function SortName({ sort }: { sort: SearchSort }) {
  switch (sort) {
    case 'price':
      return <Trans>Дешевле</Trans>;
    case 'available':
      return <Trans>Есть свободное время</Trans>;
    default:
      return <Trans>Подходят лучше</Trans>;
  }
}

function SortHint({ sort }: { sort: SearchSort }) {
  switch (sort) {
    case 'price':
      return <Trans>по цене, от меньшей</Trans>;
    case 'available':
      return <Trans>у кого есть окна, и кто быстрее отвечает</Trans>;
    default:
      return <Trans>твой вуз и предмет, потом кто больше занимался</Trans>;
  }
}

/**
 * The third way out: be on this list yourself.
 *
 * The person who needed a tutor last term is the one who can be one now. The
 * same words as on «Профиль», so the offer reads as one thing wherever it is.
 * A filled card rather than another dashed row: under the request row it was
 * read as a second way of asking (Azamat's pick, 2026-10-29).
 */
function OfferYourself({ onClick }: { onClick: () => void }) {
  return (
    <div className={ui.offerCard}>
      <b>
        <Trans>Умеешь то, что нужно другим?</Trans>
      </b>
      <span>
        <Trans>Добавь себя в этот список — студенты напишут тебе сами.</Trans>
      </span>
      <Actions>
        {/* Quiet: students are most of the people here, and this must not
            outshout their own way out, the request row above. */}
        <Action tall quiet onClick={onClick}>
          <Trans>Предложить услугу</Trans>
        </Action>
      </Actions>
    </div>
  );
}

/**
 * The guess, when it is the whole screen.
 *
 * Only for a query that gave nothing else to search by: there is no list for
 * these people to be sorted into, so they are the list, and the heading says
 * where they came from. When the query *did* give something to search by, the
 * guess sorts that list instead — see `closest` and `rest` above.
 */
function AlsoSection({
  cards,
  named,
  locale,
  onOpen,
}: {
  cards: HelperCard[];
  /** The subject it guessed, as the server named it in the reader's language. */
  named: string | null;
  locale: string;
  onOpen: (id: number) => void;
}) {
  if (cards.length === 0) return null;

  return (
    <>
      {/* Named, or the heading is a shrug: the reader is owed the reason these
          people are on a screen their query did not describe, and the reason is
          that this is what we think they meant. */}
      <Label aside={named}>
        <Trans>Похоже, речь о</Trans>
      </Label>
      <Cards>
        {cards.map((card) => (
          <HelperCardView
            key={card.user_id}
            card={card}
            locale={locale}
            onClick={() => onOpen(card.user_id)}
          />
        ))}
      </Cards>
    </>
  );
}
