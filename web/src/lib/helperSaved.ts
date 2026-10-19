/**
 * What the app forgets and learns once a helper's services are saved.
 *
 * Both screens that save a profile end here. Here rather than in a page so it
 * can be proven without rendering: «Моя анкета» fills its form once from
 * whatever the cache holds when it mounts, and so does the «+» in Offer.
 */

import type { QueryClient } from '@tanstack/react-query';

import type { Me } from './types';

export function afterHelperSaved(queryClient: QueryClient, me: Me): void {
  queryClient.setQueryData(['me'], me);
  // Removed, not invalidated. Invalidation keeps the copy loaded before the
  // save, and so does a refetch cancelled by leaving the screen (it reverts).
  // The next screen filled its form from that copy, and its «Сохранить» put
  // back the old list: services just published or just deleted were undone.
  // Without a copy it waits for the server.
  queryClient.removeQueries({ queryKey: ['my-helper'] });
  void queryClient.invalidateQueries({ queryKey: ['home'] });
}
