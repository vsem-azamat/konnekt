import { Trans } from '@lingui/react/macro';
import { openTelegramLink } from '@tma.js/sdk-react';
import { useState } from 'react';

import { useBrowserConsole } from '@/console/browserContext';
import css from '@/console/Faces.module.css';
import {
  chatLetters,
  chatPhotoPath,
  type FacePerson,
  personLetters,
  personPhotoPath,
  personTone,
  profileLink,
} from '@/console/faces';
import { assetUrl } from '@/lib/api';

function Face({
  letters,
  tone,
  photo,
  size,
  square,
}: {
  letters: string;
  tone: number;
  photo: string;
  size: number;
  square: boolean;
}) {
  const [shown, setShown] = useState(false);
  const [failed, setFailed] = useState(false);
  return (
    <span
      className={square ? `${css.face} ${css.square}` : css.face}
      style={{
        width: size,
        height: size,
        fontSize: Math.max(7, Math.round(size * (letters.length > 2 ? 0.3 : 0.4))),
        background: `var(--tone-${tone}-bg)`,
        color: `var(--tone-${tone}-fg)`,
      }}
      aria-hidden="true"
    >
      {letters}
      {/* The letters stay under it while it loads, and as the answer when there is none. */}
      {failed ? null : (
        <img
          className={shown ? `${css.photo} ${css.photoShown}` : css.photo}
          src={assetUrl(photo)}
          alt=""
          decoding="async"
          loading="lazy"
          onLoad={() => setShown(true)}
          onError={() => setFailed(true)}
        />
      )}
    </span>
  );
}

/** A person, round. */
export function PersonFace({ person, size }: { person: FacePerson; size: number }) {
  return (
    <Face
      key={person.user_id}
      letters={personLetters(person)}
      tone={personTone(person.user_id)}
      photo={personPhotoPath(person.user_id)}
      size={size}
      square={false}
    />
  );
}

/** A chat, a rounded square. */
export function ChatFace({
  chat,
  size,
  tone = 3,
}: {
  chat: { id: number; title: string | null };
  size: number;
  tone?: number;
}) {
  return (
    <Face
      key={chat.id}
      letters={chatLetters(chat)}
      tone={tone}
      photo={chatPhotoPath(chat.id)}
      size={size}
      square
    />
  );
}

/**
 * How to reach a person in Telegram: their @username, which opens the profile,
 * or their id to copy. A bare id has no link a browser can open.
 */
export function Handle({ person }: { person: FacePerson }) {
  const inBrowser = useBrowserConsole();
  const [copied, setCopied] = useState(false);
  const link = profileLink(person);
  if (link) {
    return (
      <span className={css.handle}>
        <a
          href={link}
          target="_blank"
          rel="noreferrer"
          onClick={(event) => {
            // Inside Telegram the profile opens in Telegram, not a browser tab.
            if (inBrowser || !openTelegramLink.isAvailable()) return;
            event.preventDefault();
            openTelegramLink(link);
          }}
        >
          @{person.username}
        </a>
      </span>
    );
  }
  const id = person.user_id;
  return (
    <span className={css.handle}>
      <span>
        <Trans>без @username · id {id}</Trans>
      </span>
      <button
        type="button"
        className={css.copy}
        onClick={() =>
          // Refused (a WebView without it, a denied permission): the id is on
          // screen to select by hand.
          void navigator.clipboard
            ?.writeText(String(person.user_id))
            .then(() => setCopied(true))
            .catch(() => undefined)
        }
      >
        {copied ? <Trans>Скопировано</Trans> : <Trans>Скопировать id</Trans>}
      </button>
    </span>
  );
}
