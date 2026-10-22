/**
 * The shared vocabulary of the interface.
 *
 * Six colour tones, referenced by index, chosen by the server. That is what
 * keeps a person the same colour on the results list and on their own page
 * without the client having to remember anything.
 */

import { type ReactNode, useState } from 'react';

import { assetUrl } from '@/lib/api';
import type { Avatar, Price } from '@/lib/types';

import { CheckIcon, ChevronIcon, CloseIcon } from './icons';
import css from './ui.module.css';

const TONES = 6;

function toneStyle(tone: number): React.CSSProperties {
  const index = ((tone % TONES) + TONES) % TONES;
  return {
    background: `var(--tone-${index}-bg)`,
    color: `var(--tone-${index}-fg)`,
  };
}

// ── layout ──────────────────────────────────────────────────────────────

export function Screen({ children }: { children: ReactNode }) {
  return <div className={css.screen}>{children}</div>;
}

// The header moved to its own file when it grew controls: see AppHeader.

/**
 * Two columns of tiles.
 *
 * For a set small enough to see at once — the seven kinds of help — where a
 * list would cost a scroll to say the same thing.
 */
export function Grid({ children }: { children: ReactNode }) {
  return <div className={css.grid}>{children}</div>;
}

export function Cell({
  leading,
  title,
  hint,
  trailing,
  /** Spans both columns and lays out as a row, for the one that matters most. */
  wide = false,
  /**
   * Undefined on a grid that navigates, boolean on one that chooses. The
   * distinction is the whole difference between the two screens that use this,
   * and `aria-pressed` has to be absent rather than false on a tile that is
   * not a toggle at all.
   */
  selected,
  onClick,
}: {
  leading?: ReactNode;
  title: ReactNode;
  hint?: ReactNode;
  trailing?: ReactNode;
  wide?: boolean;
  selected?: boolean;
  onClick: () => void;
}) {
  if (wide) {
    return (
      <button
        type="button"
        className={`${css.cell} ${css.cellWide} ${css.pressable} ${
          selected ? css.cellOn : ''
        }`}
        aria-pressed={selected}
        onClick={onClick}
      >
        {leading}
        <span className={css.rowBody}>
          <span className={css.rowName}>{title}</span>
          {hint ? <span className={css.rowHint}>{hint}</span> : null}
        </span>
        {trailing ? <span className={css.rowTrailing}>{trailing}</span> : null}
        {selected === undefined ? null : <CellCheck on={selected} wide />}
      </button>
    );
  }

  return (
    <button
      type="button"
      className={`${css.cell} ${css.pressable} ${selected ? css.cellOn : ''}`}
      aria-pressed={selected}
      onClick={onClick}
    >
      {selected === undefined ? null : <CellCheck on={selected} />}
      {leading}
      <span className={css.cellName}>{title}</span>
      <span className={css.cellFoot}>
        <span className={css.cellHint}>{hint}</span>
        {/* Wrapped, like the wide cell's: two loose children under
            space-between put the trailing content in the middle of the tile
            whenever the hint is short. */}
        {trailing ? <span className={css.rowTrailing}>{trailing}</span> : null}
      </span>
    </button>
  );
}

/**
 * The tick in the corner of a chosen tile.
 *
 * Drawn even when off, as an empty ring: a checkmark that only appears once
 * something is chosen leaves the person to work out that the tiles are
 * choosable at all.
 */
function CellCheck({ on, wide = false }: { on: boolean; wide?: boolean }) {
  return (
    <span
      className={`${css.cellCheck} ${on ? css.cellCheckOn : ''} ${
        // A wide cell lays out as a row, so the corner is the wrong place: the
        // tick sits at the end of the line with everything else.
        wide ? css.cellCheckInline : ''
      }`}
      aria-hidden="true"
    >
      {on ? <CheckIcon size={11} /> : null}
    </span>
  );
}

export function Title({ children }: { children: ReactNode }) {
  return <h1 className={css.h1}>{children}</h1>;
}

export function Heading({ children }: { children: ReactNode }) {
  return <h2 className={css.h2}>{children}</h2>;
}

export function Label({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className={css.label}>
      <span>{children}</span>
      {aside ? <span>{aside}</span> : null}
    </div>
  );
}

export function Sub({ children }: { children: ReactNode }) {
  return <p className={css.sub}>{children}</p>;
}

export function Hint({ children }: { children: ReactNode }) {
  return <p className={css.hint}>{children}</p>;
}

// ── atoms ───────────────────────────────────────────────────────────────

/**
 * A tile's letters, sized to fit: an abbreviation such as «VŠCHT» is the
 * name, and a fixed size would push it over the tile's edge.
 */
export function Letters({ text }: { text: string }) {
  return (
    <span className={css.letters} data-length={Math.min(text.length, 5)}>
      {text}
    </span>
  );
}

