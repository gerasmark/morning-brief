import { useEffect, useMemo, useState } from 'react';
import ClusterCard from '../components/ClusterCard';
import { generateBriefing, getTodayBriefing, listArticles, listSources, runIngestion } from '../api';
import { ArticleItem, Briefing, WeatherForecastDay } from '../types';

function formatDayMonthYear(dateValue: string): string {
  const [year, month, day] = dateValue.split('-');
  if (!year || !month || !day || year.length !== 4) {
    return dateValue;
  }
  return `${day}-${month}-${year}`;
}

function formatShortWeekday(dateValue: string): string {
  const parsed = new Date(`${dateValue}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) {
    return dateValue;
  }
  return new Intl.DateTimeFormat('el-GR', { weekday: 'short' }).format(parsed).replace('.', '');
}

function weatherIconForCode(code?: number | null): string {
  if (code === undefined || code === null) {
    return '🌤️';
  }
  if (code === 0) {
    return '☀️';
  }
  if (code <= 2) {
    return '🌤️';
  }
  if (code === 3) {
    return '☁️';
  }
  if (code === 45 || code === 48) {
    return '🌫️';
  }
  if ((code >= 51 && code <= 67) || (code >= 80 && code <= 82)) {
    return '🌧️';
  }
  if (code >= 71 && code <= 77) {
    return '❄️';
  }
  if (code === 85 || code === 86) {
    return '🌨️';
  }
  if (code >= 95) {
    return '⛈️';
  }
  return '🌥️';
}

export default function TodayPage() {
  const ALL_PAPERS_LABEL = 'Όλες';
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [topSourceFilter, setTopSourceFilter] = useState<string>(ALL_PAPERS_LABEL);
  const [strikeSourceFilter, setStrikeSourceFilter] = useState<string>(ALL_PAPERS_LABEL);
  const [sourceArticles, setSourceArticles] = useState<ArticleItem[]>([]);
  const [sourceArticlesLoading, setSourceArticlesLoading] = useState(false);
  const [sourceArticlesError, setSourceArticlesError] = useState<string | null>(null);
  const [topFilterSources, setTopFilterSources] = useState<string[]>([]);
  const [weatherExpanded, setWeatherExpanded] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getTodayBriefing();
      setBriefing(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Αποτυχία φόρτωσης briefing');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    let cancelled = false;
    void listSources()
      .then((rows) => {
        if (cancelled) {
          return;
        }
        const names = rows
          .filter((row) => row.enabled)
          .map((row) => row.name)
          .sort((a, b) => a.localeCompare(b));
        setTopFilterSources(names);
      })
      .catch(() => {
        if (cancelled) {
          return;
        }
        setTopFilterSources([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleRunIngestion = async () => {
    setBusyAction('ingestion');
    setStatusMessage(null);
    try {
      const result = await runIngestion();
      if (result.failed_sources.length > 0) {
        setStatusMessage(
          `Ingestion: fetched ${result.fetched}, inserted ${result.inserted}. Αποτυχία σε: ${result.failed_sources.join(', ')}`
        );
      } else {
        setStatusMessage(`Ingestion: fetched ${result.fetched}, inserted ${result.inserted}.`);
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Αποτυχία ingestion');
    } finally {
      setBusyAction(null);
    }
  };

  const handleGenerate = async () => {
    setBusyAction('generate');
    setStatusMessage(null);
    try {
      const result = await generateBriefing();
      const topCount = result.briefing?.top_stories?.length ?? 0;
      setStatusMessage(`Briefing δημιουργήθηκε: ${topCount} θέματα.`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Αποτυχία δημιουργίας briefing');
    } finally {
      setBusyAction(null);
    }
  };

  const weather = briefing?.weather;
  const birthdays = briefing?.birthdays;
  const displayDate = formatDayMonthYear(briefing?.day ?? new Date().toISOString().slice(0, 10));
  const forecastDays: WeatherForecastDay[] = useMemo(() => {
    const forecast = weather?.forecast ?? [];
    if (forecast.length > 1) {
      return forecast.slice(1, 4);
    }
    return forecast.slice(0, 3);
  }, [weather]);
  const canExpandWeather = forecastDays.length > 0;
  const topSummaryParagraphs = useMemo(() => {
    const raw = briefing?.top_summary_md?.trim();
    if (!raw) {
      return [];
    }
    return raw
      .split(/\n\s*\n+/)
      .map((paragraph) => paragraph.trim())
      .filter(Boolean)
      .slice(0, 3);
  }, [briefing]);
  const topSources = useMemo(() => {
    if (topFilterSources.length > 0) {
      return topFilterSources;
    }
    if (!briefing) {
      return [];
    }
    return Array.from(new Set(briefing.top_stories.map((item) => item.source))).sort((a, b) => a.localeCompare(b));
  }, [briefing, topFilterSources]);

  useEffect(() => {
    if (topSourceFilter !== ALL_PAPERS_LABEL && !topSources.includes(topSourceFilter)) {
      setTopSourceFilter(ALL_PAPERS_LABEL);
    }
  }, [topSourceFilter, topSources]);

  const filteredTopStories = useMemo(() => {
    if (!briefing) {
      return [];
    }
    if (topSourceFilter === ALL_PAPERS_LABEL) {
      return briefing.top_stories;
    }
    return briefing.top_stories.filter((item) => item.source === topSourceFilter);
  }, [briefing, topSourceFilter]);

  useEffect(() => {
    if (topSourceFilter === ALL_PAPERS_LABEL) {
      setSourceArticles([]);
      setSourceArticlesError(null);
      setSourceArticlesLoading(false);
      return;
    }

    let cancelled = false;
    setSourceArticlesLoading(true);
    setSourceArticlesError(null);
    void listArticles(topSourceFilter, 15)
      .then((rows) => {
        if (cancelled) {
          return;
        }
        setSourceArticles(rows);
      })
      .catch((err) => {
        if (cancelled) {
          return;
        }
        setSourceArticles([]);
        setSourceArticlesError(err instanceof Error ? err.message : 'Αποτυχία φόρτωσης άρθρων.');
      })
      .finally(() => {
        if (cancelled) {
          return;
        }
        setSourceArticlesLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [topSourceFilter]);

  const strikeSources = useMemo(() => {
    if (!briefing) {
      return [];
    }
    return Array.from(new Set(briefing.strikes.map((item) => item.source))).sort((a, b) => a.localeCompare(b));
  }, [briefing]);

  useEffect(() => {
    if (strikeSourceFilter !== ALL_PAPERS_LABEL && !strikeSources.includes(strikeSourceFilter)) {
      setStrikeSourceFilter(ALL_PAPERS_LABEL);
    }
  }, [strikeSourceFilter, strikeSources]);

  const filteredStrikes = useMemo(() => {
    if (!briefing) {
      return [];
    }
    if (strikeSourceFilter === ALL_PAPERS_LABEL) {
      return briefing.strikes;
    }
    return briefing.strikes.filter((item) => item.source === strikeSourceFilter);
  }, [briefing, strikeSourceFilter]);

  return (
    <section className="page-wrap">
      <header className="hero">
        <div>
          <p className="overline">Προσωπικό Daily Digest</p>
          <h1>Καλημέρα!</h1>
          <p>{displayDate}</p>
        </div>

        <div className="hero-side">
          <div className={`weather-chip ${weatherExpanded ? 'expanded' : ''}`}>
            {weather?.unavailable ? (
              <>
                <span>Καιρός μη διαθέσιμος</span>
                {weather.error && <small>{weather.error}</small>}
              </>
            ) : (
              <>
                <button
                  className="weather-chip-toggle"
                  type="button"
                  onClick={() => {
                    if (canExpandWeather) {
                      setWeatherExpanded((prev) => !prev);
                    }
                  }}
                  aria-expanded={weatherExpanded}
                  aria-label="Εμφάνιση πρόγνωσης επόμενων ημερών"
                >
                  <span className="weather-main-icon" aria-hidden="true">
                    {weatherIconForCode(weather?.current_weather_code)}
                  </span>
                  <span className="weather-main-content">
                    <strong>{weather?.city || 'Καιρός'}</strong>
                    <span>
                      Τώρα: {weather?.current_temperature ?? '-'}°
                      {weather?.current_condition ? ` • ${weather.current_condition}` : ''}
                    </span>
                    <span>
                      {weather?.temperature_min ?? '-'}° / {weather?.temperature_max ?? '-'}°
                    </span>
                    <small>Βροχή {weather?.precipitation_probability ?? '-'}% • Άνεμος {weather?.wind_speed ?? '-'} km/h</small>
                    {weather?.tls_warning && <small>{weather.tls_warning}</small>}
                  </span>
                  {canExpandWeather && (
                    <span className={`weather-expand-indicator ${weatherExpanded ? 'open' : ''}`} aria-hidden="true">
                      ▾
                    </span>
                  )}
                </button>
                {weatherExpanded && canExpandWeather && (
                  <div className="weather-forecast">
                    {forecastDays.map((forecast) => (
                      <div key={forecast.day} className="weather-forecast-day">
                        <span className="weather-forecast-label">{formatShortWeekday(forecast.day)}</span>
                        <span className="weather-forecast-icon" aria-hidden="true">
                          {weatherIconForCode(forecast.weather_code)}
                        </span>
                        <span className="weather-forecast-temp">
                          {forecast.temperature_max ?? '-'}° <small>{forecast.temperature_min ?? '-'}°</small>
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>

          <div className="birthday-blob">
            <strong>Ποιοι γιορτάζουν σήμερα</strong>
            {birthdays?.unavailable ? (
              <>
                <span>Μη διαθέσιμο</span>
                {birthdays.error && <small>{birthdays.error}</small>}
              </>
            ) : birthdays?.names?.length ? (
              <div className="birthday-list">
                {birthdays.names.map((name) => (
                  <span key={name} className="birthday-pill">
                    {name}
                  </span>
                ))}
              </div>
            ) : (
              <span>Δεν βρέθηκαν ονόματα.</span>
            )}
          </div>
        </div>
      </header>

      <div className="toolbar">
        <button className="btn" onClick={() => void load()} disabled={loading}>
          Ανανέωση
        </button>
        <button className="btn" onClick={handleRunIngestion} disabled={busyAction !== null}>
          {busyAction === 'ingestion' ? 'Τρέχει...' : 'Run ingestion'}
        </button>
        <button className="btn btn-primary" onClick={handleGenerate} disabled={busyAction !== null}>
          {busyAction === 'generate' ? 'Τρέχει...' : 'Generate briefing'}
        </button>
      </div>

      {loading && <p>Φόρτωση...</p>}
      {error && <p className="error-box">{error}</p>}
      {statusMessage && <p className="status-box">{statusMessage}</p>}

      {!loading && !error && briefing && (
        <>
          <section>
            <h2>Με μια ματιά</h2>
            {topSummaryParagraphs.length > 0 && (
              <div className="top-summary-box">
                {topSummaryParagraphs.map((paragraph, idx) => (
                  <p key={`top-summary-${idx}`}>{paragraph}</p>
                ))}
              </div>
            )}
            {topSources.length > 0 && (
              <div className="strike-filters">
                <button
                  className={`strike-filter ${topSourceFilter === ALL_PAPERS_LABEL ? 'active' : ''}`}
                  onClick={() => setTopSourceFilter(ALL_PAPERS_LABEL)}
                  type="button"
                >
                  {ALL_PAPERS_LABEL}
                </button>
                {topSources.map((source) => (
                  <button
                    key={source}
                    className={`strike-filter ${topSourceFilter === source ? 'active' : ''}`}
                    onClick={() => setTopSourceFilter(source)}
                    type="button"
                  >
                    {source}
                  </button>
                ))}
              </div>
            )}
            <div className="cards-grid">
              {topSourceFilter === ALL_PAPERS_LABEL ? (
                <>
                  {filteredTopStories.length === 0 && (
                    <p>
                      Δεν βρέθηκαν άρθρα ακόμα. Πάτησε πρώτα <strong>Run ingestion</strong> και μετά
                      <strong> Generate briefing</strong>.
                    </p>
                  )}
                  {filteredTopStories.map((item) => (
                    <ClusterCard key={item.id} item={item} />
                  ))}
                </>
              ) : (
                <>
                  {sourceArticlesLoading && <p>Φόρτωση άρθρων...</p>}
                  {sourceArticlesError && <p className="error-box">{sourceArticlesError}</p>}
                  {!sourceArticlesLoading && !sourceArticlesError && sourceArticles.length === 0 && (
                    <p>Δεν βρέθηκαν εισαγμένα άρθρα για {topSourceFilter}.</p>
                  )}
                  {sourceArticles.map((item) => (
                    <article
                      key={item.id}
                      className="story-card"
                      onDoubleClick={() => window.open(item.url, '_blank', 'noopener,noreferrer')}
                      title="Διπλό κλικ για άνοιγμα άρθρου"
                    >
                      <h3>{item.title}</h3>
                    </article>
                  ))}
                </>
              )}
            </div>
          </section>

          <section>
            <h2>Απεργίες / Μετακινήσεις</h2>
            {strikeSources.length > 0 && (
              <div className="strike-filters">
                <button
                  className={`strike-filter ${strikeSourceFilter === ALL_PAPERS_LABEL ? 'active' : ''}`}
                  onClick={() => setStrikeSourceFilter(ALL_PAPERS_LABEL)}
                  type="button"
                >
                  {ALL_PAPERS_LABEL}
                </button>
                {strikeSources.map((source) => (
                  <button
                    key={source}
                    className={`strike-filter ${strikeSourceFilter === source ? 'active' : ''}`}
                    onClick={() => setStrikeSourceFilter(source)}
                    type="button"
                  >
                    {source}
                  </button>
                ))}
              </div>
            )}
            <div className="cards-grid">
              {filteredStrikes.length === 0 && <p>Δεν βρέθηκαν σχετικά θέματα.</p>}
              {filteredStrikes.map((item) => (
                <ClusterCard
                  key={item.id}
                  item={item}
                  summaryMode="hidden"
                  showScore={false}
                  showSourcesToggle={false}
                  variant="strike"
                />
              ))}
            </div>
          </section>
        </>
      )}
    </section>
  );
}
