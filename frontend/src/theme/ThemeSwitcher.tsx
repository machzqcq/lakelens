import { useEffect, useRef, useState } from 'react';
import { Palette, Check } from 'lucide-react';
import { useTheme, type ThemeName } from './ThemeContext';

export default function ThemeSwitcher({ compact = false }: { compact?: boolean }) {
  const { theme, setTheme, themes } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  // Close on click-outside / Escape
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [open]);

  const current = themes.find((t) => t.name === theme) ?? themes[0];

  function pick(t: ThemeName) {
    setTheme(t);
    setOpen(false);
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title={`Theme: ${current.label}`}
        aria-label="Switch theme"
        className={`flex items-center justify-center gap-2 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-card-hover)] transition-colors shadow-sm ${
          compact
            ? 'w-9 h-9'                          /* exactly square in compact mode */
            : 'px-2.5 py-1.5'
        }`}
      >
        <Palette size={14} />
        {!compact && (
          <>
            <span className="flex items-center gap-0.5">
              {current.swatch.map((c, i) => (
                <span key={i} className="w-2.5 h-2.5 rounded-full border border-black/10" style={{ backgroundColor: c }} />
              ))}
            </span>
            <span className="text-xs font-medium">{current.label}</span>
          </>
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-72 z-50 rounded-xl shadow-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-2">
          <p className="px-2 py-1 text-[10px] uppercase tracking-wider font-semibold text-[var(--color-text-muted)]">Theme</p>
          <div className="space-y-0.5">
            {themes.map((t) => (
              <button
                key={t.name}
                type="button"
                onClick={() => pick(t.name)}
                className={`w-full flex items-center gap-3 px-2 py-2 rounded-lg text-left transition-colors ${
                  t.name === theme
                    ? 'bg-[var(--color-bg-card-hover)]'
                    : 'hover:bg-[var(--color-bg-card-hover)]'
                }`}
              >
                <span className="flex items-center gap-1 shrink-0">
                  {t.swatch.map((c, i) => (
                    <span key={i} className="w-4 h-4 rounded-full border border-black/10" style={{ backgroundColor: c }} />
                  ))}
                </span>
                <span className="flex-1 min-w-0">
                  <span className="block text-sm font-medium text-[var(--color-text-primary)]">{t.label}</span>
                  <span className="block text-[11px] text-[var(--color-text-muted)] truncate">{t.description}</span>
                </span>
                {t.name === theme && <Check size={14} className="text-[var(--color-primary)] shrink-0" />}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
