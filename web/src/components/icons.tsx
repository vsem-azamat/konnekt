/**
 * The icon set, drawn inline.
 *
 * Hand-written rather than pulled from a library: there are under twenty of
 * them, they all share one stroke weight, and a package would ship several
 * hundred we never use. `currentColor` throughout, so a tile's foreground colour is the
 * only thing that has to be set.
 */

interface IconProps {
  size?: number;
  className?: string;
}

function Svg({
  size = 20,
  className,
  children,
}: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

export const SearchIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="6.4" />
    <path d="m16 16 4 4" />
  </Svg>
);

export const PersonIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="9" r="3.4" />
    <path d="M5.4 19.4a6.9 6.9 0 0 1 13.2 0" />
  </Svg>
);

export const TargetIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8" />
    <circle cx="12" cy="12" r="3.2" />
  </Svg>
);

export const ClockIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8" />
    <path d="M12 7.4V12l3.2 1.9" />
  </Svg>
);

export const DocumentIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6.4 3.8h6.8l4.4 4.5v11.9H6.4z" />
    <path d="M13 3.8v4.6h4.6" />
    <path d="M9.2 13h5.6M9.2 16.2h3.6" />
  </Svg>
);

export const SealIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="9.6" r="5.2" />
    <path d="m9 13.8-1.2 6L12 17.6l4.2 2.2-1.2-6" />
  </Svg>
);

export const LanguageIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4.5 6.5h6M7.5 5v1.5M9.5 6.5c0 4-2.5 7-5 8.5M6 10.5c1 2 3 3.8 5 4.5" />
    <path d="m13 19 4-10 4 10M14.4 16h5.2" />
  </Svg>
);

export const BookIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4.8 5.2h4.6c1.4 0 2.6 1 2.6 2.3v11.3c0-1-1.2-1.8-2.6-1.8H4.8z" />
    <path d="M19.2 5.2h-4.6c-1.4 0-2.6 1-2.6 2.3v11.3c0-1 1.2-1.8 2.6-1.8h4.6z" />
  </Svg>
);

export const HeadsetIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4.5 14v-2.5a7.5 7.5 0 0 1 15 0V14" />
    <rect x="3" y="13.5" width="4" height="6" rx="2" />
    <rect x="17" y="13.5" width="4" height="6" rx="2" />
  </Svg>
);

export const ChatIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20 12.4c0 3.6-3.6 6.5-8 6.5-1 0-2-.1-2.9-.4L4.4 20l1.3-3.2A6.6 6.6 0 0 1 4 12.4C4 8.8 7.6 5.9 12 5.9s8 2.9 8 6.5Z" />
  </Svg>
);

export const BookmarkIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6.5 4.5h11v15.5l-5.5-3.6-5.5 3.6z" />
  </Svg>
);

export const PlusIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 5.5v13M5.5 12h13" strokeWidth={2} />
  </Svg>
);

export const CloseIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="m7 7 10 10M17 7 7 17" strokeWidth={2.2} />
  </Svg>
);

/** The language button. A globe, not a flag: languages are not countries. */
export const GlobeIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.2" />
    <path d="M3.8 12h16.4" />
    <path d="M12 3.8a13 13 0 0 1 0 16.4 13 13 0 0 1 0-16.4" />
  </Svg>
);

export const SunIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2.8v2.1M12 19.1v2.1M4.9 4.9l1.5 1.5M17.6 17.6l1.5 1.5M2.8 12h2.1M19.1 12h2.1M4.9 19.1l1.5-1.5M17.6 6.4l1.5-1.5" />
  </Svg>
);

export const MoonIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20 14.2A8.2 8.2 0 0 1 9.8 4 8.4 8.4 0 1 0 20 14.2Z" />
  </Svg>
);

/** Selling a thing, as opposed to offering a skill. */
export const BagIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4.6 8.4h14.8v11.2H4.6z" />
    <path d="M9 8.4V6.8a3 3 0 0 1 6 0v1.6" />
  </Svg>
);

export const ChevronIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="m9.5 6 6 6-6 6" />
  </Svg>
);

export const CheckIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4.5 12.5 9.5 17l10-10" />
  </Svg>
);

export const LockIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="5" y="11" width="14" height="9" rx="2" />
    <path d="M8 11V8a4 4 0 0 1 8 0v3" />
  </Svg>
);

export const ShieldIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3.4 5.6 6v5.8c0 3.6 2.7 6.5 6.4 8.4 3.7-1.9 6.4-4.8 6.4-8.4V6L12 3.4Z" />
  </Svg>
);

export const BankIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.6 9.6 12 4.6l8.4 5" />
    <path d="M6.4 11.6v6.2" />
    <path d="M10.1 11.6v6.2" />
    <path d="M13.9 11.6v6.2" />
    <path d="M17.6 11.6v6.2" />
    <path d="M4 20.2h16" />
  </Svg>
);

export const PassportIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="5.8" y="3.4" width="12.4" height="17.2" rx="2" />
    <circle cx="12" cy="10.4" r="2.4" />
    <path d="M9.8 16.4h4.4" />
  </Svg>
);

export const HomeIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4.4 10.6 12 4.6l7.6 6v9H4.4v-9Z" />
    <path d="M9.8 19.6v-5.2h4.4v5.2" />
  </Svg>
);

/**
 * Which icon belongs to which kind of help.
 *
 * Keyed by the server's `code`, so adding a service type on the server shows
 * up here as the fallback rather than as a blank tile.
 */
const BY_SERVICE: Record<string, (p: IconProps) => React.ReactElement> = {
  tutoring: PersonIcon,
  entrance_prep: TargetIcon,
  language_tutoring: LanguageIcon,
  exam_live_help: ClockIcon,
  exam_prep: CheckIcon,
  nostrification: SealIcon,
  writing: DocumentIcon,
  // Help that is not about studying. The fallback is a person, which reads as
  // "a tutor" and is wrong for every one of these.
  insurance: ShieldIcon,
  bank_letter: BankIcon,
  translation: LanguageIcon,
  residence: PassportIcon,
  housing: HomeIcon,
  rental: HeadsetIcon,
  books: BookIcon,
};

export function iconForService(code: string) {
  return BY_SERVICE[code] ?? PersonIcon;
}
