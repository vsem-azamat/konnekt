import { Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { AppHeader } from '@/components/AppHeader';
import { SearchIcon } from '@/components/icons';
import { ServiceGrid } from '@/components/ServiceGrid';
import { TabBar } from '@/components/TabBar';
import {
  AvatarStack,
  Count,
  Row,
  Rows,
  Screen,
  SkeletonRows,
  Title,
  ui,
} from '@/components/Ui';
import { api } from '@/lib/api';

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

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ['home'],
    queryFn: ({ signal }) => api.getHome(signal),
  });

  return (
    <>
      <Screen withTabs>
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
          <span>{t`математика, čeština B2, вступительные экзамены…`}</span>
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
          <ServiceGrid
            items={data.people}
            onPick={(section) => navigate(`/results?service=${section.code}`)}
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
        )}
      </Screen>
      <TabBar />
    </>
  );
}
