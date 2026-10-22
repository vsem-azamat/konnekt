import type { HelpRequest, SearchParams } from './types';

/**
 * «Не ждать»: who in the catalog could take an open request with no answers
 * yet, so its author can write to them instead of waiting.
 *
 * The request's own service, and its subject when it names one; the catalog
 * search already leaves out paused services, and `exclude_self` leaves out the
 * author's own profile. Null when there is nothing to ask for.
 */
export function dontWait(
  request: Pick<HelpRequest, 'status' | 'service_type_id' | 'subject_id'>,
): SearchParams | null {
  if (request.status !== 'open' || request.service_type_id === null) return null;
  return {
    service_type_id: request.service_type_id,
    ...(request.subject_id === null ? {} : { subject_id: request.subject_id }),
    exclude_self: true,
    limit: 3,
  };
}
