/**
 * The console's queries. Webapi's go through its session (see session.ts);
 * the catalog's are ordinary `/api/v1` calls that only operators may make.
 */

import { api, rawInitData } from '@/lib/api';

import {
  type AudienceFilters,
  type AudiencePage,
  type AudiencePerson,
  type AudienceSummary,
  audiencePath,
} from './audience';

import {
  type AdminSession,
  type BlockedUser,
  type ChatUpdate,
  type ConsoleChat,
  type ConsoleChatDetail,
  consoleRequester,
  type HomeStats,
  type SpamPing,
  type SystemStatus,
} from './session';

/** The console's requester for webapi's session endpoints. See session.ts. */
export const consoleGet = consoleRequester((...args) => fetch(...args), rawInitData);

// The console reads while somebody looks at it; a minute is fresh enough.
const CONSOLE_STALE = 60_000;

export const adminCatalogQuery = {
  queryKey: ['console', 'catalog'] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.getAdminCatalog(signal),
  staleTime: CONSOLE_STALE,
};

export const adminPartnersQuery = {
  queryKey: ['console', 'partners'] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.getAdminPartners(signal),
  staleTime: CONSOLE_STALE,
};

export const consoleStatsQuery = {
  queryKey: ['console', 'stats'] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) =>
    consoleGet<HomeStats>('/api/stats/home', { signal }),
  staleTime: CONSOLE_STALE,
  // A refusal or a stale sign-in stays so for this launch; coming back to the
  // summary must not send the sign-in again.
  retryOnMount: false,
};

export const consoleChatsQuery = {
  queryKey: ['console', 'chats'] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) =>
    consoleGet<ConsoleChat[]>('/api/chats', { signal }),
  staleTime: CONSOLE_STALE,
  retryOnMount: false,
};

export const chatDetailQuery = (id: number) => ({
  queryKey: ['console', 'chat', id] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) =>
    consoleGet<ConsoleChatDetail>(`/api/chats/${id}`, { signal }),
  staleTime: CONSOLE_STALE,
  retryOnMount: false,
});

// ── changes ──────────────────────────────────────────────────────────────

export const consoleChanges = {
  /** Only the fields sent are applied; the answer is the chat as it now is. */
  updateChat: (id: number, update: ChatUpdate) =>
    consoleGet<ConsoleChat>(`/api/chats/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(update),
    }),

  /** A chat the bot is not in, listed by its public link and marked as not ours. */
  addExternalChat: (publicLink: string) =>
    consoleGet<ConsoleChat>('/api/chats/external', {
      method: 'POST',
      body: JSON.stringify({ public_link: publicLink }),
    }),

  /** Title, photo and member count, read again from Telegram. */
  refreshChat: (id: number) =>
    consoleGet<ConsoleChat>(`/api/chats/${id}/refresh`, { method: 'POST' }),

  /** Banned in every chat the bot moderates, as /banall does; optionally
   *  with every message of theirs the bot recorded. */
  block: (userId: number, revokeMessages: boolean) =>
    consoleGet<{ blocked: boolean }>(`/api/users/${userId}/block`, {
      method: 'POST',
      body: JSON.stringify({ revoke_messages: revokeMessages }),
    }),

  /**
   * Signs this browser out. Past the requester on purpose: it would answer a
   * missing session by opening a new one.
   */
  signOut: async () => {
    const response = await fetch('/api/auth/logout', {
      method: 'POST',
      credentials: 'same-origin',
    });
    if (!response.ok) throw new Error(`sign-out failed: ${response.status}`);
  },

  /** Signs that session out; webapi refuses the one making the request. */
  closeSession: (id: string) =>
    consoleGet<void>(`/api/admin/sessions/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),

  unblock: (userId: number) =>
    consoleGet<{ blocked: boolean }>(`/api/users/${userId}/block`, { method: 'DELETE' }),
};

/** Who the super admins are, among webapi's operational facts. */
export const consoleSystemQuery = {
  queryKey: ['console', 'system'] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) =>
    consoleGet<SystemStatus>('/api/admin/system', { signal }),
  staleTime: 10 * CONSOLE_STALE,
  retryOnMount: false,
};

/** The global blacklist, most recently changed first. */
export const blockedQuery = {
  queryKey: ['console', 'blocked'] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) =>
    consoleGet<BlockedUser[]>('/api/users/blocked', { signal }),
  staleTime: CONSOLE_STALE,
  retryOnMount: false,
};

/** The console's open sessions. */
export const sessionsQuery = {
  queryKey: ['console', 'sessions'] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) =>
    consoleGet<AdminSession[]>('/api/admin/sessions', { signal }),
  staleTime: CONSOLE_STALE,
  retryOnMount: false,
};

/** The ad detector's latest hits across every chat. */
export const spamPingsQuery = {
  queryKey: ['console', 'spam'] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) =>
    consoleGet<SpamPing[]>('/api/spam/pings?limit=100', { signal }),
  staleTime: CONSOLE_STALE,
  retryOnMount: false,
};

/** The top of the Audience screen: how many, who may be written to, where from. */
export const audienceSummaryQuery = {
  queryKey: ['console', 'audience', 'summary'] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) =>
    consoleGet<AudienceSummary>('/api/audience/summary', { signal }),
  staleTime: CONSOLE_STALE,
  retryOnMount: false,
};

/** The audience list, a page at a time, newest activity first. */
export const audiencePeopleQuery = (filters: AudienceFilters) => ({
  queryKey: ['console', 'audience', 'people', filters] as const,
  queryFn: ({ signal, pageParam }: { signal: AbortSignal; pageParam: number }) =>
    consoleGet<AudiencePage>(audiencePath(filters, pageParam), { signal }),
  initialPageParam: 0,
  getNextPageParam: (last: AudiencePage, pages: AudiencePage[]) => {
    const seen = pages.reduce((sum, page) => sum + page.items.length, 0);
    return seen < last.total ? seen : undefined;
  },
  staleTime: CONSOLE_STALE,
  retryOnMount: false,
});

export const audiencePersonQuery = (id: number) => ({
  queryKey: ['console', 'audience', 'person', id] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) =>
    consoleGet<AudiencePerson>(`/api/audience/${id}`, { signal }),
  staleTime: CONSOLE_STALE,
  retryOnMount: false,
});
