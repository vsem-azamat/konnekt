import css from './ui.module.css';

/**
 * On or off, saved the moment it is flipped: no «Сохранить» for a setting
 * that is one bit. Busy while the change is on its way, so a second flip
 * cannot race the first.
 */
export function Switch({
  checked,
  busy = false,
  label,
  onChange,
}: {
  checked: boolean;
  busy?: boolean;
  label: string;
  onChange: (next: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      aria-busy={busy}
      disabled={busy}
      className={css.switch}
      onClick={() => onChange(!checked)}
    />
  );
}
