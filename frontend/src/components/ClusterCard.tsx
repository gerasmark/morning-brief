import type { MouseEvent } from 'react';
import { useMemo, useState } from 'react';
import { ClusterCardData } from '../types';
import { formatGreekDateTime, formatRelativeGreekTime } from '../time';
import SourceIcon from './SourceIcon';

type Props = {
  item: ClusterCardData;
  summaryMode?: 'list' | 'plain' | 'hidden';
  showSourcesToggle?: boolean;
  variant?: 'default' | 'strike';
};

function summaryLines(summary: string): string[] {
  return summary
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
}

export default function ClusterCard({
  item,
  summaryMode = 'hidden',
  showSourcesToggle = false,
  variant = 'default',
}: Props) {
  const [open, setOpen] = useState(false);
  const lines = useMemo(() => summaryLines(item.summary_md), [item.summary_md]);
  const latestPublishedAt = useMemo(() => {
    let latestIso: string | null = null;
    let latestMs = -Infinity;
    for (const source of item.sources) {
      if (!source.published_at) {
        continue;
      }
      const parsed = new Date(source.published_at);
      const parsedMs = parsed.getTime();
      if (Number.isNaN(parsedMs)) {
        continue;
      }
      if (parsedMs > latestMs) {
        latestMs = parsedMs;
        latestIso = source.published_at;
      }
    }
    return latestIso;
  }, [item.sources]);
  const relativePublished = useMemo(() => formatRelativeGreekTime(latestPublishedAt), [latestPublishedAt]);
  const exactPublished = useMemo(() => formatGreekDateTime(latestPublishedAt), [latestPublishedAt]);
  const handleDoubleClick = (event: MouseEvent<HTMLElement>) => {
    const target = event.target as HTMLElement | null;
    if (target?.closest('a, button, input, textarea, select, label')) {
      return;
    }
    window.open(item.url, '_blank', 'noopener,noreferrer');
  };

  return (
    <article
      className={`story-card ${variant === 'strike' ? 'strike-card' : ''}`}
      onDoubleClick={handleDoubleClick}
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

      {summaryMode === 'hidden' ? null : summaryMode === 'list' ? (
        <ul>
          {lines.slice(0, 6).map((line, idx) => (
            <li key={`${item.id}-${idx}`}>{line.replace(/^-\s*/, '')}</li>
          ))}
        </ul>
      ) : (
        <div className="plain-summary">
          {lines.slice(0, 6).map((line, idx) => (
            <p key={`${item.id}-${idx}`}>{line.replace(/^-\s*/, '')}</p>
          ))}
        </div>
      )}

      {showSourcesToggle && (
        <div className="story-actions">
          <button className="btn" onClick={() => setOpen((prev) => !prev)}>
            {open ? 'Απόκρυψη πηγών' : 'Δείτε όλες τις πηγές'}
          </button>
        </div>
      )}

      {showSourcesToggle && open && (
        <div className="sources-list">
          {item.sources.map((source) => (
            <a key={source.article_id} href={source.url} target="_blank" rel="noreferrer">
              <span className="source-inline">
                <SourceIcon source={source.source} />
                <strong>{source.source}</strong>
              </span>
              : {source.title}
            </a>
          ))}
        </div>
      )}
    </article>
  );
}
