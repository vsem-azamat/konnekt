/**
 * Hand-written mirrors of the API's Pydantic schemas.
 *
 * These are a stopgap. `pnpm api:generate` generates types from the API's OpenAPI
 * document into `lib/generated`, and this file shrinks as they move across —
 * see the note on `ServiceType` below for how that happens.
 *
 * Two conventions carried over from the API and worth remembering:
 *
 * - **Data is localised server-side, chrome is not.** Subject, faculty and
 *   service-type names arrive already in the caller's language. Sentences the
 *   interface composes arrive as a {@link Phrase} — a code plus params — and
 *   this app renders them, because plural agreement in Czech, Russian and
 *   Ukrainian belongs in the presentation layer.
 * - **Screens are assembled server-side.** `/home` returns the whole home
 *   screen in one response rather than making a phone on mobile data issue six
 *   requests.
 */

import type { Avatar, HideReason, HomeSection } from './generated/types.gen';

export type UiLang = 'ru' | 'cs' | 'en' | 'uk';

export type WorkFormat = 'online' | 'offline' | 'both';

export type PriceUnit =
  | 'hour'
  | 'lesson'
  | 'work'
  | 'day'
  | 'week'
  | 'month'
  | 'semester'
  | 'item'
  | 'negotiable';

/** A sentence for the client to render, not a sentence. */
export interface Phrase {
  code: string;
  params: Record<string, string | number>;
}

export interface Price {
  amount: number | null;
  currency: string;
  unit: PriceUnit;
}

/**
 * Enough to draw the little circle without fetching anything. Telegram avatar
 * URLs expire, so the monogram is the fallback rather than a broken image, and
 * `tone` is 0-5, derived from the user id so a person keeps their colour.
 *
 * From the contract rather than written out again: `HomeSection` carries these
 * too, and two structurally equal declarations of the same thing are one
 * rename away from not being equal.
 */
export type { Avatar };

// ── taxonomy ────────────────────────────────────────────────────────────

/**
 * Taken from the contract, not written out again.
 *
 * `pnpm api:generate` regenerates `lib/generated` from the API's OpenAPI
 * document, and these two carry `group`, which is an enum on the server. Going
 * through the generated type is what makes a mistyped group a compile error
 * here instead of an empty heading at runtime; a hand-written `string` would
 * accept anything. The rest of this file is still the hand-written stopgap
 * described above — types move across as the code that uses them is touched.
 */
export type {
  HideReason,
  ServiceGroup,
  ServiceTypeOut as ServiceType,
} from './generated/types.gen';

export interface Subject {
  id: number;
  slug: string;
  name: string;
  parent_id: number | null;
  has_children: boolean;
  external_code: string | null;
  offers_count: number;
}

export interface Institution {
  id: number;
  code: string;
  name: string;
  short_name: string | null;
  city: string | null;
  parent_id: number | null;
  faculties: Institution[];
}

export interface LanguageOption {
  code: string;
  name: string;
}

// ── catalog ─────────────────────────────────────────────────────────────

export interface Offer {
  id: number;
  service_type: string;
  service_type_name: string;
  subject: string | null;
  institution: string | null;
  price: Price;
  langs: string[];
  work_format: WorkFormat;
  /** Already translated — these are names we author. */
  options: string[];
  /** The helper's own words, in whatever language they wrote them. */
  note: string | null;
  /** Only a written work has one. `null` reads as "the two of them agree". */
  turnaround_days: number | null;
}

/** One row in the results list. */
export interface HelperCard {
  user_id: number;
  name: string;
  avatar: Avatar;
  affiliation: string | null;
  price: Price | null;
  /** Why this person is in the list. Sometimes it says the match is weak. */
  reason: Phrase | null;
  availability: Phrase | null;
  rating: number | null;
  deals_count: number;
  langs: string[];
}

export interface Stat {
  code: string;
  value: string;
}

export interface Review {
  author: string;
  /** ISO date, `YYYY-MM-DD`. */
  created_on: string;
  text: string;
}

export interface HelperDetail {
  user_id: number;
  name: string;
  avatar: Avatar;
  affiliation: string | null;
  about: string | null;
  headline: string | null;
  stats: Stat[];
  offers: Offer[];
  langs: string[];
  work_format: WorkFormat;
  place_note: string | null;
  /** ISO datetimes. */
  free_slots: string[];
  reviews: Review[];
  /** Facts for composing the prefilled first message. The wording is ours. */
  intro_context: Record<string, string | number>;
  telegram_url: string | null;
}

// ── search ──────────────────────────────────────────────────────────────

export type ChipKind =
  | 'subject'
  | 'institution'
  | 'service_type'
  | 'deadline'
  | 'budget'
  | 'lang';

/** One piece of what the parser understood, shown back for correction. */
export interface Chip {
  kind: ChipKind | string;
  label: string;
  value: string | number | null;
  confidence: number;
}

export interface ClarifyOption {
  code: string;
  tone: number;
}

/** One question, asked only when the answer changes the result set. */
export interface Clarify {
  code: string;
  options: ClarifyOption[];
}

export interface ParseResult {
  chips: Chip[];
  clarify: Clarify | null;
  matches: number;
  /** Set when nothing was recognised, so the screen can say so plainly. */
  note: Phrase | null;
  /**
   * A subject the parser guessed at and would not search by.
   *
   * Never a filter — narrowing by a subject nobody named shows nobody. The
   * results screen asks for it separately and shows it under its own heading.
   */
  also: { subject_id: number; label: string } | null;
}

