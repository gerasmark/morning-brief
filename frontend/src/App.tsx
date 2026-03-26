import { useEffect, useState } from 'react';
import { Navigate, NavLink, Route, Routes } from 'react-router-dom';
import { useAuth } from './auth';
import { ADMIN_ENTRY_ROUTE, PUBLIC_HOME_PATH } from './config';
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

function HiddenAdminRoute() {
  const { loading, status, login, logout } = useAuth();

  useEffect(() => {
    if (loading || !status.enabled || !status.configured || status.authenticated) {
      return;
    }

    const nextPath = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    login(nextPath);
  }, [loading, login, status.authenticated, status.configured, status.enabled]);

  if (loading) {
    return (
      <section className="page-wrap">
        <p>Έλεγχος admin πρόσβασης...</p>
      </section>
    );
  }

  if (status.enabled && !status.configured) {
    return (
      <section className="page-wrap">
        <h1>Admin μη διαθέσιμο</h1>
        <p className="error-box">{status.error || 'Το Keycloak auth δεν έχει ρυθμιστεί σωστά ακόμα.'}</p>
      </section>
    );
  }

  if (status.enabled && !status.authenticated) {
    return (
      <section className="page-wrap">
        <p>Ανακατεύθυνση προς Keycloak...</p>
      </section>
    );
  }

  if (status.enabled && !status.is_admin) {
    return (
      <section className="page-wrap">
        <h1>403</h1>
        <p className="error-box">Ο λογαριασμός σου δεν έχει δικαίωμα πρόσβασης σε αυτή τη σελίδα.</p>
      </section>
    );
  }

  return (
    <SettingsPage
      adminUsername={status.username ?? null}
      onLogout={status.enabled ? () => logout(PUBLIC_HOME_PATH) : null}
    />
  );
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
          <Route path="settings" element={<Navigate to="/" replace />} />
          <Route path={`${ADMIN_ENTRY_ROUTE}/*`} element={<HiddenAdminRoute />} />
        </Routes>
      </main>
    </div>
  );
}
