import { i18n } from '@lingui/core';
import { retrieveRawInitData } from '@tma.js/sdk-react';
import { type PublicChat, sanitize } from './chats';
import { type ClientErrorReport, describeError, reportApiFailure } from './clientErrors';
import type { FeedQuery } from './feedChips';
import type {
  AdminCatalog,
  AdminDecision,
  AdminHide,
  AdminPlacement,
  AdminPlacementIn,
  AdminPlacementSwitch,
  AdminProfileDetail,
  AdsInfo,
  FeedFacetsOut,
} from './generated/types.gen';
import { isApproval } from './join';
import { isReach, type Reach } from './reach';
import { SessionEndedError } from './sessionEnded';
import type {
  ContactStart,
  FeedRequest,
  HelperDetail,
  HelperUpsert,
  HelpRequest,
  Home,
  Institution,
  LanguageOption,
  Me,
  MeUpdate,
  MyHelper,
  MyOffer,
  ParseResult,
  Placement,
  RequestCreate,
  RequestResponse,
  ResponseCreate,
  SearchParams,
  SearchResult,
  ServiceType,
  Subject,
} from './types';

/**
 * Base URL for the API.
 *
 * Empty by default, which makes every call same-origin and lets the Vite dev
 * proxy (and, in production, the image's Caddy, docker/Caddyfile) route it. Since 20 July 2026 Telegram only allows Mini App API calls from the app's
 * own origin, so a cross-origin base is the exception, not the rule.
 */
const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');

const API_PREFIX = '/api/v1';

/** Where a call to the catalog goes, and whether it carries initData. */
export type CatalogRoute = (
  path: string,
  search: string,
  lang?: string,
) => { url: string; initData: boolean };

/** Inside Telegram: the catalog itself, with initData. */
let catalogRoute: CatalogRoute = (path, search) => ({
  url: `${API_PREFIX}${path}${search}`,
  initData: true,
});

/**
 * Another way to the catalog: the console in a browser has no initData and
 * asks webapi instead (console/catalogDoor.ts). Called once, before it renders.
 */
export function routeCatalogCalls(route: CatalogRoute): void {
  catalogRoute = route;
}

/** Thrown for any non-2xx response. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? `API request failed with status ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

/**
 * The caller is not (or no longer) an authenticated Telegram user.
 *
 * initData carries a signature that Telegram time-limits, so a long-lived
 * session will eventually start failing. The only cure is a reload of the Mini
 * App, which is a decision for the UI, not for this module.
 */
export class UnauthorizedError extends ApiError {
  constructor(detail: unknown) {
    super(401, detail, 'Telegram init data was rejected');
    this.name = 'UnauthorizedError';
  }
}

/** Listeners notified once per 401, so the shell can prompt for a reload. */
const unauthorizedListeners = new Set<(error: UnauthorizedError) => void>();

export function onUnauthorized(
  listener: (error: UnauthorizedError) => void,
): VoidFunction {
  unauthorizedListeners.add(listener);
  return () => unauthorizedListeners.delete(listener);
}

/**
 * The raw initData, or nothing outside Telegram and without the dev mock. The
 * one place that decides what "no initData" means.
 */
export function rawInitData(): string | undefined {
  try {
    return retrieveRawInitData() || undefined;
  } catch {
    return undefined;
  }
}

/**
 * The `tma` scheme is the convention the Telegram SDKs and the API agree on.
 * initData must never travel as a query parameter — it would end up in proxy
 * and access logs.
 */
function authHeader(): Record<string, string> {
  // With none, the request goes out unauthenticated and the 401 says so.
  const raw = rawInitData();
  return raw ? { Authorization: `tma ${raw}` } : {};
}

type QueryValue = string | number | boolean | null | undefined | (string | number)[];

