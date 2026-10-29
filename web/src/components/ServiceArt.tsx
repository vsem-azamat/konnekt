/**
 * A picture of what a service looks like in Czech life, for an open place
 * on the showcase. Our own drawings: silhouettes of a card, a statement, a
 * stamp, never a real brand or a state document's design, and no readable
 * words. Outlines in the service's tone over its light fill, like the 24px
 * icons grown up; those stay in the tiles, where a drawing would not read.
 */

import css from './ServiceArt.module.css';

const ART: Record<string, React.ReactNode> = {
  bank_letter: (
    <>
      <rect className={css.body} x="42" y="11" width="44" height="55" rx="3" />
      <rect className={css.body} x="32" y="6" width="46" height="58" rx="3" />
      <path className={css.ink} d="M38 15h16" strokeWidth="3" />
      <rect className={css.mark} x="66" y="11" width="6" height="6" rx="1.5" />
      <path className={css.ink} d="M38 26h22M64 26h8M38 33h18M64 33h8M38 40h24M64 40h8" />
      <path className={css.ink} d="M38 49h34" />
      <path className={css.ink} d="M60 55h12" strokeWidth="3" />
      <circle className={css.body} cx="18" cy="52" r="9" />
      <circle className={css.ink} cx="18" cy="52" r="5" />
      <circle className={css.ring} cx="76" cy="53" r="9" />
      <circle className={css.ring} cx="76" cy="53" r="5.5" strokeDasharray="2 2" />
    </>
  ),
  insurance: (
    <>
      <rect className={css.body} x="22" y="14" width="64" height="42" rx="5" />
      <path className={css.mark} d="M22 24v-5a5 5 0 0 1 5-5h54a5 5 0 0 1 5 5v5z" />
      <circle className={css.ink} cx="36" cy="39" r="8" />
      <path className={css.ring} d="M36 35v8M32 39h8" strokeWidth="2.6" />
      <path className={css.ink} d="M50 34h26M50 40h22M50 46h14" />
      <path
        className={css.body}
        d="M94 28l11 4v9c0 8-5 12.5-11 15-6-2.5-11-7-11-15v-9z"
      />
      <path className={css.ring} d="M89 41.5l3.5 3.5 6.5-6.5" />
    </>
  ),
  residence: (
    <>
      <rect className={css.body} x="74" y="22" width="26" height="36" rx="3" />
      <circle className={css.ink} cx="91" cy="40" r="4.5" />
      <rect className={css.body} x="18" y="14" width="66" height="44" rx="5" />
      <rect className={css.ink} x="24" y="22" width="16" height="20" rx="2" />
      <circle className={css.ink} cx="32" cy="29" r="3.5" />
      <path className={css.ink} d="M26.5 41a5.5 5.5 0 0 1 11 0" />
      <rect className={css.ring} x="46" y="22" width="10" height="8" rx="1.5" />
      <path className={css.ring} d="M46 26h10M51 22v8" />
      <rect className={css.mark} x="68" y="20" width="10" height="7" rx="1" />
      <path className={css.ink} d="M46 37h28M46 43h20" />
      <path className={css.ink} d="M24 51h54" strokeDasharray="2.5 2" />
    </>
  ),
  translation: (
    <>
      <rect className={css.body} x="20" y="8" width="38" height="50" rx="3" />
      <path className={css.ink} d="M26 18h24M26 24h20M26 30h26M26 36h16" />
      <rect className={css.body} x="50" y="14" width="40" height="52" rx="3" />
      <path className={css.ink} d="M56 24h26M56 30h22M56 36h28M56 42h18" />
      <path className={css.ink} d="M73 58c-4 5-9 8-15 7M79 61c0 4-2 8-6 10" />
      <circle className={css.mark} cx="79" cy="54" r="7" />
      <circle className={css.cut} cx="79" cy="54" r="4" />
    </>
  ),
  housing: (
    <>
      <path className={css.ink} d="M8 66h104" />
      <circle className={css.body} cx="20" cy="47" r="9" />
      <path className={css.ink} d="M20 56v10" />
      <rect className={css.body} x="76" y="30" width="24" height="36" rx="2" />
      <path
        className={css.dots}
        d="M81 36h4M91 36h4M81 43h4M91 43h4M81 50h4M91 50h4M81 57h4M91 57h4"
      />
      <rect className={css.body} x="34" y="8" width="40" height="58" rx="2" />
      <path
        className={css.dots}
        d="M39 15h5M48 15h5M57 15h5M66 15h4M39 22h5M48 22h5M57 22h5M66 22h4M39 29h5M48 29h5M57 29h5M66 29h4M39 36h5M48 36h5M57 36h5M66 36h4M39 43h5M48 43h5M57 43h5M66 43h4M39 50h5M57 50h5M66 50h4"
      />
      <rect className={css.mark} x="50" y="56" width="8" height="10" rx="1" />
    </>
  ),
  rental: (
    <>
      <rect className={css.body} x="26" y="12" width="46" height="32" rx="3" />
      <path className={css.ink} d="M33 21h22M33 27h16M33 33h20" />
      <path className={css.body} d="M18 48h62l-5 7H23z" />
      <path className={css.ink} d="M80 26c-4 0-7 3-8 7" />
      <path className={css.body} d="M82 16h15l7 8-7 8H82z" />
      <circle className={css.mark} cx="87" cy="24" r="2.5" />
    </>
  ),
  books: (
    <>
      <rect className={css.body} x="22" y="52" width="58" height="12" rx="2" />
      <rect className={css.body} x="28" y="40" width="52" height="12" rx="2" />
      <rect className={css.body} x="20" y="28" width="54" height="12" rx="2" />
      <path className={css.ink} d="M30 52v12M36 40v12M28 28v12" />
      <path className={css.mark} d="M60 28v-7l3.5 3 3.5-3v7z" />
      <rect className={css.body} x="86" y="14" width="16" height="50" rx="2" />
      <path className={css.ink} d="M90 22h8M90 27h6" />
    </>
  ),
};

/** Whether `code` has a drawing; a service added later keeps its icon. */
export function hasArt(code: string) {
  return code in ART;
}

export function ServiceArt({ code }: { code: string }) {
  return (
    <svg className={css.art} viewBox="0 0 120 72" aria-hidden="true" focusable="false">
      {ART[code]}
    </svg>
  );
}
