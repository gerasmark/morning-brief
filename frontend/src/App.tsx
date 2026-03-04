import { useEffect, useState } from 'react';
import { NavLink, Route, Routes } from 'react-router-dom';
import TodayPage from './pages/TodayPage';
import ArchivePage from './pages/ArchivePage';
import SettingsPage from './pages/SettingsPage';

const THEME_STORAGE_KEY = 'morning-brief-theme';
type ThemeMode = 'light' | 'dark';

function resolveInitialTheme(): ThemeMode {
  if (typeof window === 'undefined') {
    return 'light';
  }

  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (stored === 'light' || stored === 'dark') {
    return stored;
  }

  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export default function App() {
  const [theme, setTheme] = useState<ThemeMode>(resolveInitialTheme);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

  return (
    <div className="app-shell">
      <nav className="top-nav">
        <span className="brand">Πρωινή Ενημέρωση</span>
        <div className="top-nav-links">
          <NavLink to="/" end>
            Σήμερα
          </NavLink>
          <NavLink to="/archive">Αρχείο</NavLink>
          <NavLink to="/settings">Πηγές</NavLink>
          <button
            type="button"
            className="theme-toggle"
            onClick={() => setTheme((prev) => (prev === 'light' ? 'dark' : 'light'))}
            title="Εναλλαγή θέματος"
            aria-label="Εναλλαγή θέματος"
          >
            {theme === 'dark' ? 'Φωτεινό' : 'Σκοτεινό'}
          </button>
        </div>
      </nav>

      <main>
        <Routes>
          <Route path="/" element={<TodayPage />} />
          <Route path="/archive" element={<ArchivePage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}
