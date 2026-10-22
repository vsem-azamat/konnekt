import type { HelpRequest } from './types';

/**
 * The requests still waiting for help, and how many answers they have: what
 * «Мои заявки» in the profile says. A closed or expired request is history,
 * and a draft has not been asked yet.
 */
export function openRequests(requests: HelpRequest[]): {
  requests: number;
  responses: number;
} {
  const open = requests.filter((request) => request.status === 'open');
  return {
    requests: open.length,
    responses: open.reduce((sum, request) => sum + request.responses_count, 0),
  };
}
