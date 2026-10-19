/**
 * What the app forgets and learns once a helper's services are saved.
 *
 * Here rather than in the page so it can be proven without rendering: the
 * page navigates to «Моя анкета» straight after this, and that screen fills
 * its form once from whatever the cache holds at the moment it mounts.
 */

import type { QueryClient } from '@tanstack/react-query';

import type { Me } from './types';

export function afterHelperSaved(queryClient: QueryClient, me: Me): void {
  queryClient.setQueryData(['me'], me);
  // Removed, not invalidated. Invalidation keeps the copy loaded before the
  // save, «Моя анкета» took that copy (no services) and a «Сохранить» from it
  // deleted everything just published. Without a copy it waits for the server.
  queryClient.removeQueries({ queryKey: ['my-helper'] });
  void queryClient.invalidateQueries({ queryKey: ['home'] });
}
