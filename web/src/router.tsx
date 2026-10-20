import { createBrowserRouter } from 'react-router';
import ConsoleAudiencePage from '@/console/pages/Audience';
import ConsoleAudiencePeoplePage from '@/console/pages/AudiencePeople';
import ConsoleAudiencePersonPage from '@/console/pages/AudiencePerson';
import ConsoleBlacklistPage from '@/console/pages/Blacklist';
import ConsoleCatalogPage from '@/console/pages/Catalog';
import ConsoleChatPage from '@/console/pages/Chat';
import ConsoleChatsPage from '@/console/pages/Chats';
import ConsolePartnerNewPage from '@/console/pages/PartnerNew';
import ConsolePartnersPage from '@/console/pages/Partners';
import ConsoleSpamPage from '@/console/pages/Spam';
import ConsoleSummaryPage from '@/console/pages/Summary';
import ConsoleSystemPage from '@/console/pages/System';
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
import NotFoundPage from '@/pages/NotFound';
import OfferPage from '@/pages/Offer';
import OfferPricesPage from '@/pages/OfferPrices';
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
 */
export const router = createBrowserRouter([
  {
    path: '/',
    element: <Root />,
    children: [
      { index: true, element: <HomePage /> },
      { path: 'ads', element: <AdsPage /> },
      { path: 'ads/chats', element: <AdsChatsPage /> },
      { path: 'ads/app', element: <AdsAppPage /> },
      { path: 'ask', element: <AskPage /> },
      { path: 'chats', element: <ChatsPage /> },
      { path: 'chats/:group', element: <ChatSectionPage /> },
      { path: 'results', element: <ResultsPage /> },
      { path: 'helper/:id', element: <HelperPage /> },
      { path: 'join', element: <JoinPage /> },
      { path: 'mine', element: <MinePage /> },
      { path: 'request/:id', element: <RequestPage /> },
      { path: 'offer', element: <OfferPage /> },
      { path: 'offer/prices', element: <OfferPricesPage /> },
      { path: 'my-helper', element: <MyHelperPage /> },
      { path: 'life', element: <LifePage /> },
      { path: 'profile', element: <ProfilePage /> },
      { path: 'console', element: <ConsoleSummaryPage /> },
      { path: 'console/audience', element: <ConsoleAudiencePage /> },
      { path: 'console/audience/people', element: <ConsoleAudiencePeoplePage /> },
      { path: 'console/audience/:id', element: <ConsoleAudiencePersonPage /> },
      { path: 'console/catalog', element: <ConsoleCatalogPage /> },
      { path: 'console/partners', element: <ConsolePartnersPage /> },
      { path: 'console/partners/new', element: <ConsolePartnerNewPage /> },
      { path: 'console/chats', element: <ConsoleChatsPage /> },
      { path: 'console/chats/:id', element: <ConsoleChatPage /> },
      { path: 'console/spam', element: <ConsoleSpamPage /> },
      { path: 'console/blacklist', element: <ConsoleBlacklistPage /> },
      { path: 'console/system', element: <ConsoleSystemPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]);
