import { describe, expect, test } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ThemeProvider, useTheme, THEMES } from '@app/theme/ThemeContext';

function Probe() {
  const { theme, setTheme } = useTheme();
  return (
    <div>
      <div data-testid="theme">{theme}</div>
      <button onClick={() => setTheme('midnight')}>midnight</button>
      <button onClick={() => setTheme('forest')}>forest</button>
    </div>
  );
}

describe('<ThemeProvider>', () => {
  test('defaults to light when nothing is stored and no media match', () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByTestId('theme')).toHaveTextContent('light');
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
  });

  test('reads previous selection from localStorage', () => {
    localStorage.setItem('app.theme', 'forest');
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByTestId('theme')).toHaveTextContent('forest');
    expect(document.documentElement.getAttribute('data-theme')).toBe('forest');
  });

  test('setTheme updates state, attribute, and storage', async () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    await act(async () => {
      await userEvent.click(screen.getByText('midnight'));
    });
    expect(screen.getByTestId('theme')).toHaveTextContent('midnight');
    expect(document.documentElement.getAttribute('data-theme')).toBe('midnight');
    expect(localStorage.getItem('app.theme')).toBe('midnight');
  });

  test('exposes all six themes', () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    const names = THEMES.map((t) => t.name);
    expect(names).toEqual(['light', 'dark', 'midnight', 'forest', 'sunset', 'ocean']);
  });

  test('dark variants set color-scheme: dark on html', () => {
    localStorage.setItem('app.theme', 'midnight');
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(document.documentElement.style.colorScheme).toBe('dark');
  });

  test('light variants set color-scheme: light on html', () => {
    localStorage.setItem('app.theme', 'sunset');
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(document.documentElement.style.colorScheme).toBe('light');
  });
});
