/**
 * Where a `startapp` link opens the app.
 *
 * Most start parameters only say where somebody came from (`welcome` from a
 * chat greeting), and the audience records them; those open nothing. A few
 * name a screen, so that a button in the bot or a chat can lead straight to
 * it instead of to the first tab.
 */

export interface StartRoute {
  path: string;
  state: { from: 'link' };
}

const SCREENS: Record<string, string> = {
  offer: '/offer',
};

export function startRoute(param: string | undefined): StartRoute | null {
  const path = param ? SCREENS[param] : undefined;
  return path ? { path, state: { from: 'link' } } : null;
}
