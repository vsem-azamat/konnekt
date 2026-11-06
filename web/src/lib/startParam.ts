import { INSTITUTION_CODE } from './chats.ts';

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
  // /chats in a chat the bot knows no university for.
  chats: '/chats',
};

/**
 * A university's chats, by its code: `uni-cvut`. The code and not the
 * section's name, which has diacritics and spaces a start parameter may not
 * hold; the section screen finds the name from the code.
 */
const UNIVERSITY = 'uni-';

/**
 * A helper's profile, by their id: `helper-123`, from «Написать в Konnekt» on
 * their page on konnekt.cz. The catalog's /open passes it on only for a helper
 * the site shows.
 */
const HELPER = /^helper-([1-9][0-9]{0,17})$/;

export function startRoute(param: string | undefined): StartRoute | null {
  const university = param?.startsWith(UNIVERSITY)
    ? param.slice(UNIVERSITY.length)
    : undefined;
  if (university && INSTITUTION_CODE.test(university))
    return { path: `/chats/${university}`, state: { from: 'link' } };
  const helper = param ? HELPER.exec(param)?.[1] : undefined;
  if (helper) return { path: `/helper/${helper}`, state: { from: 'link' } };
  const path = param ? SCREENS[param] : undefined;
  return path ? { path, state: { from: 'link' } } : null;
}
