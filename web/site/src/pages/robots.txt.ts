import type { APIRoute } from 'astro';

/**
 * Search engines may read the site. The app is on a host of its own, whose
 * screens say noindex themselves (docker/Caddyfile); here an API path is only
 * the way into the bot.
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
