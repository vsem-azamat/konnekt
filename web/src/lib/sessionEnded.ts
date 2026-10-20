/**
 * The cookie session a request went under has ended: webapi answered 401.
 *
 * Only the console in a browser asks that way (console/catalogDoor.ts), and it
 * answers this by signing in again (console/browser.ts, `endsSession`). Kept
 * apart from api.ts, which needs the Telegram SDK and Vite, so a test can
 * import it.
 */
export class SessionEndedError extends Error {
  constructor() {
    super('the session behind this request has ended');
    this.name = 'SessionEndedError';
  }
}
