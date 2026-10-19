import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  isApproval,
  isSettled,
  joinEventFor,
  joinStart,
  joinStep,
  keepSettled,
  settledOf,
} from '../src/lib/join.ts';

test('with initData and a query id the check can be taken', () => {
  assert.deepEqual(joinStart('user=...&hash=...', 'q-123'), {
    phase: 'ready',
    initData: 'user=...&hash=...',
    queryId: 'q-123',
    retried: false,
  });
});

test('without initData there is nothing to sign with', () => {
  assert.deepEqual(joinStart(undefined, 'q-123'), { phase: 'unavailable' });
});

test('without a query id there is no request to approve', () => {
  assert.deepEqual(joinStart('user=...&hash=...', null), { phase: 'unavailable' });
  assert.deepEqual(joinStart('user=...&hash=...', ''), { phase: 'unavailable' });
});

test('a press moves to sending, and a second press is not a second request', () => {
  const ready = joinStart('x', 'q');
  const sending = joinStep(ready, { type: 'press' });
  assert.equal(sending.phase, 'sending');
  // The screen sends only when the step changed the state; the same object
  // back means "do nothing".
  assert.equal(joinStep(sending, { type: 'press' }), sending);
});

test('approval passes and a refusal fails, and neither can be pressed again', () => {
  const sending = joinStep(joinStart('x', 'q'), { type: 'press' });
  const passed = joinStep(sending, { type: 'approved' });
  const failed = joinStep(sending, { type: 'refused' });
  assert.equal(passed.phase, 'passed');
  assert.equal(failed.phase, 'failed');
  assert.equal(joinStep(passed, { type: 'press' }), passed);
  assert.equal(joinStep(failed, { type: 'press' }), failed);
});

test('a failure that is not a refusal keeps the button, marked as a retry', () => {
  const sending = joinStep(joinStart('x', 'q'), { type: 'press' });
  const again = joinStep(sending, { type: 'unreachable' });
  assert.deepEqual(again, { phase: 'ready', initData: 'x', queryId: 'q', retried: true });
  assert.equal(joinStep(again, { type: 'press' }).phase, 'sending');
});

test('an answer that arrives without a press is ignored', () => {
  const ready = joinStart('x', 'q');
  assert.equal(joinStep(ready, { type: 'approved' }), ready);
  assert.equal(joinStep(ready, { type: 'unreachable' }), ready);
});

test('a check settled earlier in this session opens settled', () => {
  assert.deepEqual(joinStart('x', 'q', 'passed'), { phase: 'passed' });
  assert.deepEqual(joinStart('x', 'q', 'failed'), { phase: 'failed', afterRetry: false });
  assert.deepEqual(joinStart('x', 'q', 'failed-after-retry'), {
    phase: 'failed',
    afterRetry: true,
  });
});

test('only a 403 is a refusal; everything else may be tried again', () => {
  const status = (code: number) => Object.assign(new Error('x'), { status: code });
  assert.deepEqual(joinEventFor(status(403)), { type: 'refused' });
  // Telegram refused the answer itself: the request is closed, retrying cannot help.
  assert.deepEqual(joinEventFor(status(409)), { type: 'refused' });
  // Telegram never heard: the check was released, so a retry can pass.
  assert.deepEqual(joinEventFor(status(503)), { type: 'unreachable' });
  assert.deepEqual(joinEventFor(status(502)), { type: 'unreachable' });
  assert.deepEqual(joinEventFor(status(422)), { type: 'unreachable' });
  assert.deepEqual(joinEventFor(new TypeError('network')), { type: 'unreachable' });
});

test('a refusal after a retry may mean the first try went through', () => {
  const sending = joinStep(joinStart('x', 'q'), { type: 'press' });
  const again = joinStep(joinStep(sending, { type: 'unreachable' }), { type: 'press' });
  assert.deepEqual(joinStep(again, { type: 'refused' }), {
    phase: 'failed',
    afterRetry: true,
  });
  assert.deepEqual(joinStep(sending, { type: 'refused' }), {
    phase: 'failed',
    afterRetry: false,
  });
});

test('only status "approved" counts as passing', () => {
  assert.equal(isApproval({ status: 'approved' }), true);
  assert.equal(isApproval({ status: 'queued' }), false);
  assert.equal(isApproval('<html>ok</html>'), false);
  assert.equal(isApproval(null), false);
});

test('what is kept of a settled check says which way it ended', async () => {
  assert.equal(settledOf({ phase: 'passed' }), 'passed');
  assert.equal(settledOf({ phase: 'failed', afterRetry: false }), 'failed');
  assert.equal(settledOf({ phase: 'failed', afterRetry: true }), 'failed-after-retry');
  assert.equal(settledOf({ phase: 'unavailable' }), null);
});

test('only the three outcomes are read back from storage', () => {
  assert.equal(isSettled('passed'), true);
  assert.equal(isSettled('failed-after-retry'), true);
  assert.equal(isSettled('sending'), false);
  assert.equal(isSettled(null), false);
});

test('a kept «passed» is never overwritten by a later refusal', () => {
  assert.equal(keepSettled('passed', 'failed'), 'passed');
  assert.equal(keepSettled('passed', 'failed-after-retry'), 'passed');
  assert.equal(keepSettled(null, 'failed'), 'failed');
  assert.equal(keepSettled('failed', 'passed'), 'passed');
});
