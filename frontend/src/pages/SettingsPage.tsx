import { useEffect, useState } from 'react';
import { listSources, patchSource } from '../api';
import { SourceItem } from '../types';

export default function SettingsPage() {
  const [sources, setSources] = useState<SourceItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await listSources();
      setSources(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Αποτυχία φόρτωσης πηγών');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const updateSource = async (sourceId: number, payload: Partial<SourceItem>) => {
    const updated = await patchSource(sourceId, payload);
    setSources((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
  };

  return (
    <section className="page-wrap">
      <h1>Πηγές & Ρυθμίσεις</h1>
      <p className="muted">Τοποθεσία και ώρα scheduler ρυθμίζονται από env vars στο backend για το MVP.</p>

      {loading && <p>Φόρτωση...</p>}
      {error && <p className="error-box">{error}</p>}

      <div className="sources-grid">
        {sources.map((source) => (
          <div key={source.id} className="source-row">
            <div>
              <strong>{source.name}</strong>
              <p>{source.base_url}</p>
            </div>
            <label>
              Ενεργό
              <input
                type="checkbox"
                checked={source.enabled}
                onChange={(e) => void updateSource(source.id, { enabled: e.target.checked })}
              />
            </label>
            <label>
              Βάρος {source.weight.toFixed(1)}
              <input
                type="range"
                min={0}
                max={2}
                step={0.1}
                value={source.weight}
                onChange={(e) => void updateSource(source.id, { weight: Number(e.target.value) })}
              />
            </label>
          </div>
        ))}
      </div>
    </section>
  );
}
