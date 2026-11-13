// Theme: "system" (follow the OS), "light" or "dark", remembered in this browser. The choice is applied as
// <html data-theme="..."> (no attribute = follow the system); index.css holds the colours for each.
// index.html applies the saved choice before the first paint, so the page never flashes the wrong theme.
import { useEffect, useState } from 'react';

const KEY = 'rag_validator_theme';
export const THEMES = ['system', 'light', 'dark'];

export function readTheme() {
  try {
    const v = localStorage.getItem(KEY);
    return THEMES.includes(v) ? v : 'system';
  } catch { return 'system'; }
}

function apply(theme) {
  const root = document.documentElement;
  if (theme === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', theme);
}

export function useTheme() {
  const [theme, setTheme] = useState(readTheme);
  useEffect(() => {
    apply(theme);
    try {
      if (theme === 'system') localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, theme);
    } catch { /* storage unavailable: the choice lasts until the page is closed */ }
  }, [theme]);
  return [theme, setTheme];
}
