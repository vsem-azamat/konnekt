import { createBrowserRouter, Navigate } from 'react-router';
import { RouteError } from '@/components/RouteError';
import { TabsLayout } from '@/components/TabsLayout';
import { lazyScreen as screen } from '@/lib/lazyScreen';
import AdsPage from '@/pages/Ads';
import AdsAppPage from '@/pages/AdsApp';
import AdsChatsPage from '@/pages/AdsChats';
import AskPage from '@/pages/Ask';
import ChatSectionPage from '@/pages/ChatSection';
import ChatsPage from '@/pages/Chats';
import HelperPage from '@/pages/Helper';
import HomePage from '@/pages/Home';
import JoinPage from '@/pages/Join';
import LifePage from '@/pages/Life';
import MinePage from '@/pages/Mine';
import MyHelperPage from '@/pages/MyHelper';
import MyHelperAboutPage from '@/pages/MyHelperAbout';
import NotFoundPage from '@/pages/NotFound';
import OfferPage from '@/pages/Offer';
import OfferPricesPage from '@/pages/OfferPrices';
import PartnerPage from '@/pages/Partner';
import ProfilePage from '@/pages/Profile';
import RequestPage from '@/pages/Request';
import ResultsPage from '@/pages/Results';
import Root from '@/Root';

/**
 * A browser router, not a hash router.
 *
 * The app is served from its own origin alongside the API, so real paths work
 * and survive a reload. Telegram's own back button is bound to this history in
 * `Root`.
 *
 * Every screen sits under one pathless route whose `errorElement` takes the
 * place of a screen that throws. It is below `Root` so that the back button
 * stays wired while it shows.
 *
 * The console's screens are lazy: only admins open them, and everyone else
 * would download them with the first screen.
 *
 * The first screen is /home, where the public site sends a Telegram launch
 * that landed on it (web/site/). The root leads there too. Opened at the root,
 * the address is rewritten before the router reads it, rather than redirected
 * by a <Navigate>: that would give the first location a key of its own, and
 * Telegram's back button would show on Home with nothing behind it.
 */
if (window.location.pathname === '/') {
  window.history.replaceState(
    window.history.state,
    '',
    `/home${window.location.search}${window.location.hash}`,
  );
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Root />,
    children: [
      {
        errorElement: <RouteError />,
        // A console screen opened by its link is fetched before it shows;
        // until then Root, and the back button with it, stand on their own.
        HydrateFallback: () => null,
        children: [
          {
            element: <TabsLayout />,
            children: [
              { index: true, element: <Navigate to="/home" replace /> },
              { path: 'home', element: <HomePage /> },
              { path: 'chats', element: <ChatsPage /> },
              { path: 'chats/:group', element: <ChatSectionPage /> },
              { path: 'results', element: <ResultsPage /> },
              { path: 'mine', element: <MinePage /> },
              { path: 'profile', element: <ProfilePage /> },
            ],
          },
          { path: 'ads', element: <AdsPage /> },
          { path: 'ads/chats', element: <AdsChatsPage /> },
          { path: 'ads/app', element: <AdsAppPage /> },
          { path: 'ask', element: <AskPage /> },
          { path: 'helper/:id', element: <HelperPage /> },
          { path: 'join', element: <JoinPage /> },
          { path: 'request/:id', element: <RequestPage /> },
          { path: 'offer', element: <OfferPage /> },
          { path: 'offer/prices', element: <OfferPricesPage /> },
          { path: 'my-helper', element: <MyHelperPage /> },
          { path: 'my-helper/about', element: <MyHelperAboutPage /> },
          { path: 'life', element: <LifePage /> },
          { path: 'partner/:id', element: <PartnerPage /> },
          { path: 'console', lazy: screen(() => import('@/console/pages/Summary')) },
          {
            path: 'console/audience',
            lazy: screen(() => import('@/console/pages/Audience')),
          },
          {
            path: 'console/audience/people',
            lazy: screen(() => import('@/console/pages/AudiencePeople')),
          },
          {
            path: 'console/audience/:id',
            lazy: screen(() => import('@/console/pages/AudiencePerson')),
          },
          {
            path: 'console/usage',
            lazy: screen(() => import('@/console/pages/Usage')),
          },
          {
            path: 'console/sources',
            lazy: screen(() => import('@/console/pages/Sources')),
          },
          {
            path: 'console/catalog',
            lazy: screen(() => import('@/console/pages/Catalog')),
          },
          {
            path: 'console/partners',
            lazy: screen(() => import('@/console/pages/Partners')),
          },
          {
            path: 'console/partners/new',
            lazy: screen(() => import('@/console/pages/PartnerNew')),
          },
          { path: 'console/chats', lazy: screen(() => import('@/console/pages/Chats')) },
          {
            path: 'console/chats/:id',
            lazy: screen(() => import('@/console/pages/Chat')),
          },
          { path: 'console/spam', lazy: screen(() => import('@/console/pages/Spam')) },
          {
            path: 'console/signals',
            lazy: screen(() => import('@/console/pages/Signals')),
          },
          {
            path: 'console/blacklist',
            lazy: screen(() => import('@/console/pages/Blacklist')),
          },
          {
            path: 'console/system',
            lazy: screen(() => import('@/console/pages/System')),
          },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
]);
