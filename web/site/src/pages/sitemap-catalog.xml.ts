import { allPlaceTexts } from '../catalog/places.ts';
import { catalogSitemap } from '../catalog/sitemap.ts';

/** The catalog pages search engines may keep (catalog/sitemap.ts), rendered on request. */
export const prerender = false;

export const GET = catalogSitemap(allPlaceTexts);