export function Tile({
  tone,
  large = false,
  round = false,
  photo = null,
  children,
}: {
  tone: number;
  /** The head of a preview, where the tile stands for the whole chat. */
  large?: boolean;
  /** A chat's tile: round, and carrying its photo when it has one. */
  round?: boolean;
  /** A picture's path from the server. The letters stay underneath it. */
  photo?: string | null;
  children: ReactNode;
}) {
  const classes = [css.tile];
  if (large) classes.push(css.tileLarge);
  if (round) classes.push(css.tileRound);
  if (photo) classes.push(css.tilePhoto);
  return (
    <span className={classes.join(' ')} style={toneStyle(tone)}>
      {children}
      {/* Keyed by address: a photo that changed gets a fresh try, not the
          verdict of the one before it. */}
      {photo ? <TilePhoto key={photo} src={photo} /> : null}
    </span>
  );
}

/** The picture over a tile's letters; if it does not load, the letters stay. */
function TilePhoto({ src }: { src: string }) {
  const [shown, setShown] = useState(false);
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    <img
      className={shown ? `${css.tileImg} ${css.tileImgShown}` : css.tileImg}
      src={assetUrl(src)}
      // The name is next to it; a description would be read twice.
      alt=""
      decoding="async"
      onLoad={() => setShown(true)}
      onError={() => setFailed(true)}
    />
  );
}

export function AvatarView({
  avatar,
  size = 24,
  square = false,
  short = false,
}: {
  avatar: Avatar;
  size?: number;
  square?: boolean;
  /** One letter instead of two — for stacks, where the next circle covers the second. */
  short?: boolean;
}) {
  const style: React.CSSProperties = {
    ...toneStyle(avatar.tone),
    width: size,
    height: size,
    fontSize: Math.round(size * 0.4),
  };
  const className = square ? `${css.avatar} ${css.avatarSquare}` : css.avatar;

  // A Telegram photo URL expires; the monogram is what is left when it does.
  if (avatar.photo_url) {
    return (
      <img
        className={className}
        style={style}
        src={avatar.photo_url}
        alt=""
        width={size}
        height={size}
      />
    );
  }
  return (
    <span className={className} style={style} aria-hidden="true">
      {short ? avatar.initials.slice(0, 1) : avatar.initials}
    </span>
  );
}

export function AvatarStack({
  avatars,
  size = 24,
  ring,
}: {
  avatars: Avatar[];
  size?: number;
  ring?: string;
}) {
  if (!avatars.length) return null;
  return (
    <div
      className={css.stack}
      style={
        {
          '--stack-size': `${size}px`,
          ...(ring ? { '--stack-ring': ring } : {}),
        } as React.CSSProperties
      }
    >
      {/* Reversed here too, so row-reverse puts them back in the given order. */}
      {[...avatars].reverse().map((avatar) => (
        <AvatarView key={avatar.id} avatar={avatar} size={size} short />
      ))}
    </div>
  );
}

export function Count({ children }: { children: ReactNode }) {
  return <span className={css.count}>{children}</span>;
}

export function Chevron() {
  return <ChevronIcon size={17} className={css.chevron} />;
}

/**
 * `inline` for a badge beside a name: the default overhangs the edge of the
 * positioned row it sits in, and with no such ancestor it lands at the top of
 * the screen.
 */
export function Badge({ children, inline }: { children: ReactNode; inline?: boolean }) {
  return (
    <span className={inline ? `${css.badge} ${css.badgeInline}` : css.badge}>
      {children}
    </span>
  );
}

// ── rows ────────────────────────────────────────────────────────────────

export function Rows({ children }: { children: ReactNode }) {
  return <div className={css.rows}>{children}</div>;
}

export function Row({
  leading,
  title,
  hint,
  trailing,
  badge,
  outline = false,
  onClick,
}: {
  leading?: ReactNode;
  title: ReactNode;
  hint?: ReactNode;
  trailing?: ReactNode;
  badge?: ReactNode;
  /** Drawn rather than filled: a row for something that is not ours. */
  outline?: boolean;
  onClick?: () => void;
}) {
  const Tag = onClick ? 'button' : 'div';
  return (
    <Tag
      className={`${css.row} ${css.pressable}${outline ? ` ${css.rowOutline}` : ''}`}
      type={onClick ? 'button' : undefined}
      onClick={onClick}
    >
      {badge ? <Badge>{badge}</Badge> : null}
      {leading}
      <span className={css.rowBody}>
        <span className={css.rowName}>{title}</span>
        {hint ? <span className={css.rowHint}>{hint}</span> : null}
      </span>
      {trailing ? <span className={css.rowTrailing}>{trailing}</span> : null}
    </Tag>
  );
}

// ── chips ───────────────────────────────────────────────────────────────

export function Chips({ children }: { children: ReactNode }) {
  return <div className={css.chips}>{children}</div>;
}

