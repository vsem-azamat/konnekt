/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Origin of the API. Leave unset so calls stay same-origin and go through the
   * dev proxy — Telegram only allows Mini App API calls from the app's own
   * origin, so a cross-origin base is the exception.
   */
  readonly VITE_API_BASE_URL?: string;
  /**
   * Raw init data to use instead of the generated mock when developing outside
   * Telegram. Paste a real signed string here to exercise authenticated calls.
   * Read only in development.
   */
  readonly VITE_MOCK_INIT_DATA?: string;
  /** The commit this build was made from, set by the image build; reported with a failure. */
  readonly VITE_APP_VERSION?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

/** Compiled by `@lingui/vite-plugin` into a loadable message catalog. */
declare module '*.po' {
  import type { Messages } from '@lingui/core';
  export const messages: Messages;
}
