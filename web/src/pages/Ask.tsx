import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { AppHeader } from '@/components/AppHeader';
import { HelperCardView } from '@/components/HelperCard';
import {
  CheckIcon,
  ClockIcon,
  iconForService,
  PlusIcon,
  SearchIcon,
} from '@/components/icons';
import { ClarifyOptionLabel, PhraseView } from '@/components/Phrase';
import {
  Cards,
  Chips,
  ChipView,
  Count,
  Empty,
  Hint,
  Label,
  Row,
  Rows,
  Screen,
  SkeletonRows,
  Sub,
  Tile,
  Title,
  ui,
} from '@/components/Ui';
import { useSearchFilters } from '@/hooks/useSearchFilters';
import { useMainButton } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import { chipKey, chipLabel } from '@/lib/chips';
import type { Chip, ParseResult, SearchResult } from '@/lib/types';

const OPTION_ICON: Record<string, typeof CheckIcon> = {
  exam_prep: CheckIcon,
  exam_live_help: ClockIcon,
  both: PlusIcon,
};

/**
 * How much text counts as a query.
 *
 * Shared by the parse and by the empty state below it, which must agree about
 * when a query has begun: two literals would let the examples disappear while
 * nothing had been asked yet.
 */
const MIN_QUERY = 3;

/** How many of the results to show before the person has asked for them. */
const PREVIEW = 2;

/** How many kinds of help to name while the field is still empty. */
const SHELVES = 3;

/**
 * One field, then what we made of it.
 *
 * This screen exists so the catalog can have a single input instead of a
 * category tree. It shows the parse back as chips the person can remove, and
 * asks at most one question — and only when the answer changes the result.
 *
 * It also has to answer, before anything is typed and again after, the question
 * a bare text field never answers: what comes out of this? Empty, it names what
 * can be asked for and what the catalog holds. Filled, it shows the count and
 * the first two people on the screen itself. That count used to exist only on
 * Telegram's main button, which no browser has.
 */
