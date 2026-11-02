/**
 * What fails in the app, to Sentry, with the stack the source maps decode.
 *
 * Beside lib/clientErrors.ts, not instead of it: that one counts failures on
 * our own server, this one groups them and keeps their stacks. Off without
 * `VITE_SENTRY_DSN` and in development.
 *
 * Every string in an event goes through the same `scrub` the server reports
 * use before it leaves: the page address carries initData in its fragment,
 * and breadcrumbs carry every address the app called. Frame file names are
 * left alone, since they are what a source map is matched by.
 */

import type { Breadcrumb, ErrorEvent } from '@sentry/react';
import { scrub } from './clientErrors.ts';

/** Where a stack frame's file is named; scrubbing it would unmatch the source map. */
const FRAME_KEYS = new Set(['filename', 'abs_path', 'module', 'debug_id']);
/** The event's own ids: a commit, an event or a trace id can hold a run of digits. */
const OWN_KEYS = new Set([
  'event_id',
  'release',
  'dist',
  'trace_id',
  'span_id',
  'parent_span_id',
]);

function scrubbed<T>(value: T, key?: string): T {
  if (typeof value === 'string') {
    if (key && OWN_KEYS.has(key)) return value;
    // A frame in the page itself is named by the page's address, initData and all.
    const clean =
      key && FRAME_KEYS.has(key) ? value.replace(/[?#].*$/, '') : scrub(value, Infinity);
    return clean as T;
  }
  if (Array.isArray(value)) return value.map((item) => scrubbed(item)) as T;
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([name, item]) => [name, scrubbed(item, name)]),
    ) as T;
  }
  return value;
}

export function scrubEvent(event: ErrorEvent): ErrorEvent {
  return scrubbed(event);
}

export function scrubBreadcrumb(crumb: Breadcrumb): Breadcrumb {
  return scrubbed(crumb);
}

export interface ErrorTrackingConfig {
  dsn: string | undefined;
  environment: string | undefined;
  /** The commit, the same name CI uploads the source maps under. */
  release: string | undefined;
}

type Sdk = typeof import('@sentry/react');

/** The SDK once started, or null: off, or not started yet. */
let started: Promise<Sdk | null> = Promise.resolve(null);

/** Start reporting, when this build was given somewhere to report to. */
export function startErrorTracking(config: ErrorTrackingConfig): void {
  if (!config.dsn) return;
  const { dsn } = config;
  started = (async () => {
    // Loaded only when on, so a build without a DSN does not carry the SDK's weight.
    const Sentry = await import('@sentry/react');
    Sentry.init({
      dsn,
      environment: config.environment || 'production',
      release: config.release || undefined,
      // Nothing about the person or the requests: the SDK's defaults collect it all.
      dataCollection: {
        userInfo: false,
        cookies: false,
        httpHeaders: false,
        httpBodies: [],
        urlQueryParams: false,
      },
      beforeSend: scrubEvent,
      beforeBreadcrumb: scrubBreadcrumb,
    });
    return Sentry;
  })().catch(() => null);
}

/**
 * Report what the app caught itself, which Sentry's global handlers never see:
 * a render error React hands to `onCaughtError`, a boot that failed. Waits for
 * the SDK when it is still loading, so a failure at boot is not lost.
 */
export function captureError(error: unknown, componentStack?: string): void {
  void started.then((Sentry) =>
    Sentry?.captureException(
      error,
      componentStack ? { contexts: { react: { componentStack } } } : undefined,
    ),
  );
}
