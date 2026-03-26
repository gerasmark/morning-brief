import { createContext, ReactNode, useContext, useEffect, useState } from 'react';
import { getAuthStatus, startAuthLogin, startAuthLogout } from './api';
import { PUBLIC_HOME_PATH } from './config';
import { AuthStatus } from './types';

const DEFAULT_AUTH_STATUS: AuthStatus = {
  enabled: false,
  configured: true,
  authenticated: false,
  is_admin: false,
  username: null,
  email: null,
  error: null,
};

type AuthContextValue = {
  loading: boolean;
  status: AuthStatus;
  canManage: boolean;
  refresh: () => Promise<void>;
  login: (nextPath?: string) => void;
  logout: (nextPath?: string) => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>(DEFAULT_AUTH_STATUS);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    try {
      const payload = await getAuthStatus();
      setStatus(payload);
    } catch (err) {
      setStatus({
        ...DEFAULT_AUTH_STATUS,
        error: err instanceof Error ? err.message : 'Αποτυχία ελέγχου admin auth.',
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <AuthContext.Provider
      value={{
        loading,
        status,
        canManage: !status.enabled || status.is_admin,
        refresh,
        login: (nextPath?: string) => startAuthLogin(nextPath),
        logout: (nextPath?: string) => startAuthLogout(nextPath || PUBLIC_HOME_PATH),
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used inside AuthProvider');
  }
  return context;
}