export function ChipView({
  children,
  active = false,
  pressed,
  ghost = false,
  onRemove,
  onClick,
  removeLabel,
}: {
  children: ReactNode;
  active?: boolean;
  /** Set only on a chip that toggles: one that acts is not a toggle, and says so by having none. */
  pressed?: boolean;
  ghost?: boolean;
  onRemove?: () => void;
  onClick?: () => void;
  removeLabel?: string;
}) {
  const className = [css.chip, active && css.chipOn, ghost && css.chipGhost]
    .filter(Boolean)
    .join(' ');

  const body = (
    <>
      {children}
      {onRemove ? (
        <button
          type="button"
          className={css.chipRemove}
          aria-label={removeLabel}
          onClick={(event) => {
            event.stopPropagation();
            onRemove();
          }}
        >
          <CloseIcon size={12} />
        </button>
      ) : null}
    </>
  );

  // A chip that only removes is not itself a button; nesting one inside
  // another is invalid and breaks keyboard order.
  if (onClick && !onRemove) {
    return (
      <button
        type="button"
        className={`${className} ${css.pressable}`}
        aria-pressed={pressed}
        onClick={onClick}
      >
        {body}
      </button>
    );
  }
  return <span className={className}>{body}</span>;
}

// ── cards ───────────────────────────────────────────────────────────────

export function Cards({ children }: { children: ReactNode }) {
  return <div className={css.cards}>{children}</div>;
}

export function Card({
  children,
  onClick,
}: {
  children: ReactNode;
  onClick?: () => void;
}) {
  if (onClick) {
    return (
      <button type="button" className={`${css.card} ${css.pressable}`} onClick={onClick}>
        {children}
      </button>
    );
  }
  return <div className={css.card}>{children}</div>;
}

export function PriceView({ price, unitLabel }: { price: Price; unitLabel: ReactNode }) {
  if (price.amount == null) return null;
  return (
    <span className={css.price}>
      <b className={css.priceAmount}>
        {formatMoney(price.amount)} {price.currency === 'CZK' ? 'Kč' : price.currency}
      </b>
      <span className={css.priceUnit}>{unitLabel}</span>
    </span>
  );
}

/** Thin spaces between thousands: "8 900", the way prices are written here. */
export function formatMoney(amount: number): string {
  return Math.round(amount)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

export function Reason({
  children,
  weak = false,
}: {
  children: ReactNode;
  weak?: boolean;
}) {
  return (
    <p className={css.reason}>
      <i className={weak ? `${css.reasonDot} ${css.weak}` : css.reasonDot} />
      <span>{children}</span>
    </p>
  );
}

export function Free({ children }: { children: ReactNode }) {
  return (
    <p className={css.free}>
      <i className={css.freeDot} />
      {children}
    </p>
  );
}

// ── segmented control ───────────────────────────────────────────────────

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
  disabled = false,
}: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (value: T) => void;
  /** What is chosen, for a screen reader when no heading says it. */
  label?: string;
  /** While a choice is being saved: another would race it. */
  disabled?: boolean;
}) {
  return (
    <div className={css.seg} role="tablist" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          className={css.segItem}
          aria-selected={option.value === value}
          disabled={disabled}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

// ── actions ─────────────────────────────────────────────────────────────

export function Actions({ children }: { children: ReactNode }) {
  return <div className={css.actions}>{children}</div>;
}

/**
 * A button inside the page, as opposed to Telegram's main button.
 *
 * There is only one main button and it belongs to the screen; a list where
 * every card can be accepted or turned down needs its own.
 */
export function Action({
  children,
  onClick,
  quiet,
  danger,
  tall,
  disabled,
}: {
  children: ReactNode;
  onClick: () => void;
  quiet?: boolean;
  /** For what cannot be undone, and nothing else. */
  danger?: boolean;
  /** 44 px, for the buttons a screen exists to have pressed. */
  tall?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className={`${css.action} ${quiet ? css.actionQuiet : ''} ${danger ? css.actionDanger : ''} ${tall ? css.actionTall : ''} ${css.pressable}`}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

// ── states ──────────────────────────────────────────────────────────────

/** Text cut to two lines, for a card that shows the rest when opened. */
export const CLAMP_TWO_LINES = {
  display: '-webkit-box',
  WebkitLineClamp: 2,
  WebkitBoxOrient: 'vertical',
  overflow: 'hidden',
  // One unbroken string (a pasted link) wraps instead of running off the card.
  overflowWrap: 'anywhere',
} as const;

export function Empty({
  title,
  body,
  action,
}: {
  title: ReactNode;
  body?: ReactNode;
  /** What to do about it; an empty list that tells you to act should let you. */
  action?: ReactNode;
}) {
  return (
    <div className={css.empty}>
      <p className={css.emptyTitle}>{title}</p>
      {body ? <p className={css.emptyBody}>{body}</p> : null}
      {action ? (
        <div className={`${css.actions} ${css.emptyAction}`}>{action}</div>
      ) : null}
    </div>
  );
}

/**
 * Placeholder rows in the shape of the real ones.
 *
 * A spinner tells you to wait; this tells you what is coming and stops the
 * layout jumping when it lands.
 */
export function SkeletonRows({ count = 4 }: { count?: number }) {
  return (
    <div className={css.rows} aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: placeholders have no identity and never reorder
        <div key={index} className={css.skeleton} style={{ height: 'var(--h-row)' }} />
      ))}
    </div>
  );
}

export { css as ui };