function toQuery(params: Record<string, QueryValue> | undefined): string {
  if (!params) return '';
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) {
      // FastAPI reads repeated keys as a list; a comma-joined string is a
      // single value and would silently become one bogus language code.
      for (const item of value) search.append(key, String(item));
    } else {
      search.append(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : '';
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  query?: Record<string, QueryValue>;
  body?: unknown;
  signal?: AbortSignal;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', query, body, signal } = options;

  const call = catalogRoute(path, toQuery(query), i18n.locale);
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(call.initData ? authHeader() : {}),
  };
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  const response = await reported(call.url, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
    // The console's session cookie, which webapi asks the catalog under.
    credentials: call.initData ? undefined : 'same-origin',
  });

  if (response.status === 204) return undefined as T;

  const payload = await readBody(response);

  if (!response.ok) {
    // Through webapi a 401 is the browser's session gone, which the console
    // answers by signing in again (browser.ts, `endsSession`).
    if (response.status === 401 && !call.initData) throw new SessionEndedError();
    if (response.status === 401) {
      const error = new UnauthorizedError(payload);
      for (const listener of unauthorizedListeners) listener(error);
      throw error;
    }
    throw new ApiError(response.status, payload, detailOf(payload));
  }

  return payload as T;
}

/**
 * `fetch` on this origin, with every failure told to `clientErrors`: the
 * endpoint's pattern and the status, 0 when nothing came back. Never the body,
 * which can be anybody's profile.
 */
async function reported(url: string, init: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${url}`, init);
  } catch (error) {
    if (!describeError(error).ignore) reportApiFailure(url, 0);
    throw error;
  }
  if (!response.ok) reportApiFailure(url, response.status);
  return response;
}

async function readBody(response: Response): Promise<unknown> {
  const type = response.headers.get('content-type') ?? '';
  if (!type.includes('application/json')) {
    const text = await response.text();
    return text || null;
  }
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function detailOf(payload: unknown): string | undefined {
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const { detail } = payload as { detail: unknown };
    if (typeof detail === 'string') return detail;
  }
  return undefined;
}

/**
 * supervisor-telegram's public API, served on this origin by the router.
 *
 * Anonymous reads need no initData and get none. The join check is the one
 * call that carries it, in the body as supervisor's contract says, never in
 * the address. See catalog/docs/architecture.md, «One origin, two APIs».
 */
async function publicRequest<T>(
  path: string,
  init: Pick<RequestInit, 'method' | 'body' | 'signal'> = {},
): Promise<T> {
  const response = await reported(`/api/public${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
    },
  });
  const payload = await readBody(response);
  if (!response.ok) throw new ApiError(response.status, payload, detailOf(payload));
  return payload as T;
}

/** A path the server gave for a picture, as the browser must ask for it. */
export function assetUrl(path: string): string {
  return `${BASE_URL}${path}`;
}

// ── endpoints ───────────────────────────────────────────────────────────
//
// Written by hand, and not by the generator: `openapi-ts.config.ts` declares
// only the typescript plugin, so `lib/generated` holds types and no request
// functions at all. Keep these in step with the catalog API,
// catalog/src/students_cz/api/v1/.

