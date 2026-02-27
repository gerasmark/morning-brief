import { useEffect, useState } from 'react';
import ClusterCard from '../components/ClusterCard';
import { getBriefingByDay, listBriefings } from '../api';
import { Briefing, BriefingMeta } from '../types';

export default function ArchivePage() {
  const [day, setDay] = useState(new Date().toISOString().slice(0, 10));
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [days, setDays] = useState<BriefingMeta[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadDays = async () => {
      try {
        const rows = await listBriefings();
        setDays(rows);
      } catch {
        setDays([]);
      }
    };
    void loadDays();
  }, []);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getBriefingByDay(day);
      setBriefing(data);
    } catch (err) {
      setBriefing(null);
      setError(err instanceof Error ? err.message : 'Δεν βρέθηκε briefing για τη μέρα');
    } finally {
      setLoading(false);
    }
  };

  const openDay = async (selectedDay: string) => {
    setDay(selectedDay);
    setLoading(true);
    setError(null);
    try {
      const data = await getBriefingByDay(selectedDay);
      setBriefing(data);
    } catch {
      setBriefing(null);
      setError('Δεν βρέθηκε briefing για τη μέρα');
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="page-wrap">
      <h1>Αρχείο Briefings</h1>
      <div className="toolbar">
        <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
        <button className="btn btn-primary" onClick={() => void load()} disabled={loading}>
          {loading ? 'Φόρτωση...' : 'Φόρτωση ημέρας'}
        </button>
      </div>

      {days.length > 0 && (
        <div className="archive-list">
          {days.map((item) => (
            <button
              key={item.id}
              type="button"
              className="archive-item"
              onClick={() => void openDay(item.day)}
            >
              <strong>{item.day}</strong>
              <span>{item.top_count} top • {item.strike_count} strikes</span>
            </button>
          ))}
        </div>
      )}

      {error && <p className="error-box">{error}</p>}

      {briefing && (
        <div className="cards-grid">
          {briefing.top_stories.map((item) => (
            <ClusterCard key={item.id} item={item} />
          ))}
        </div>
      )}
    </section>
  );
}
