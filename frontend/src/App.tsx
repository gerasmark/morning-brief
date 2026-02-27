import { NavLink, Route, Routes } from 'react-router-dom';
import TodayPage from './pages/TodayPage';
import ArchivePage from './pages/ArchivePage';
import SettingsPage from './pages/SettingsPage';

export default function App() {
  return (
    <div className="app-shell">
      <nav className="top-nav">
        <span className="brand">Πρωινή Ενημέρωση</span>
        <div>
          <NavLink to="/" end>
            Σήμερα
          </NavLink>
          <NavLink to="/archive">Αρχείο</NavLink>
          <NavLink to="/settings">Πηγές</NavLink>
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
