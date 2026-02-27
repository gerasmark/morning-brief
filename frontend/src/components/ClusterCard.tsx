import type { MouseEvent } from 'react';
import { useMemo, useState } from 'react';
import { ClusterCardData } from '../types';

type Props = {
  item: ClusterCardData;
  summaryMode?: 'list' | 'plain' | 'hidden';
  showScore?: boolean;
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
  showScore = true,
  showSourcesToggle = false,
  variant = 'default',
}: Props) {
  const [open, setOpen] = useState(false);
  const lines = useMemo(() => summaryLines(item.summary_md), [item.summary_md]);
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
        <span className="source-pill" title={item.source}>{item.source}</span>
        {showScore && <span className="score-pill">Score {item.score.toFixed(2)}</span>}
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
              <strong>{source.source}</strong>: {source.title}
            </a>
          ))}
        </div>
      )}
    </article>
  );
}
