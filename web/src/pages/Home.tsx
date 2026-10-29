import { Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router';
import { AppHeader } from '@/components/AppHeader';
import { EmptyServiceSheet } from '@/components/EmptyServiceSheet';
import { PlusIcon, SearchIcon } from '@/components/icons';
import { ServiceGrid } from '@/components/ServiceGrid';
import { Showcase } from '@/components/Showcase';
import {
  AvatarStack,
  Chevron,
  Count,
  Label,
  Row,
  Rows,
  Screen,
  SkeletonRows,
  Tile,
  Title,
  ui,
} from '@/components/Ui';
import { api, meQuery } from '@/lib/api';
import { shelf } from '@/lib/showcase';
import type { HomeSection } from '@/lib/types';

/**
 * The first screen.
 *
 * The query field sits above the categories, not below them: someone who
 * already knows they need "нострификация аттестата" should never have to find
 * it in a tree. The categories are for the people who came to look around.
 */
export default function HomePage() {
  const navigate = useNavigate();
  const { t } = useLingui();
  const [empty, setEmpty] = useState<{ code: string; name: string } | null>(null);

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ['home'],
    queryFn: ({ signal }) => api.getHome(signal),
  });

  // The same `me` the header reads, so the two agree on who is a helper.
  const { data: me } = useQuery(meQuery);

  // Who a business writes to about a free paid place. The same query as the
  // ads page, so it is asked once an hour at most.
  const { data: ads } = useQuery({
    queryKey: ['ads'],
    queryFn: ({ signal }) => api.getAds(signal),
    staleTime: 60 * 60_000,
  });
  const contact = ads?.contact_url;
  // The paid places under «Документы и жизнь». None, while there is no card
  // and nobody to invite a partner to write to: the shelf is its tiles then.
  const paid = data
    ? shelf(
        data.showcase,
        data.people.filter((section) => section.group === 'life'),
        contact,
      )
    : null;

  // Nobody offers it yet: no list to open, so the tile says so and offers to
  // be the first, rather than opening an empty one.
  const pick = (section: HomeSection) =>
    section.count === 0
      ? setEmpty({ code: section.code, name: section.name })
      : navigate(`/results?service=${section.code}`);

  return (
    <Screen>
      <AppHeader />
      <Title>
        <Trans>Что нужно?</Trans>
      </Title>

      <button
        type="button"
        className={`${ui.field} ${ui.fieldGhost} ${ui.pressable}`}
        style={{ marginTop: 16 }}
        onClick={() => navigate('/ask')}
      >
        <SearchIcon size={18} className={ui.fieldIcon} />
        <span>{t`математический анализ, čeština B2…`}</span>
      </button>

      {isPending ? (
        <SkeletonRows count={6} />
      ) : isError ? (
        <Rows>
          <Row
            title={<Trans>Не удалось загрузить каталог</Trans>}
            hint={<Trans>Нажми, чтобы попробовать ещё раз</Trans>}
            onClick={() => void refetch()}
          />
        </Rows>
      ) : (
        // Grouped, with a heading per shelf. An odd-sized group widens its
        // first tile, which is what keeps the last one from sitting alone in
        // its row.
        <>
          <ServiceGrid
            // «Документы и жизнь» is the last shelf, so drawing it on its own
            // after the grid keeps it where it was.
            items={
              paid
                ? data.people.filter((section) => section.group !== 'life')
                : data.people
            }
            onPick={pick}
            renderTrailing={(section, wide) => {
              // Faces on every shelf that has any, not only where a wide cell
              // happened to fall. Which shelf got one was decided by whether
              // its number of tiles is odd, so «Учёба» — the fullest shelf in
              // the catalog — was the one that never showed a face.
              //
              // Two of them in a narrow tile rather than three: they share
              // the line with the hint, and each face costs it about a word.
              // On the narrowest phone that is most of the hint — "математика,
              // физика, экономика, программирование" keeps its first word.
              // Taken: a hint that lists examples of a category the name
              // already gives is worth less than the faces of people offering
              // it.
              if (!section.avatars.length && !section.count) return null;
              return (
                <>
                  {section.avatars.length ? (
                    <AvatarStack
                      avatars={wide ? section.avatars : section.avatars.slice(0, 2)}
                      size={wide ? 24 : 19}
                    />
                  ) : null}
                  {section.count ? <Count>{section.count}</Count> : null}
                </>
              );
            }}
          />
          {paid ? <Showcase shelf={paid} contact={contact} onPick={pick} /> : null}
        </>
      )}

      {/* The way in for the few who could offer something, under the shelves
          rather than above them: most people here came to find help, and the
          grid is theirs. Worded as the profile's card is, so the offer reads
          the same wherever it is made. Not drawn until `me` has answered: a
          helper must not see it flash in and out. */}
      {me && !me.is_helper ? (
        <>
          <Label>
            <Trans>Помогать другим</Trans>
          </Label>
          <Rows>
            <Row
              outline
              onClick={() => navigate('/offer', { state: { from: 'home' } })}
              leading={
                <Tile tone={1}>
                  <PlusIcon size={19} />
                </Tile>
              }
              title={<Trans>Умеешь то, что нужно другим?</Trans>}
              hint={<Trans>Предложи услугу — студенты напишут сами</Trans>}
              trailing={<Chevron />}
            />
          </Rows>
        </>
      ) : null}

      {empty ? (
        <EmptyServiceSheet service={empty} onClose={() => setEmpty(null)} />
      ) : null}
    </Screen>
  );
}
