import { Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import { api } from '@/lib/api';
import type { Chip } from '@/lib/types';
import { RequestSheet } from './RequestSheet';
import { Sheet } from './Sheet';
import { Action, Actions } from './Ui';

/**
 * A tile nobody offers yet, opened.
 *
 * Instead of the results screen: an empty list under tabs that sort nothing
 * says less than this does. The first thing on offer is to be the first one
 * here; the second is the request, as under any list that came up short.
 */
export function EmptyServiceSheet({
  service,
  onClose,
}: {
  service: { code: string; name: string };
  onClose: () => void;
}) {
  const { t } = useLingui();
  const navigate = useNavigate();
  const [asking, setAsking] = useState(false);

  // The request carries the service as a chip, and a chip carries the id.
  // Cached for an hour by every screen that shows tiles.
  const types = useQuery({
    queryKey: ['service-types'],
    queryFn: ({ signal }) => api.getServiceTypes(signal),
    staleTime: 60 * 60 * 1000,
  });
  const id = types.data?.find((type) => type.code === service.code)?.id;
  const chips: Chip[] =
    id === undefined
      ? []
      : [{ kind: 'service_type', label: service.name, value: id, confidence: 1 }];

  if (asking) {
    return (
      <RequestSheet text="" chips={chips} known={id !== undefined} onClose={onClose} />
    );
  }

  return (
    <Sheet title={service.name} onClose={onClose} closeLabel={t`Закрыть`}>
      <div style={{ padding: '4px 2px 0' }}>
        <div style={{ fontSize: 17, fontWeight: 700, letterSpacing: '-0.01em' }}>
          <Trans>Здесь пока никого</Trans>
        </div>
        <div style={{ marginTop: 4, fontSize: 14, lineHeight: 1.45 }}>
          <Trans>Твоя анкета будет здесь первой.</Trans>
        </div>
      </div>
      <Actions>
        <Action
          tall
          onClick={() =>
            navigate('/offer', { state: { picked: [service.code], from: 'home' } })
          }
        >
          <Trans>Предложить услугу</Trans>
        </Action>
      </Actions>
      <Actions>
        <Action quiet onClick={() => setAsking(true)}>
          <Trans>Оставить заявку</Trans>
        </Action>
      </Actions>
    </Sheet>
  );
}
