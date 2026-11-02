import type { APIRoute } from 'astro';

/**
 * Search engines may read the site; the app's screens carry X-Robots-Tag:
 * noindex from docker/Caddyfile, and the API is no page at all.
 */
export const GET: APIRoute = ({ site }) =>
  new Response(
    [
      'User-agent: *',
      'Disallow: /api/',
      '',
      `Sitemap: ${new URL('/sitemap-index.xml', site)}`,
      '',
    ].join('\n'),
    { headers: { 'Content-Type': 'text/plain; charset=utf-8' } },
  );
