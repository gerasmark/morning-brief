import { APP_BASE_PATH } from './config';
import { ArticleItem, AuthStatus, Briefing, BriefingMeta, EmailDeliveryResult, EmailDeliverySettings, SourceItem } from './types';

const API_BASE = resolveApiBase();

function normalizeApiBase(value: string): string {
  const trimmed = value.replace(/\/+$/g, '');
  return trimmed || '/';
}

function resolveApiBase(): string {
  const explicit = import.meta.env.VITE_API_BASE;
  if (explicit) {
    return normalizeApiBase(explicit);
  }

  const appBasePath = APP_BASE_PATH;
  if (appBasePath === '/') {
    return '/api';
  }

  return `${appBasePath}/api`;
}

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

function buildAuthRedirectUrl(path: string, nextPath?: string): string {
  const absolute = new URL(`${API_BASE}${path}`, window.location.origin);
  if (nextPath) {
    absolute.searchParams.set('next', nextPath);
  }
  return absolute.toString();
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
  source_stats: Array<{
    source: string;
    status: string;
    fetched: number;
    inserted: number;
    http_requests: number;
    http_non_200: number;
    http_statuses: Record<string, number>;
    total_articles: number;
    last_24h_articles: number;
  }>;
}> {
  return fetchJson('/admin/run-ingestion', { method: 'POST' });
}

export async function generateBriefing(day?: string): Promise<{ status: string; briefing: Briefing }> {
  return fetchJson('/admin/generate-briefing', {
    method: 'POST',
    body: JSON.stringify(day ? { day } : {}),
  });
}

export async function sendBriefingEmail(day?: string, recipientEmails?: string[]): Promise<EmailDeliveryResult> {
  const payload: { day?: string; recipient_emails?: string[] } = {};
  if (day) {
    payload.day = day;
  }
  if (recipientEmails && recipientEmails.length > 0) {
    payload.recipient_emails = recipientEmails;
  }
  return fetchJson('/admin/send-briefing-email', {
    method: 'POST',
    body: JSON.stringify(payload),
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

export async function getEmailDeliverySettings(): Promise<EmailDeliverySettings> {
  return fetchJson<EmailDeliverySettings>('/delivery/email-settings');
}

export async function updateEmailDeliverySettings(payload: {
  transport: 'smtp' | 'resend_api';
  auto_send_enabled: boolean;
  recipient_emails: string[];
}): Promise<EmailDeliverySettings> {
  return fetchJson<EmailDeliverySettings>('/delivery/email-settings', {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function getAuthStatus(): Promise<AuthStatus> {
  return fetchJson<AuthStatus>('/auth/me');
}

export function startAuthLogin(nextPath?: string): void {
  window.location.assign(buildAuthRedirectUrl('/auth/login', nextPath));
}

export function startAuthLogout(nextPath?: string): void {
  window.location.assign(buildAuthRedirectUrl('/auth/logout', nextPath));
}