export default function AskPage() {
  const navigate = useNavigate();
  const { t, i18n } = useLingui();
  const [text, setText] = useState('');
  const [parsed, setParsed] = useState<ParseResult | null>(null);
  const [dropped, setDropped] = useState<Set<string>>(new Set());
  const [answer, setAnswer] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const parse = useMutation({
    mutationFn: (value: string) => api.parseQuery(value),
    onSuccess: (result) => {
      setParsed(result);
      setDropped(new Set());
      setAnswer(null);
    },
    // A failed parse (a refusal, too many at once) must not leave the previous
    // text's chips standing as if they were this text's.
    onError: () => setParsed(null),
  });

  // Parse as the person pauses, not on every keystroke: each call is a round
  // trip and a logged query, and mid-word text parses to nonsense anyway.
  // The debounce must restart on the text and on nothing else: including the
  // mutation would reset the timer on every state change the mutation makes.
  // biome-ignore lint/correctness/useExhaustiveDependencies: see above
  useEffect(() => {
    const value = text.trim();
    if (value.length < MIN_QUERY) {
      setParsed(null);
      return;
    }
    const timer = setTimeout(() => parse.mutate(value), 450);
    return () => clearTimeout(timer);
  }, [text]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const kept = (parsed?.chips ?? []).filter((chip) => !dropped.has(chipKey(chip)));

  // One string, used for the preview, for the filters and for the navigation,
  // so none of the three can describe a different search.
  const query = useMemo(() => toQuery(kept, answer), [kept, answer]);

  // The words themselves travel too, but only on the way out. They are not a
  // filter, and putting them in the string this screen measures would make
  // every query "ready" from the first letter — a count of the whole catalog
  // under a screen that has understood nothing yet.
  const target = useMemo(
    () => withGuess(withWords(query, text), parsed?.also ?? null),
    [query, text, parsed],
  );

  // Empty when nothing the parse understood is something the search can filter
  // on — a lone deadline is the real case, since there is no date filter to send
  // it to. Counting that would count the whole catalog and put the number under
  // a chip that had no part in it.
  const ready = query !== '';

  // Nothing to filter on, but the embedder had an idea about what the sentence
  // is about. Without this the tier that idea exists for is unreachable from
  // here: no chips means no count, no count means no button, and the button is
  // the only way to the results screen.
  const onlyGuess = !ready && parsed?.also != null;

  // Understood something, but nothing to search on. Saying nothing here would be
  // a dead end: chips on the screen, no count, no button, no explanation.
  const stuck = !ready && !onlyGuess && kept.length > 0;
  const { filters, isError: filtersFailed } = useSearchFilters(query);

  const preview = useQuery({
    queryKey: ['ask-preview', filters],
    queryFn: ({ signal }) => api.search({ ...filters, limit: PREVIEW }, signal),
    enabled: ready && filters !== null,
  });

  // The number on the screen is the length of the list behind it, because both
  // come out of this one request. Taking it from the parse instead would make
  // the screen right only for as long as the two endpoints agree.
  const total = preview.data?.total;

  useMainButton(
    // Only once the count is the count. While a changed query is in flight the
    // button goes away rather than keeping the previous number under new chips:
    // a stale number on a button that promises it is the failure this screen was
    // rebuilt to fix.
    // Zero is a count too, and the way out of it is the other half of the
    // product: a search that found nobody used to hide the button and end the
    // screen, which is the one case a request exists for.
    ready && total !== undefined
      ? {
          text: total > 0 ? t`Показать ${total}` : t`Оставить заявку`,
          isVisible: true,
          isEnabled: true,
          isLoaderVisible: parse.isPending || preview.isFetching,
          onClick: () =>
            navigate(total > 0 ? `/results?${target}` : `/results?${target}&ask=1`),
        }
      : onlyGuess
        ? {
            // No number, because nothing is being filtered — the guess is shown
            // beside the results rather than narrowing them, and a count here
            // would be a promise about a list that does not exist.
            text: t`Посмотреть похожее`,
            isVisible: true,
            isEnabled: true,
            isLoaderVisible: parse.isPending,
            onClick: () => navigate(`/results?${target}`),
          }
        : null,
  );

  return (
    <Screen>
      <AppHeader />
      <Title>
        <Trans>Что нужно?</Trans>
      </Title>
      <Sub>
        <Trans>Напиши как думаешь. Поймём предмет, вуз, срок и бюджет.</Trans>
      </Sub>

      <div className={ui.field} style={{ alignItems: 'flex-start', marginTop: 16 }}>
        <SearchIcon size={18} className={ui.fieldIcon} />
        <textarea
          ref={inputRef}
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={t`матан на ČVUT к 14 февраля, до 600 Kč`}
          rows={2}
          style={{
            all: 'unset',
            width: '100%',
            resize: 'none',
            lineHeight: 1.4,
          }}
        />
      </div>

      {parsed?.note ? (
        <div style={{ marginTop: 14 }}>
          <Sub>
            <PhraseView phrase={parsed.note} locale={i18n.locale} />
          </Sub>
        </div>
      ) : null}

      {text.trim().length < MIN_QUERY ? <EmptyState onPick={setText} /> : null}

      {kept.length > 0 || (parsed?.chips.length ?? 0) > 0 ? (
        <>
          <Label>
            <Trans>Поняли так — поправь, если не то</Trans>
          </Label>
          <Chips>
            {(parsed?.chips ?? []).map((chip) => {
              const key = chipKey(chip);
              const isDropped = dropped.has(key);
              return (
                <ChipView
                  key={key}
                  active={!isDropped}
                  ghost={isDropped}
                  removeLabel={t`Убрать`}
                  onRemove={
                    isDropped ? undefined : () => setDropped(new Set(dropped).add(key))
                  }
                  onClick={
                    isDropped
                      ? () => {
                          const next = new Set(dropped);
                          next.delete(key);
                          setDropped(next);
                        }
                      : undefined
                  }
                >
                  {chipLabel(chip, i18n.locale)}
                </ChipView>
              );
            })}
          </Chips>
        </>
      ) : null}

      {parsed?.clarify ? (
        <>
          <Label>
            <PhraseView
              phrase={{ code: parsed.clarify.code, params: {} }}
              locale={i18n.locale}
            />
          </Label>
          <Rows>
            {parsed.clarify.options.map((option) => {
              const Icon = OPTION_ICON[option.code] ?? CheckIcon;
              return (
                <Row
                  key={option.code}
                  onClick={() => setAnswer(option.code)}
                  leading={
                    <Tile tone={option.tone}>
                      <Icon size={19} />
                    </Tile>
                  }
                  title={<ClarifyOptionLabel code={option.code} />}
                  trailing={answer === option.code ? <CheckIcon size={18} /> : undefined}
                />
              );
            })}
          </Rows>
          <div style={{ marginTop: 14 }}>
            <Hint>
              <Trans>Дальше вопросов не будет.</Trans>
            </Hint>
          </div>
        </>
      ) : null}

      {/* Last, and after the clarifying question rather than before it: the
          answer to that question changes the list, and a list shown above the
          thing that narrows it reads as already final. */}
      {stuck ? (
        <Empty
          title={<Trans>По этому пока не найти</Trans>}
          body={<Trans>Добавь предмет — по одному сроку искать нечего.</Trans>}
        />
      ) : null}

      {ready ? (
        <Preview
          data={preview.data}
          isPending={preview.isPending}
          isError={preview.isError || filtersFailed}
          locale={i18n.locale}
        />
      ) : null}
    </Screen>
  );
}

/**
 * What to type, and what is here to be found.
 *
 * The examples are the cheap half: a person who has just left a screen of
 * categories needs to be told that this field takes a sentence, not a keyword.
 * The shelves under them are the honest half — three kinds of help that
 * actually have someone behind them today.
 */
function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  const navigate = useNavigate();
  const { t } = useLingui();

  const { data } = useQuery({
    queryKey: ['home'],
    queryFn: ({ signal }) => api.getHome(signal),
  });

  // Not filtered by what the catalog holds, unlike the shelves below: an
  // example is there to show the shape of a query, and the shapes are true even
  // where nobody offers that yet. The shelves are the half that promises supply,
  // and those are counted.
  //
  // What an example must do is parse to what it says. Four of these have been
  // replaced for failing that: «страховка на год» parsed to nothing at all, and
  // «přijímačky на медицину» answered with the technical-university subject at
  // full confidence, because the parser reads the first word and has nothing to
  // say about medicine.
  //
  // The same bar applies to each **translation**, and it is not met by
  // translating the words: the parser matches against subject names in the
  // reader's language, so the Czech «matika» found linear algebra where the
  // Russian «матан» finds calculus, and the English «a term paper» found
  // mechanics. Every example, in all four catalogs, was checked by posting it to
  // /search/parse as a user of that language. Do that before changing one — an
  // example that misreads itself is a demonstration of the failure this screen
  // exists to remove.
  const examples = [
    t`матан ČVUT`,
    t`čeština B2`,
    t`помощь на экзамене по матану`,
    t`нострификация аттестата`,
    t`курсовая работа`,
  ];

  // Only what someone is actually offering. An empty shelf here would be the
  // screen advertising a thing it cannot deliver, which is the failure this
  // whole change is about.
  const shelves = [...(data?.people ?? [])]
    .filter((section) => section.count > 0)
    .sort((a, b) => b.count - a.count)
    .slice(0, SHELVES);

  return (
    <>
      <Label>
        <Trans>Например</Trans>
      </Label>
      <Chips>
        {examples.map((example) => (
          <ChipView key={example} ghost onClick={() => onPick(example)}>
            {example}
          </ChipView>
        ))}
      </Chips>

      {shelves.length > 0 ? (
        <>
          <Label>
            <Trans>Кого тут можно найти</Trans>
          </Label>
          <Rows>
            {shelves.map((section) => {
              const Icon = iconForService(section.code);
              return (
                <Row
                  key={section.code}
                  onClick={() => navigate(`/results?service=${section.code}`)}
                  leading={
                    <Tile tone={section.tone}>
                      <Icon size={19} />
                    </Tile>
                  }
                  title={section.name}
                  hint={section.hint}
                  // A count and no chevron, which is what the same shelf
                  // wears on the home screen. One row in two places has to
                  // look like one row.
                  trailing={<Count>{section.count}</Count>}
                />
              );
            })}
          </Rows>
        </>
      ) : null}
    </>
  );
}

