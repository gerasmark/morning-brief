import { ArticleItem, Briefing, BriefingMeta, SourceItem } from './types';

const API_BASE = import.meta.env.VITE_API_BASE || '/api';

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  const rawText = await response.text();

  let parsed: unknown = null;
  if (rawText) {
    try {
      parsed = JSON.parse(rawText);
    } catch {
      parsed = null;
    }
  }

  if (!response.ok) {
    if (typeof parsed === 'object' && parsed !== null && 'detail' in parsed) {
      throw new Error(String((parsed as { detail: unknown }).detail));
    }
    const fallback = rawText.trim().slice(0, 180);
    throw new Error(fallback || `Request failed: ${response.status}`);
  }

  if (parsed === null) {
    const preview = rawText.trim().slice(0, 180);
    throw new Error(`API returned non-JSON response. ${preview}`);
  }

  return parsed as T;
}

export async function getTodayBriefing(): Promise<Briefing> {
  return fetchJson<Briefing>('/briefings/today');
}

export async function getBriefingByDay(day: string): Promise<Briefing> {
  return fetchJson<Briefing>(`/briefings/${day}`);
}

export async function listBriefings(): Promise<BriefingMeta[]> {
  return fetchJson<BriefingMeta[]>('/briefings');
}

export async function runIngestion(): Promise<{
  status: string;
  fetched: number;
  inserted: number;
  failed_sources: string[];
}> {
  return fetchJson('/admin/run-ingestion', { method: 'POST' });
}

export async function generateBriefing(day?: string): Promise<{ status: string; briefing: Briefing }> {
  return fetchJson('/admin/generate-briefing', {
    method: 'POST',
    body: JSON.stringify(day ? { day } : {}),
  });
}

export async function listSources(): Promise<SourceItem[]> {
  return fetchJson<SourceItem[]>('/sources');
}

export async function patchSource(sourceId: number, payload: Partial<SourceItem>): Promise<SourceItem> {
  return fetchJson<SourceItem>(`/sources/${sourceId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export async function listArticles(source?: string, limit = 2000): Promise<ArticleItem[]> {
  const params = new URLSearchParams();
  params.set('limit', String(limit));
  if (source) {
    params.set('source', source);
  }
  return fetchJson<ArticleItem[]>(`/articles?${params.toString()}`);
}
