import type { ComponentType } from 'react';

import { describeError, reportClientEvent } from './clientErrors.ts';

/**
 * A screen fetched the first time it is opened. The screen before stays on
 * show until it arrives; one that fails to arrive is the `errorElement`'s.
 *
 * The failure is reported here because nothing else would: React Router hands
 * it to the `errorElement` as state, never throwing, so React's
 * `onCaughtError` does not hear of it. The likeliest cause is a deploy that
 * replaced the chunk under an open app.
 */
export function lazyScreen(load: () => Promise<{ default: ComponentType }>) {
  return async () => {
    try {
      return { Component: (await load()).default };
    } catch (error) {
      const { message, stack, ignore } = describeError(error);
      if (!ignore) reportClientEvent({ kind: 'error', message, stack });
      throw error;
    }
  };
}