/**
 * The first people the query finds, before the person has asked to see them.
 *
 * Two cards, because the point is not the list — it is that there is one, and
 * what the rows in it look like. Zero is said out loud here rather than left
 * to a main button reading "искать всё равно".
 */
function Preview({
  data,
  isPending,
  isError,
  locale,
}: {
  data: SearchResult | undefined;
  isPending: boolean;
  isError: boolean;
  locale: string;
}) {
  const navigate = useNavigate();

  // Before the skeleton: a failed lookup of the reference list leaves the
  // request disabled and therefore pending for ever, so an error checked second
  // would never be reached.
  if (isError) {
    return (
      <Empty
        title={<Trans>Не получилось посчитать</Trans>}
        body={<Trans>Проверь соединение и попробуй ещё раз.</Trans>}
      />
    );
  }

  if (isPending) {
    return (
      <>
        <Label>
          <Trans>Ищем…</Trans>
        </Label>
        <SkeletonRows count={PREVIEW} />
      </>
    );
  }

  if (!data) return null;

  const { total, results } = data;

  if (total === 0) {
    return (
      <Empty
        title={<Trans>По этому запросу пока никого</Trans>}
        body={<Trans>Убери что-нибудь из уточнений выше или напиши иначе.</Trans>}
      />
    );
  }

  return (
    <>
      {/* `data.total` rather than the `total` destructured above, deliberately:
          Lingui keys a message by its placeholders, and the member expression
          gives `всего {0}` — the message the results screen already has. A bare
          `total` would give `всего {total}` and split one sentence into two
          catalog entries to translate in four files. */}
      <Label aside={<Trans>всего {data.total}</Trans>}>
        <Trans>Кто найдётся</Trans>
      </Label>
      <Cards>
        {results.map((card) => (
          <HelperCardView
            key={card.user_id}
            card={card}
            locale={locale}
            onClick={() => navigate(`/helper/${card.user_id}`)}
          />
        ))}
      </Cards>
    </>
  );
}

