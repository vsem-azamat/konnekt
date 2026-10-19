/**
 * The join check's states, apart from the screen that draws them.
 *
 * A person arrives from a join request to a moderated chat with a query id in
 * the address. Supervisor approves the request when it gets that id together
 * with the signed initData of the person it was issued to. See
 * catalog/docs/architecture.md, «The join check answers one question».
 */

export type JoinState =
  /** Opened without initData or a query id: nothing here can work. */
  | { phase: 'unavailable' }
  /** `retried`: the last attempt did not get through, and the screen says so. */
  | { phase: 'ready'; initData: string; queryId: string; retried: boolean }
  | { phase: 'sending'; initData: string; queryId: string; retried: boolean }
  | { phase: 'passed' }
  /**
   * Supervisor refused. `afterRetry`: an earlier attempt may have gone
   * through, since supervisor spends the check before it asks Telegram.
   */
  | { phase: 'failed'; afterRetry: boolean };

export type JoinEvent =
  | { type: 'press' }
  | { type: 'approved' }
  | { type: 'refused' }
  /** Anything that is not supervisor's refusal: the network, the proxy, a 5xx. */
  | { type: 'unreachable' };

/** How a check can already have ended in this session. */
export type Settled = 'passed' | 'failed' | 'failed-after-retry';

export function joinStart(
  initData: string | undefined,
  queryId: string | null | undefined,
  settled?: Settled | null,
): JoinState {
  // A settled check stays settled, whatever route led back here: offering
  // the button again for a spent check can only end in a false refusal.
  if (settled === 'passed') return { phase: 'passed' };
  if (settled === 'failed') return { phase: 'failed', afterRetry: false };
  if (settled === 'failed-after-retry') return { phase: 'failed', afterRetry: true };
  if (!initData || !queryId) return { phase: 'unavailable' };
  return { phase: 'ready', initData, queryId, retried: false };
}

/**
 * The next state, or the same object when the event does not apply.
 *
 * The same object, not a copy: the screen sends the request only when a press
 * moved the state to `sending`, so a second press while one is in flight, or
 * after it settled, cannot send a second one.
 */
export function joinStep(state: JoinState, event: JoinEvent): JoinState {
  if (event.type === 'press') {
    return state.phase === 'ready' ? { ...state, phase: 'sending' } : state;
  }
  if (state.phase !== 'sending') return state;
  if (event.type === 'approved') return { phase: 'passed' };
  if (event.type === 'refused') return { phase: 'failed', afterRetry: state.retried };
  return { ...state, phase: 'ready', retried: true };
}

/** Whether a stored value is one of the outcomes, the only ones read back. */
export function isSettled(value: unknown): value is Settled {
  return value === 'passed' || value === 'failed' || value === 'failed-after-retry';
}

/**
 * What to store when a check settles, given what is stored already.
 *
 * «passed» is never replaced: a second attempt after leaving mid-request gets
 * supervisor's 403 because the first went through, and that refusal must not
 * tell somebody who is in the chat to apply again.
 */
export function keepSettled(stored: Settled | null, outcome: Settled): Settled {
  return stored === 'passed' ? 'passed' : outcome;
}

/** What to keep of a state, or nothing while it is not settled. */
export function settledOf(state: JoinState): Settled | null {
  if (state.phase === 'passed') return 'passed';
  if (state.phase === 'failed') return state.afterRetry ? 'failed-after-retry' : 'failed';
  return null;
}

/** What a failed request means. Only supervisor's 403 and 409 are refusals. */
export function joinEventFor(error: unknown): JoinEvent {
  const status = (error as { status?: unknown } | null)?.status;
  return status === 403 || status === 409 ? { type: 'refused' } : { type: 'unreachable' };
}

/** Whether supervisor's answer is an approval: `{status: "approved"}` and nothing else. */
export function isApproval(answer: unknown): boolean {
  return (
    answer !== null &&
    typeof answer === 'object' &&
    (answer as { status?: unknown }).status === 'approved'
  );
}
