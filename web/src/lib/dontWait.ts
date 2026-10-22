import type { HelpRequest, SearchParams } from './types';

/**
 * «Не ждать»: who in the catalog could take an open request with no answers
 * yet, so its author can write to them instead of waiting.
 *
 * Whichever of the request's service and subject it names, the way the server
 * counts `helpers_seeing`; the catalog search already leaves out paused
 * services, and `exclude_self` leaves out the author's own profile. Null when
 * there is nothing to ask for, including when the server counted nobody.
 */
export function dontWait(
  request: Pick<
    HelpRequest,
    'status' | 'helpers_seeing' | 'service_type_id' | 'subject_id'
  >,
): SearchParams | null {
  const { service_type_id, subject_id } = request;
  if (request.status !== 'open' || request.helpers_seeing === 0) return null;
  if (service_type_id === null && subject_id === null) return null;
  return {
    ...(service_type_id === null ? {} : { service_type_id }),
    ...(subject_id === null ? {} : { subject_id }),
    exclude_self: true,
    limit: 3,
  };
}
