import { Trans } from '@lingui/react/macro';

import { HideReasonText } from '@/components/HideReasonText';
import { ui } from '@/components/Ui';
import { allPaused } from '@/lib/myServices';
import type { OwnerStatus } from '@/lib/ownerStatus';
import type { MyHelper } from '@/lib/types';

/**
 * Where the profile stands, and who can change that: the owner's own states
 * and an operator's hide with its reason.
 *
 * Two screens show it. «О себе и как работаю» holds «Видимость», so its hints
 * point below; «Мои услуги» holds the switches. Neither shows «на проверке»:
 * a profile not looked at yet is listed already, and the approved screens say
 * just that.
 */
export function OwnerStatusCard({
  status,
  helper,
  listed,
  place,
}: {
  status: OwnerStatus;
  helper: MyHelper;
  /** «Видимость» as it is now on the form, which the draft's hint talks about. */
  listed: boolean;
  place: 'services' | 'about';
}) {
  const shown: Shown = status === 'review' ? 'listed' : status;
  return (
    <div className={ui.ownerStatus} data-status={shown}>
      <span className={ui.ownerStatusTitle}>
        {shown === 'draft' ? (
          <Trans>Черновик</Trans>
        ) : shown === 'listed' ? (
          <Trans>В каталоге</Trans>
        ) : shown === 'hidden' ? (
          <Trans>Скрыта тобой</Trans>
        ) : (
          <Trans>Скрыта администратором</Trans>
        )}
      </span>
      {shown === 'banned' && helper.hidden_reason ? (
        <span>
          {helper.hidden_reason === 'other' && helper.hidden_note ? (
            <Trans>Причина: {helper.hidden_note}</Trans>
          ) : (
            <Trans>
              Причина: <HideReasonText reason={helper.hidden_reason} />
            </Trans>
          )}
        </span>
      ) : null}
      <span>
        {place === 'services' ? (
          <ServicesHint status={shown} helper={helper} />
        ) : (
          <AboutHint status={shown} helper={helper} listed={listed} />
        )}
      </span>
    </div>
  );
}

type Shown = Exclude<OwnerStatus, 'review'>;

function ServicesHint({ status, helper }: { status: Shown; helper: MyHelper }) {
  switch (status) {
    case 'draft':
      return (
        <Trans>Пока её видишь только ты. Опубликовать — в «О себе и как работаю».</Trans>
      );
    case 'listed':
      // Listed, and in no list: they filter on the service.
      return allPaused(helper) ? (
        <Trans>
          Все услуги выключены, поэтому тебя сейчас не найдут. Включи хотя бы одну.
        </Trans>
      ) : (
        <Trans>Тебя видят студенты. Выключатель скрывает одну услугу.</Trans>
      );
    case 'hidden':
      return <Trans>В каталоге её нет. Вернуть — в «О себе и как работаю».</Trans>;
    case 'banned':
      return <BannedHint helper={helper} />;
  }
}

function AboutHint({
  status,
  helper,
  listed,
}: {
  status: Shown;
  helper: MyHelper;
  listed: boolean;
}) {
  switch (status) {
    case 'draft':
      // A new profile starts on «В каталоге» (startsListed), so the hint
      // says what saving does rather than ask for a choice already made.
      return listed ? (
        <Trans>
          Пока её видишь только ты. Ниже уже стоит «В каталоге»: нажми «Сохранить», и
          анкета появится в поиске.
        </Trans>
      ) : (
        <Trans>Пока её видишь только ты. Выбери «В каталоге», когда всё готово.</Trans>
      );
    case 'listed':
      return <Trans>Тебя видят в поиске и могут написать.</Trans>;
    case 'hidden':
      return <Trans>Анкета сохранена, но в каталоге её нет. Вернуть можно ниже.</Trans>;
    case 'banned':
      return <BannedHint helper={helper} />;
  }
}

function BannedHint({ helper }: { helper: MyHelper }) {
  return helper.under_review ? (
    <Trans>
      В каталоге её не видно. Правки сохранены, администратор посмотрит анкету ещё раз.
    </Trans>
  ) : (
    <Trans>
      В каталоге её не видно. Править анкету можно, правки сохранятся, но вернуть её в
      каталог может только администратор.
    </Trans>
  );
}
