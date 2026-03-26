export function normalizeBasePath(value?: string): string {
  if (!value || value === '/') {
    return '/';
  }

  return `/${value.replace(/^\/+|\/+$/g, '')}`;
}

export function normalizeRoutePath(value?: string): string {
  const trimmed = (value || '/ops-admin').replace(/^\/+|\/+$/g, '');
  return trimmed || 'ops-admin';
}

export const APP_BASE_PATH = normalizeBasePath(import.meta.env.VITE_APP_BASE_PATH);
export const ROUTER_BASENAME = APP_BASE_PATH === '/' ? undefined : APP_BASE_PATH;
export const ADMIN_ENTRY_ROUTE = normalizeRoutePath(import.meta.env.VITE_ADMIN_ENTRY_PATH);
export const PUBLIC_HOME_PATH = APP_BASE_PATH === '/' ? '/' : `${APP_BASE_PATH}/`;
