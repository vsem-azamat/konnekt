import { Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';

import { HelperCardView } from '@/components/HelperCard';
import { RequestSheet } from '@/components/RequestSheet';
import {
  Cards,
  Chips,
  ChipView,
  Empty,
  Label,
  Screen,
  Segmented,
  SkeletonRows,
  Sub,
  ui,
} from '@/components/Ui';
import { useSearchFilters } from '@/hooks/useSearchFilters';
import { hapticSelection } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import { chipKey, chipLabel } from '@/lib/chips';
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
    queryFn: ({ signal }) => api.search({ ...filters, sort }, signal),
    enabled: filters !== null && !onlyGuess,
  });

  const also = useQuery({
    queryKey: ['search-also', filters, guess, sort],
    // Every filter the parse *was* sure about still applies: the guess replaces
    // the subject and nothing else. A query that named a school and a budget
    // means them in this list too.
    queryFn: ({ signal }) =>
      api.search({ ...filters, subject_id: guess ?? undefined, sort }, signal),
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
  const closest = split ? matching : (data?.results ?? []);
  const rest = split
    ? (data?.results ?? []).filter((card) => !guessed.has(card.user_id))
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
        <Segmented
          value={sort}
          onChange={(next) => {
            hapticSelection();
            setSort(next);
          }}
          options={[
            { value: 'relevance', label: t`Подходят` },
            { value: 'price', label: t`Дешевле` },
            { value: 'available', label: t`Свободны` },
          ]}
        />

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
          </>
        ) : (
          <>
            <Label aside={<Trans>всего {data.total}</Trans>}>
              <Trans>Кто может помочь</Trans>
            </Label>
            {/* Why these are first. Two unexplained groups is worse than one
                list: the reader is owed the guess that reordered them. */}
            {split && alsoProps.named ? (
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
          </>
        )}
      </Screen>
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
