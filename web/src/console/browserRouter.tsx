import type { ReactElement } from 'react';
import { createBrowserRouter } from 'react-router';
import BrowserNotFound from '@/console/BrowserNotFound';
import BrowserShell from '@/console/BrowserShell';
import { BROWSER_PATHS, type BrowserPath } from '@/console/browser';
import LoginPage from '@/console/Login';
import ConsoleAudiencePage from '@/console/pages/Audience';
import ConsoleAudiencePeoplePage from '@/console/pages/AudiencePeople';
import ConsoleAudiencePersonPage from '@/console/pages/AudiencePerson';
import ConsoleBlacklistPage from '@/console/pages/Blacklist';
import ConsoleCatalogPage from '@/console/pages/Catalog';
import ConsoleChatPage from '@/console/pages/Chat';
import ConsoleChatsPage from '@/console/pages/Chats';
import ConsolePartnerNewPage from '@/console/pages/PartnerNew';
import ConsolePartnersPage from '@/console/pages/Partners';
import ConsoleSignalsPage from '@/console/pages/Signals';
import ConsoleSpamPage from '@/console/pages/Spam';
import ConsoleSummaryPage from '@/console/pages/Summary';
import ConsoleSystemPage from '@/console/pages/System';

/**
 * What a browser gets: the console beside its menu, and the way to sign in.
 * Every screen is reached through webapi's session, the catalog's too.
 *
 * Its own module, which main.tsx imports only for a browser, so that the Mini
 * App never downloads it.
 */
const browserScreens: Record<BrowserPath, ReactElement> = {
  '': <ConsoleSummaryPage />,
  audience: <ConsoleAudiencePage />,
  'audience/people': <ConsoleAudiencePeoplePage />,
  'audience/:id': <ConsoleAudiencePersonPage />,
  catalog: <ConsoleCatalogPage />,
  partners: <ConsolePartnersPage />,
  'partners/new': <ConsolePartnerNewPage />,
  chats: <ConsoleChatsPage />,
  'chats/:id': <ConsoleChatPage />,
  spam: <ConsoleSpamPage />,
  blacklist: <ConsoleBlacklistPage />,
  signals: <ConsoleSignalsPage />,
  system: <ConsoleSystemPage />,
};

export const browserRouter = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    path: '/console',
    element: <BrowserShell />,
    children: [
      ...BROWSER_PATHS.map((path) =>
        path === ''
          ? { index: true as const, element: browserScreens[path] }
          : { path, element: browserScreens[path] },
      ),
      { path: '*', element: <BrowserNotFound /> },
    ],
  },
  { path: '*', element: <BrowserNotFound /> },
]);
