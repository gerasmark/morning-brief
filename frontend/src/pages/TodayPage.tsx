import { useEffect, useMemo, useState } from 'react';
import { useAuth } from '../auth';
import ClusterCard from '../components/ClusterCard';
import SourceIcon from '../components/SourceIcon';
import { generateBriefing, getTodayBriefing, listArticles, listSources, runIngestion, sendBriefingEmail } from '../api';
import { ArticleItem, Briefing, WeatherForecastDay } from '../types';
import { formatGreekDateTime, formatRelativeGreekTime } from '../time';

function formatDayMonthYear(dateValue: string): string {
  const parsed = new Date(`${dateValue}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) {
    return dateValue;
  }
  const rendered = new Intl.DateTimeFormat('el-GR', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(parsed);
  return rendered.charAt(0).toUpperCase() + rendered.slice(1);
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

type TodayBriefingCache = {
  day: string;
  briefing: Briefing;
};

let todayBriefingCache: TodayBriefingCache | null = null;

function currentAthensDay(): string {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/Athens',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date());

  let year = '';
  let month = '';
  let day = '';
  for (const part of parts) {
    if (part.type === 'year') {
      year = part.value;
    } else if (part.type === 'month') {
      month = part.value;
    } else if (part.type === 'day') {
      day = part.value;
    }
  }

  if (year && month && day) {
    return `${year}-${month}-${day}`;
  }

  return new Date().toISOString().slice(0, 10);
}

export default function TodayPage() {
  const ALL_PAPERS_LABEL = 'Όλες';
  const { canManage } = useAuth();
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [topSourceFilter, setTopSourceFilter] = useState<string>(ALL_PAPERS_LABEL);
  const [strikeSourceFilter, setStrikeSourceFilter] = useState<string>(ALL_PAPERS_LABEL);
  const [sourceArticles, setSourceArticles] = useState<ArticleItem[]>([]);
  const [sourceArticlesLoading, setSourceArticlesLoading] = useState(false);
  const [sourceArticlesError, setSourceArticlesError] = useState<string | null>(null);
  const [topFilterSources, setTopFilterSources] = useState<string[]>([]);
  const [weatherExpanded, setWeatherExpanded] = useState(false);
  const [deliveryStatus, setDeliveryStatus] = useState<string | null>(null);
  const [deliveryError, setDeliveryError] = useState<string | null>(null);

  const load = async ({ force = false }: { force?: boolean } = {}) => {
    const athensDay = currentAthensDay();
    if (todayBriefingCache && todayBriefingCache.day !== athensDay) {
      todayBriefingCache = null;
    }

    if (!force && todayBriefingCache) {
      setBriefing(todayBriefingCache.briefing);
      setError(null);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const data = await getTodayBriefing();
      todayBriefingCache = { day: data.day, briefing: data };
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
    if (!canManage) {
      setTopFilterSources([]);
      return;
    }

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
  }, [canManage]);

  const handleRunIngestion = async () => {
    setBusyAction('ingestion');
    try {
      await runIngestion();
      await load({ force: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Αποτυχία ingestion');
    } finally {
      setBusyAction(null);
    }
  };

  const handleGenerate = async () => {
    setBusyAction('generate');
    try {
      await generateBriefing();
      await load({ force: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Αποτυχία δημιουργίας briefing');
    } finally {
      setBusyAction(null);
    }
  };

  const handleSendEmail = async () => {
    setBusyAction('email');
    setDeliveryStatus(null);
    setDeliveryError(null);
    try {
      const result = await sendBriefingEmail();
      const transportLabel = result.transport === 'resend_api' ? 'Resend API' : 'SMTP';
      setDeliveryStatus(
        `Το report στάλθηκε σε ${result.recipient_count} παραλήπτες από ${result.sender} μέσω ${transportLabel}.`
      );
    } catch (err) {
      setDeliveryError(err instanceof Error ? err.message : 'Αποτυχία αποστολής email');
    } finally {
      setBusyAction(null);
    }
  };

  const weather = briefing?.weather;
  const birthdays = briefing?.birthdays;
  const quoteOfDay = briefing?.quote_of_day;
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
  const strikeSummaryBullets = useMemo(() => {
    const raw = briefing?.strike_summary_md?.trim();
    if (!raw) {
      return [];
    }
    return raw
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => line.replace(/^[-*•]\s*/, '').trim())
      .filter(Boolean)
      .slice(0, 8);
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
          <h1 className="hero-greeting">
            <span>Καλημέρα</span>
            <em>!</em>
          </h1>
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
            {birthdays?.names?.length ? (
              <div className="birthday-list">
                {birthdays.names.map((name) => (
                  <span key={name} className="birthday-pill">
                    {name}
                  </span>
                ))}
              </div>
            ) : null}
          </div>

          <div className="quote-blob">
            <strong>Απόφθεγμα της Ημέρας</strong>
            {quoteOfDay?.unavailable ? (
              <>
                <span>Μη διαθέσιμο</span>
                {quoteOfDay.error && <small>{quoteOfDay.error}</small>}
              </>
            ) : quoteOfDay?.quote ? (
              <>
                <p className="quote-text">«{quoteOfDay.quote}»</p>
                {quoteOfDay.author && <small className="quote-author">— {quoteOfDay.author}</small>}
              </>
            ) : (
              <span>Δεν βρέθηκε απόφθεγμα.</span>
            )}
          </div>
        </div>
      </header>

      <div className="toolbar">
        <button className="btn" onClick={() => void load({ force: true })} disabled={loading}>
          Ανανέωση
        </button>
        {canManage && (
          <>
            <button className="btn" onClick={handleRunIngestion} disabled={busyAction !== null}>
              {busyAction === 'ingestion' ? 'Τρέχει...' : 'Λήψη ειδήσεων'}
            </button>
            <button className="btn btn-primary" onClick={handleGenerate} disabled={busyAction !== null}>
              {busyAction === 'generate' ? 'Τρέχει...' : 'Δημιουργία σύνοψης'}
            </button>
            <button className="btn" onClick={handleSendEmail} disabled={busyAction !== null || loading}>
              {busyAction === 'email' ? 'Στέλνεται...' : 'Αποστολή email'}
            </button>
          </>
        )}
      </div>

      {loading && <p>Φόρτωση...</p>}
      {error && <p className="error-box">{error}</p>}
      {deliveryStatus && <p className="status-box">{deliveryStatus}</p>}
      {deliveryError && <p className="error-box">{deliveryError}</p>}

      {!loading && !error && briefing && (
        <>
          <section>
            <h2>Με μια ματιά</h2>
            {topSummaryParagraphs.length > 0 && (
              <div className="top-summary-box">
                <p className="top-summary-kicker">Σύνοψη Ημέρας</p>
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
                      Δεν βρέθηκαν άρθρα ακόμα. Πάτησε πρώτα <strong>Λήψη ειδήσεων</strong> και μετά
                      <strong> Δημιουργία σύνοψης</strong>.
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
                  {sourceArticles.map((item) => {
                    const publishedIso = item.published_at ?? item.created_at;
                    const relativePublished = formatRelativeGreekTime(publishedIso);
                    const exactPublished = formatGreekDateTime(publishedIso);
                    return (
                      <article
                        key={item.id}
                        className="story-card"
                        onDoubleClick={() => window.open(item.url, '_blank', 'noopener,noreferrer')}
                        title="Διπλό κλικ για άνοιγμα άρθρου"
                      >
                        <div className="story-head">
                          <span className="source-pill" title={item.source}>
                            <SourceIcon source={item.source} />
                            <span className="source-name">{item.source}</span>
                          </span>
                          {relativePublished && (
                            <span className="time-pill" title={exactPublished || undefined}>
                              {relativePublished}
                            </span>
                          )}
                        </div>
                        <h3>{item.title}</h3>
                      </article>
                    );
                  })}
                </>
              )}
            </div>
          </section>

          <section>
            <h2>Απεργίες / Μετακινήσεις</h2>
            {strikeSummaryBullets.length > 0 && (
              <div className="strike-summary-box">
                <p className="strike-summary-kicker">Τι Να Προσέξεις Σήμερα</p>
                <ul>
                  {strikeSummaryBullets.map((bullet, idx) => (
                    <li key={`strike-summary-${idx}`}>{bullet}</li>
                  ))}
                </ul>
              </div>
            )}
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
