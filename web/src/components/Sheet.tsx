/**
 * A panel that comes up from the bottom edge.
 *
 * Used where a question has three or four answers and a whole screen would be
 * too much ceremony: which language, what kind of thing you are posting. The
 * answer arrives without losing the screen behind it, which is the point —
 * navigating away to choose a language and navigating back is two more taps
 * than the choice is worth.
 */

import { type ReactNode, useEffect, useId, useRef } from 'react';

import { CheckIcon } from './icons';
import { focusInto, giveFocusBack } from './sheetFocus';
import css from './ui.module.css';

export function Sheet({
  title,
  onClose,
  closeLabel,
  children,
}: {
  title: ReactNode;
  onClose: () => void;
  /** For the scrim, which is a button and would otherwise be unnamed. */
  closeLabel: string;
  children: ReactNode;
}) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);

  // Focus moves into the sheet when it opens and back to what opened it when
  // it closes. Its own effect, run once: tied to `onClose`, whose identity
  // changes with every render of the screen behind, it would take focus back
  // from whatever the person had just focused inside.
  useEffect(() => {
    const opener = document.activeElement;
    focusInto(panel.current);
    return () => giveFocusBack(opener instanceof HTMLElement ? opener : null);
  }, []);

  // Escape closes it, from anywhere in the page rather than from the panel: a
  // key handler on the panel would hear nothing once focus is on the scrim.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <>
      <button
        type="button"
        className={css.scrim}
        aria-label={closeLabel}
        onClick={onClose}
      />
      <div
        ref={panel}
        className={css.sheet}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <span className={css.grabber} />
        <span id={titleId} className={css.sheetTitle}>
          {title}
        </span>
        <div className={css.sheetBody}>{children}</div>
      </div>
    </>
  );
}

export function Pick({
  leading,
  name,
  hint,
  selected = false,
  disabled = false,
  onClick,
}: {
  leading?: ReactNode;
  name: ReactNode;
  hint?: ReactNode;
  selected?: boolean;
  /** While the choice before it is on its way. */
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={css.pick}
      aria-pressed={selected}
      disabled={disabled}
      onClick={onClick}
    >
      {leading}
      <span className={css.pickBody}>
        <span className={css.pickName}>{name}</span>
        {hint ? <span className={css.pickHint}>{hint}</span> : null}
      </span>
      {selected ? <CheckIcon size={17} className={css.pickCheck} /> : null}
    </button>
  );
}