export interface SearchFilters {
  subject_id: number | null;
  institution_id: number | null;
  service_type_id: number | null;
  max_price: number | null;
  langs: string[];
  work_format: WorkFormat | null;
}

export interface SearchResult {
  total: number;
  filters: SearchFilters;
  chips: Chip[];
  results: HelperCard[];
}

export type SearchSort = 'relevance' | 'price' | 'available';

export interface SearchParams {
  subject_id?: number;
  institution_id?: number;
  service_type_id?: number;
  max_price?: number;
  langs?: string[];
  sort?: SearchSort;
  limit?: number;
  offset?: number;
}

// ── home ────────────────────────────────────────────────────────────────

/** From the contract, for `group`. See the note above `ServiceType`. */
export type { HomeSection };

export interface Home {
  people: HomeSection[];
  things: HomeSection[];
}

// ── partners ────────────────────────────────────────────────────────────

export interface Placement {
  id: number;
  title: string;
  subtitle: string | null;
  price_text: string | null;
  context_note: string | null;
  logo_text: string | null;
  logo_bg: string | null;
  url: string;
}

// ── user ────────────────────────────────────────────────────────────────

export interface Me {
  id: number;
  tg_id: number;
  name: string;
  username: string | null;
  avatar: Avatar;
  ui_lang: UiLang;
  spoken_langs: string[];
  city: string | null;
  institution: Institution | null;
  is_helper: boolean;
  helper_status: string | null;
  /** One of the console's operators. */
  is_admin: boolean;
}

export interface MeUpdate {
  ui_lang?: UiLang;
  spoken_langs?: string[];
  city?: string | null;
  institution_id?: number | null;
}

// ── requests: the catalog read backwards ────────────────────────────────

export type RequestStatus = 'draft' | 'open' | 'closed' | 'expired';

export interface HelpRequest {
  id: number;
  text: string;
  subject: string | null;
  institution: string | null;
  service_type: string | null;
  deadline_on: string | null;
  status: RequestStatus;
  responses_count: number;
  responders: Avatar[];
  created_at: string;
}

/**
 * What posting a request sends.
 *
 * From the generated module rather than hand-written, which is the rule this
 * file states above: a screen that touches a wire type takes it from the
 * contract. It matters more here than usual — `null` is an answer and not an
 * omission, the axes being read out of the text only where the caller said
 * nothing, and a second copy of that is a second thing to get wrong. See
 * `services/requests.create`.
 */
export type { RequestCreate } from './generated/types.gen';

/**
 * A request as a helper sees it: who is asking, and why it surfaced. No
 * `responders` — who else is pitching for the same work is not shown.
 */
export interface FeedRequest extends Omit<HelpRequest, 'responders'> {
  author: Avatar;
  author_name: string;
  budget: Price | null;
  langs: string[];
  reason: Phrase | null;
  /** Already answered by this helper; absent from servers that drop those. */
  responded?: boolean;
}

export type ResponseStatus = 'sent' | 'read' | 'accepted' | 'declined';

/** One helper's answer to a request. */
export interface RequestResponse {
  id: number;
  request_id: number;
  helper_id: number;
  name: string;
  avatar: Avatar;
  username: string | null;
  affiliation: string | null;
  rating: number | null;
  deals_count: number;
  message: string;
  price: Price | null;
  status: ResponseStatus;
  created_at: string;
}

export interface ResponseCreate {
  message: string;
  price_amount?: number;
  price_unit?: PriceUnit;
}

// ── becoming a helper ───────────────────────────────────────────────────

export interface OfferInput {
  service_type_id: number;
  option_ids?: number[];
  note?: string | null;
  turnaround_days?: number | null;
  subject_id?: number | null;
  institution_id?: number | null;
  price_amount?: number | null;
  price_unit?: PriceUnit;
  langs?: string[];
}

export interface HelperUpsert {
  headline?: string | null;
  about?: string | null;
  raw_intro?: string | null;
  work_format?: WorkFormat;
  city?: string | null;
  place_note?: string | null;
  offers?: OfferInput[];
  publish?: boolean;
  /** Whether the bot writes about new requests the profile could answer. */
  new_request_alerts?: boolean;
}

/**
 * One of the caller's own offers, as the cabinet edits it.
 *
 * Ids and names side by side: the ids are what goes back in `OfferInput`, the
 * names are what the person reads. `Offer` carries only names, which is right
 * for a card and useless for a form.
 */
export interface MyOffer {
  service_type_id: number;
  option_ids: number[];
  note: string | null;
  turnaround_days: number | null;
  service_type: string;
  service_type_name: string;
  subject_id: number | null;
  subject_name: string | null;
  institution_id: number | null;
  institution_name: string | null;
  price_amount: number | null;
  price_unit: PriceUnit;
  langs: string[];
}

/** The caller's own profile, drafts and hidden ones included. */
export interface MyHelper {
  exists: boolean;
  status: string | null;
  headline: string | null;
  about: string | null;
  work_format: WorkFormat;
  city: string | null;
  place_note: string | null;
  offers: MyOffer[];
  /** Listed, or hidden by an operator, and not looked at since it changed. */
  under_review?: boolean;
  /** Only while an operator keeps it hidden. */
  hidden_reason?: HideReason | null;
  hidden_note?: string | null;
  /** The bot writes about new requests the profile could answer. */
  new_request_alerts?: boolean;
}

export interface ContactStart {
  telegram_url: string;
}