/**
 * The guess the parse would not search by, carried to the results screen.
 *
 * Its own parameter and not `subject_id`: the difference between "this is what
 * you asked for" and "this might be what you meant" is the whole point, and one
 * of them filters the list while the other sits under it.
 */
function withGuess(query: string, also: ParseResult['also']): string {
  if (!also) return query;
  const params = new URLSearchParams(query);
  params.set('also_subject_id', String(also.subject_id));
  return params.toString();
}

/**
 * The same query with the person's own sentence attached.
 *
 * The results screen offers to turn the search into a request, and a request is
 * the sentence rather than the filters — rebuilt from chips it would read like
 * a form.
 */
function withWords(query: string, text: string): string {
  const words = text.trim();
  if (!words) return query;
  const params = new URLSearchParams(query);
  params.set('q', words);
  return params.toString();
}

/** Turn the chips the person kept into the search query string. */
function toQuery(chips: Chip[], answer: string | null): string {
  const params = new URLSearchParams();
  for (const chip of chips) {
    if (chip.value == null) continue;
    if (chip.kind === 'subject') params.set('subject_id', String(chip.value));
    if (chip.kind === 'institution') params.set('institution_id', String(chip.value));
    if (chip.kind === 'service_type') params.set('service_type_id', String(chip.value));
    if (chip.kind === 'budget') params.set('max_price', String(chip.value));
  }
  // The answer to the clarifying question is a service type by name. Resolving
  // it to an id belongs to `useSearchFilters`, which both this screen and the
  // results screen read the string through.
  if (answer && answer !== 'both') params.set('service', answer);
  return params.toString();
}