export const api = {
  /** The chat directory, supervisor's. Five fields per chat, in its order. */
  getChats: async (signal?: AbortSignal): Promise<PublicChat[]> => {
    const payload = await publicRequest<unknown>('/catalog', { signal });
    // Not a list at all is a failure, not an empty directory: it shows the
    // error row, which offers a retry, instead of «Чатов пока нет».
    if (!Array.isArray(payload))
      throw new ApiError(502, payload, 'chat directory is not a list');
    return sanitize(payload);
  },

  /** How far a post in the chats reaches: supervisor's, summed per group. */
  getReach: async (signal?: AbortSignal): Promise<Reach> => {
    const payload = await publicRequest<unknown>('/reach', { signal });
    if (!isReach(payload)) throw new ApiError(502, payload, 'reach has the wrong shape');
    return payload;
  },

  /** Approve the caller's own join request to a moderated chat. */
  passJoinCheck: async (initData: string, queryId: string): Promise<void> => {
    const answer = await publicRequest<unknown>('/join-check', {
      method: 'POST',
      body: JSON.stringify({ init_data: initData, query_id: queryId }),
    });
    // Only this counts as passing: a misrouted 200 must not say «Готово».
    if (!isApproval(answer))
      throw new ApiError(502, answer, 'join check gave no approval');
  },

  /**
   * Tell supervisor this person opened the Mini App, for the console's
   * audience. Once per launch; nothing waits on it and nothing is shown if it
   * fails.
   */
  reportLaunch: async (initData: string): Promise<void> => {
    await publicRequest<unknown>('/seen', {
      method: 'POST',
      body: JSON.stringify({ init_data: initData }),
    });
  },

  /**
   * What failed in this app, for the log (lib/clientErrors.ts). Plain `fetch`
   * rather than `publicRequest`, so that a report that fails is not itself
   * reported; `keepalive` so that one sent as the app goes away arrives.
   */
  reportClientErrors: (report: ClientErrorReport, keepalive: boolean): void => {
    void fetch(`${BASE_URL}/api/public/client-errors`, {
      method: 'POST',
      keepalive,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(report),
    }).catch(() => undefined);
  },

  /** Who a business writes to about advertising, if anyone. */
  getAds: (signal?: AbortSignal) => request<AdsInfo>('/ads', { signal }),

  /** The whole home screen in one response. */
  getHome: (signal?: AbortSignal) => request<Home>('/home', { signal }),

  getServiceTypes: (signal?: AbortSignal) =>
    request<ServiceType[]>('/taxonomy/service-types', { signal }),

  /** One level of the subject tree. Pass no parent for the roots. */
  getSubjects: (
    params: { parent_id?: number; limit?: number } = {},
    signal?: AbortSignal,
  ) => request<Subject[]>('/taxonomy/subjects', { query: { ...params }, signal }),

  /** Fuzzy search over the subject tree — "matan" and "матан" both work. */
  searchSubjects: (q: string, limit?: number, signal?: AbortSignal) =>
    request<Subject[]>('/taxonomy/subjects', { query: { q, limit }, signal }),

  getInstitutions: (signal?: AbortSignal) =>
    request<Institution[]>('/taxonomy/institutions', { signal }),

  getLanguages: (signal?: AbortSignal) =>
    request<LanguageOption[]>('/taxonomy/languages', { signal }),

  /** Read a sentence and show back what we made of it. */
  parseQuery: (text: string, signal?: AbortSignal) =>
    request<ParseResult>('/search/parse', { method: 'POST', body: { text }, signal }),

  search: (params: SearchParams = {}, signal?: AbortSignal) =>
    request<SearchResult>('/search', { query: { ...params }, signal }),

  getHelper: (userId: number, signal?: AbortSignal) =>
    request<HelperDetail>(`/helpers/${userId}`, { signal }),

  /** Record that a conversation is starting, and get where to continue it. */
  startContact: (userId: number) =>
    request<ContactStart>(`/helpers/${userId}/contact`, { method: 'POST' }),

  getPlacements: (
    params: {
      slot: string;
      service_type?: string;
      subject_id?: number;
      preview?: boolean;
    },
    signal?: AbortSignal,
  ) => request<Placement[]>('/placements', { query: { ...params }, signal }),

  registerPlacementClick: (placementId: number) =>
    request<void>(`/placements/${placementId}/click`, { method: 'POST' }),

  getMe: (signal?: AbortSignal) => request<Me>('/me', { signal }),

  patchMe: (payload: MeUpdate, signal?: AbortSignal) =>
    request<Me>('/me', { method: 'PATCH', body: payload, signal }),

  /** Alias with the name the mutation hooks read better with. */
  updateMe: (payload: MeUpdate) => request<Me>('/me', { method: 'PATCH', body: payload }),

  // ── requests ──────────────────────────────────────────────────────────

  getRequests: (signal?: AbortSignal) => request<HelpRequest[]>('/requests', { signal }),

  createRequest: (payload: RequestCreate) =>
    request<HelpRequest>('/requests', { method: 'POST', body: payload }),

  closeRequest: (requestId: number) =>
    request<HelpRequest>(`/requests/${requestId}/close`, { method: 'POST' }),

  /** Gone for good, with its responses. The author only; 404 for anyone else. */
  deleteRequest: (requestId: number) =>
    request<void>(`/requests/${requestId}`, { method: 'DELETE' }),

  /** Open requests worth answering. Helpers only; 403 for everyone else. */
  getRequestFeed: (query: FeedQuery, signal?: AbortSignal) =>
    // The most the server gives: the section headings count what is loaded.
    request<FeedRequest[]>('/requests/feed', { query: { ...query, limit: 50 }, signal }),

  /** The numbers on the feed's chips, over the whole feed. Helpers only. */
  getFeedFacets: (withResponded: boolean, signal?: AbortSignal) =>
    request<FeedFacetsOut>('/requests/feed/facets', {
      query: { with_responded: withResponded },
      signal,
    }),

  respondToRequest: (requestId: number, payload: ResponseCreate) =>
    request<RequestResponse>(`/requests/${requestId}/respond`, {
      method: 'POST',
      body: payload,
    }),

  /** Who answered. The author of the request only. */
  getResponses: (requestId: number, signal?: AbortSignal) =>
    request<RequestResponse[]>(`/requests/${requestId}/responses`, { signal }),

  acceptResponse: (responseId: number) =>
    request<RequestResponse>(`/responses/${responseId}/accept`, { method: 'POST' }),

  declineResponse: (responseId: number) =>
    request<RequestResponse>(`/responses/${responseId}/decline`, { method: 'POST' }),

  // ── becoming a helper ─────────────────────────────────────────────────

  /** The caller's own profile, whatever state it is in. Never 404s. */
  getMyHelper: (signal?: AbortSignal) => request<MyHelper>('/helper', { signal }),

  saveHelper: (payload: HelperUpsert) =>
    request<Me>('/helper', { method: 'PUT', body: payload }),

  /** One service out of the catalog, or back in, without touching the rest. */
  pauseOffer: (offerId: number, paused: boolean) =>
    request<MyOffer>(`/helper/offers/${offerId}`, { method: 'PATCH', body: { paused } }),

  // ── the console ───────────────────────────────────────────────────────

  /** New profiles, unanswered requests, empty searches. Operators only. */
  getAdminCatalog: (signal?: AbortSignal) =>
    request<AdminCatalog>('/admin/catalog', { signal }),

  /** One profile as the operator moderates it. Operators only. */
  getAdminProfile: (userId: number, signal?: AbortSignal) =>
    request<AdminProfileDetail>(`/admin/profiles/${userId}`, { signal }),

  /** Looked at and left listed: off «Новые анкеты». Operators only. */
  keepProfile: (userId: number, decision: AdminDecision) =>
    request<AdminProfileDetail>(`/admin/profiles/${userId}/review`, {
      method: 'POST',
      body: decision,
    }),

  /** Out of the catalog; its owner cannot list it again. Operators only. */
  hideProfile: (userId: number, why: AdminHide) =>
    request<AdminProfileDetail>(`/admin/profiles/${userId}/hide`, {
      method: 'POST',
      body: why,
    }),

  /** A hidden profile listed again. Operators only. */
  restoreProfile: (userId: number, decision: AdminDecision) =>
    request<AdminProfileDetail>(`/admin/profiles/${userId}/restore`, {
      method: 'POST',
      body: decision,
    }),

  /** Placements with the last month's impressions and clicks. Operators only. */
  getAdminPartners: (signal?: AbortSignal) =>
    request<AdminPlacement[]>('/admin/partners', { signal }),

  /** A new card on the Life screen, first in its slot. Operators only. */
  createPlacement: (card: AdminPlacementIn) =>
    request<AdminPlacement>('/admin/placements', { method: 'POST', body: card }),

  /** On or off; nothing is deleted. Operators only. */
  switchPlacement: (placementId: number, isActive: boolean) =>
    request<AdminPlacement>(`/admin/placements/${placementId}`, {
      method: 'PATCH',
      body: { is_active: isActive } satisfies AdminPlacementSwitch,
    }),
};

export type Api = typeof api;

/** Universities with their faculties; they change a few times a year. */
export const institutionsQuery = {
  queryKey: ['institutions'] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.getInstitutions(signal),
  staleTime: 60 * 60 * 1000,
};

/**
 * The chat directory's query, shared by the directory and a section's screen
 * so that opening a section costs no request. The directory changes when a
 * moderator publishes a chat, not while somebody is looking at it.
 */

export const chatsQuery = {
  queryKey: ['chats'] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.getChats(signal),
  staleTime: 5 * 60_000,
};

/** Reach, shared by the ads pages. Supervisor recounts it hourly. */
export const reachQuery = {
  queryKey: ['reach'] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.getReach(signal),
  staleTime: 60 * 60_000,
};

/**
 * The account, shared by the shell, the header and every screen that reads it.
 * One object so every observer agrees on how fresh it has to be.
 */
export const meQuery = {
  queryKey: ['me'] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.getMe(signal),
  staleTime: 5 * 60 * 1000,
};
