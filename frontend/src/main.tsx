import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './styles.css';

function normalizeBasename(value?: string): string | undefined {
  if (!value || value === '/') {
    return undefined;
  }

  return `/${value.replace(/^\/+|\/+$/g, '')}`;
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter basename={normalizeBasename(import.meta.env.VITE_APP_BASE_PATH)}>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
