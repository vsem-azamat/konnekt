import { useEffect } from 'react';

import { reportClientEvent } from '@/lib/clientErrors';

/**
 * Report a screen that loaded and came back with nothing where there should
 * be something: a directory with no chats, a section nobody can find. Data
 * that went missing shows up nowhere else, because nothing failed.
 */
export function useReportEmpty(empty: boolean, what: string): void {
  useEffect(() => {
    if (empty) reportClientEvent({ kind: 'empty', message: what });
  }, [empty, what]);
}
