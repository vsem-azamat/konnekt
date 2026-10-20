import { createContext, useContext } from 'react';

/**
 * Whether the console is open in a browser. Provided once, above the router
 * the browser gets; the Mini App never provides it, so it reads false there.
 */
export const BrowserConsoleContext = createContext(false);

export function useBrowserConsole(): boolean {
  return useContext(BrowserConsoleContext);
}
