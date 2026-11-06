/**
 * The tutors on the site: the helpers who turned «Страница на konnekt.cz» on in
 * the app, as the catalog lists them (/api/v1/public/helpers, whose rules are
 * catalog/src/students_cz/services/site.py). Checked here as they arrive, like
 * the universities: the page prints only fields it knows, in the shape it
 * expects, and drops a row it cannot address.
 */

import { num } from '../landing/copy.ts';
import { type Lang, localePath } from '../paths.ts';

export type WorkFormat = 'online' | 'offline' | 'both';
export type PriceUnit =
  | 'hour'
  | 'lesson'
  | 'work'
  | 'day'
  | 'week'
  | 'month'
  | 'semester'
  | 'item';

export interface Price {
  amount: number;
  currency: string;
  unit: PriceUnit;
}

export interface TutorCard {
  user_id: number;
  slug: string;
  name: string;
  initials: string;
  tone: number;
  headline: string | null;
  services: string[];
  subjects: string[];
  price_from: Price | null;
  langs: string[];
  work_format: WorkFormat;
  city: string | null;
  rating: number | null;
  deals_count: number;
}

export interface TutorOffer {
  service: string;
  subject: string | null;
  institution: string | null;
  price: Price | null;
  langs: string[];
  work_format: WorkFormat;
  options: string[];
  note: string | null;
}

export interface TutorPage extends TutorCard {
  about: string | null;
  place_note: string | null;
  offers: TutorOffer[];
}

/** A slug as the catalog writes it: Latin words and the id, `anna-k-123`. */
const SLUG = /^(?:[a-z0-9]+-)*([1-9][0-9]{0,14})$/;
const UNITS: readonly PriceUnit[] = [
  'hour',
  'lesson',
  'work',
  'day',
  'week',
  'month',
  'semester',
  'item',
];
const FORMATS: readonly WorkFormat[] = ['online', 'offline', 'both'];

export function tutorPath(lang: Lang, slug: string): string {
  return localePath(lang, `/tutors/${slug}/`);
}

/**
 * The id a slug ends with, which is what finds the tutor; the name part is
 * for the reader, and a stale one is redirected (load.ts). Fifteen digits at
 * most, so the number is exact.
 */
export function idFromSlug(slug: string | undefined): number | null {
  const id = slug ? SLUG.exec(slug)?.[1] : undefined;
  return id ? Number(id) : null;
}

const text = (value: unknown): string | null =>
  typeof value === 'string' && value.trim() ? value : null;
const texts = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((v): v is string => text(v) !== null) : [];
const count = (value: unknown): number =>
  typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : 0;

function price(value: unknown): Price | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const unit = UNITS.find((u) => u === row.unit);
  const currency = text(row.currency);
  if (typeof row.amount !== 'number' || !Number.isFinite(row.amount) || row.amount < 0)
    return null;
  return unit && currency ? { amount: row.amount, currency, unit } : null;
}

function format(value: unknown): WorkFormat {
  return FORMATS.find((f) => f === value) ?? 'both';
}

function card(item: unknown): TutorCard | null {
  if (!item || typeof item !== 'object') return null;
  const row = item as Record<string, unknown>;
  const slug = text(row.slug);
  const name = text(row.name);
  const id = row.user_id;
  // The slug must be this tutor's: its id is what the page is looked up by.
  if (!slug || !name || typeof id !== 'number' || idFromSlug(slug) !== id) return null;
  const tone = count(row.tone);
  return {
    user_id: id,
    slug,
    name,
    initials: text(row.initials) ?? name.slice(0, 1).toUpperCase(),
    tone: tone <= 5 ? tone : 0,
    headline: text(row.headline),
    services: texts(row.services),
    subjects: texts(row.subjects),
    price_from: price(row.price_from),
    langs: texts(row.langs),
    work_format: format(row.work_format),
    city: text(row.city),
    rating:
      typeof row.rating === 'number' && row.rating >= 0 && row.rating <= 5
        ? row.rating
        : null,
    deals_count: count(row.deals_count),
  };
}

export function sanitizeTutors(payload: unknown): TutorCard[] {
  if (!Array.isArray(payload)) throw new Error('the tutors are not a list');
  return payload.map(card).filter((row): row is TutorCard => row !== null);
}

function offer(item: unknown): TutorOffer | null {
  if (!item || typeof item !== 'object') return null;
  const row = item as Record<string, unknown>;
  const service = text(row.service_type_name);
  if (!service) return null;
  return {
    service,
    subject: text(row.subject),
    institution: text(row.institution),
    price: price(row.price),
    langs: texts(row.langs),
    work_format: format(row.work_format),
    options: texts(row.options),
    note: text(row.note),
  };
}

export function sanitizeTutor(payload: unknown): TutorPage {
  const base = card(payload);
  if (!base) throw new Error('the tutor is not one the site can address');
  const row = payload as Record<string, unknown>;
  return {
    ...base,
    about: text(row.about),
    place_note: text(row.place_note),
    offers: Array.isArray(row.offers)
      ? row.offers.map(offer).filter((o): o is TutorOffer => o !== null)
      : [],
  };
}

const UNIT_NAMES: Record<Lang, Record<PriceUnit, string>> = {
  ru: {
    hour: 'час',
    lesson: 'занятие',
    work: 'работа',
    day: 'день',
    week: 'неделя',
    month: 'месяц',
    semester: 'семестр',
    item: 'штука',
  },
  uk: {
    hour: 'година',
    lesson: 'заняття',
    work: 'робота',
    day: 'день',
    week: 'тиждень',
    month: 'місяць',
    semester: 'семестр',
    item: 'штука',
  },
  cs: {
    hour: 'hodina',
    lesson: 'lekce',
    work: 'práce',
    day: 'den',
    week: 'týden',
    month: 'měsíc',
    semester: 'semestr',
    item: 'kus',
  },
  en: {
    hour: 'hour',
    lesson: 'lesson',
    work: 'piece of work',
    day: 'day',
    week: 'week',
    month: 'month',
    semester: 'semester',
    item: 'item',
  },
};

/** «450 Kč / час»: the amount, the currency as Czechia writes it, what it is for. */
export function priceText(lang: Lang, value: Price | null): string | null {
  if (!value) return null;
  const currency = value.currency === 'CZK' ? 'Kč' : value.currency;
  return `${num(lang, value.amount)} ${currency} / ${UNIT_NAMES[lang][value.unit]}`;
}
