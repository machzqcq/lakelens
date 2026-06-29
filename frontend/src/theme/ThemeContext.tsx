import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

export type ThemeName = 'light' | 'dark' | 'midnight' | 'forest' | 'sunset' | 'ocean';

interface ThemeMeta {
  name: ThemeName;
  label: string;
  description: string;
  /** Three swatch colors used by the picker (background / primary / accent) */
  swatch: [string, string, string];
}

export const THEMES: ThemeMeta[] = [
  { name: 'light',    label: 'Light',    description: 'Apple-ish clean light',     swatch: ['#ffffff', '#0071e3', '#00856f'] },
  { name: 'dark',     label: 'Dark',     description: 'Neutral dark',              swatch: ['#1c1c1e', '#2997ff', '#34d399'] },
  { name: 'midnight', label: 'Midnight', description: 'Deep purple / pink accent', swatch: ['#0f0f1a', '#a78bfa', '#f472b6'] },
  { name: 'forest',   label: 'Forest',   description: 'Cream + emerald',           swatch: ['#fdfcf7', '#15803d', '#ca8a04'] },
  { name: 'sunset',   label: 'Sunset',   description: 'Warm orange + pink',        swatch: ['#fff8f1', '#ea580c', '#db2777'] },
  { name: 'ocean',    label: 'Ocean',    description: 'Cool teal + cyan',          swatch: ['#f0fdfa', '#0e7490', '#06b6d4'] },
];

const STORAGE_KEY = 'app.theme';

interface ThemeContextValue {
  theme: ThemeName;
  setTheme: (t: ThemeName) => void;
  themes: ThemeMeta[];
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readSavedTheme(): ThemeName {
  try {
    const stored = localStorage.getItem(STORAGE_KEY) as ThemeName | null;
    if (stored && THEMES.some((t) => t.name === stored)) return stored;
  } catch {
    /* ignore */
  }
  // Respect prefers-color-scheme on first load
  if (typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches) {
    return 'dark';
  }
  return 'light';
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeName>(() => readSavedTheme());

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.style.colorScheme = ['dark', 'midnight'].includes(theme) ? 'dark' : 'light';
    try { localStorage.setItem(STORAGE_KEY, theme); } catch { /* ignore */ }
  }, [theme]);

  const setTheme = useCallback((t: ThemeName) => setThemeState(t), []);

  const value = useMemo<ThemeContextValue>(() => ({ theme, setTheme, themes: THEMES }), [theme, setTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used inside <ThemeProvider>');
  return ctx;
}
