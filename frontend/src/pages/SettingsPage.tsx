import { useEffect, useState } from 'react';
import { getEmailDeliverySettings, listSources, patchSource, updateEmailDeliverySettings } from '../api';
import { EmailDeliverySettings, SourceItem } from '../types';

type SettingsPageProps = {
  adminUsername?: string | null;
  onLogout?: (() => void) | null;
};

function formatSchedulerTime(hour: number, minute: number): string {
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}

function parseRecipientDraft(value: string): string[] {
  return value
    .split(/[\n,;]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatTransportLabel(transport: 'smtp' | 'resend_api'): string {
  return transport === 'resend_api' ? 'Resend API (HTTPS 443)' : 'SMTP';
}

export default function SettingsPage({ adminUsername = null, onLogout = null }: SettingsPageProps) {
  const [sources, setSources] = useState<SourceItem[]>([]);
  const [deliverySettings, setDeliverySettings] = useState<EmailDeliverySettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [recipientDraft, setRecipientDraft] = useState('');
  const [transport, setTransport] = useState<'smtp' | 'resend_api'>('smtp');
  const [autoSendEnabled, setAutoSendEnabled] = useState(false);
  const [deliverySaving, setDeliverySaving] = useState(false);
  const [deliveryStatus, setDeliveryStatus] = useState<string | null>(null);
  const [deliveryError, setDeliveryError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [sourceRows, emailRows] = await Promise.all([listSources(), getEmailDeliverySettings()]);
      setSources(sourceRows);
      setDeliverySettings(emailRows);
      setRecipientDraft(emailRows.recipient_emails.join('\n'));
      setTransport(emailRows.transport);
      setAutoSendEnabled(emailRows.auto_send_enabled);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Αποτυχία φόρτωσης ρυθμίσεων');
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

  const handleSaveDelivery = async () => {
    setDeliverySaving(true);
    setDeliveryStatus(null);
    setDeliveryError(null);
    try {
      const updated = await updateEmailDeliverySettings({
        transport,
        auto_send_enabled: autoSendEnabled,
        recipient_emails: parseRecipientDraft(recipientDraft),
      });
      setDeliverySettings(updated);
      setRecipientDraft(updated.recipient_emails.join('\n'));
      setTransport(updated.transport);
      setAutoSendEnabled(updated.auto_send_enabled);
      setDeliveryStatus(
        `Αποθηκεύτηκαν ${updated.recipient_emails.length} παραλήπτες. Ενεργή σύνδεση: ${formatTransportLabel(updated.transport)}.`
      );
    } catch (err) {
      setDeliveryError(err instanceof Error ? err.message : 'Αποτυχία αποθήκευσης email ρυθμίσεων');
    } finally {
      setDeliverySaving(false);
    }
  };

  const selectedTransportReady = deliverySettings ? deliverySettings.transport_readiness[transport] : false;

  return (
    <section className="page-wrap">
      {onLogout && (
        <div className="toolbar">
          <span className="muted">{adminUsername ? `Admin: ${adminUsername}` : 'Admin πρόσβαση ενεργή'}</span>
          <button className="btn" type="button" onClick={onLogout}>
            Αποσύνδεση
          </button>
        </div>
      )}
      <h1>Πηγές & Ρυθμίσεις</h1>
      <p className="muted">Οι πηγές διαχειρίζονται από εδώ, ενώ η αποστολή email μπορεί να γίνει είτε μέσω SMTP είτε μέσω HTTPS API provider.</p>

      {loading && <p>Φόρτωση...</p>}
      {error && <p className="error-box">{error}</p>}
      {deliveryStatus && <p className="status-box">{deliveryStatus}</p>}
      {deliveryError && <p className="error-box">{deliveryError}</p>}

      {deliverySettings && (
        <section className="settings-panel">
          <h2>Αποστολή Email</h2>
          <div className="settings-meta">
            <p>
              <strong>Αποστολέας:</strong>{' '}
              {deliverySettings.sender_address
                ? `${deliverySettings.sender_name} <${deliverySettings.sender_address}>`
                : 'Μη ρυθμισμένος'}
            </p>
            <p>
              <strong>Scheduler:</strong>{' '}
              {formatSchedulerTime(deliverySettings.schedule_hour, deliverySettings.schedule_minute)}{' '}
              ({deliverySettings.timezone})
            </p>
            <p>
              <strong>Επιλεγμένη σύνδεση:</strong> {formatTransportLabel(transport)}
            </p>
            <p>
              <strong>SMTP:</strong> {deliverySettings.transport_readiness.smtp ? 'Έτοιμο' : 'Δεν έχει ρυθμιστεί ακόμα'}
            </p>
            <p>
              <strong>Resend API:</strong>{' '}
              {deliverySettings.transport_readiness.resend_api ? 'Έτοιμο μέσω HTTPS (443)' : 'Δεν έχει ρυθμιστεί ακόμα'}
            </p>
          </div>

          {!selectedTransportReady && transport === 'smtp' && (
            <p className="error-box">
              Ρύθμισε `SMTP_HOST` και `EMAIL_FROM_ADDRESS` ή `SMTP_USERNAME` στο `backend/.env` για να μπορεί να
              σταλεί email.
            </p>
          )}

          {!selectedTransportReady && transport === 'resend_api' && (
            <p className="error-box">
              Ρύθμισε `RESEND_API_KEY` στο `backend/.env`. Το Resend path χρησιμοποιεί το `RESEND_FROM_ADDRESS`
              και HTTPS στο port `443`, οπότε συνήθως παρακάμπτει το μπλοκάρισμα SMTP.
            </p>
          )}

          <div className="settings-grid">
            <label className="settings-stack">
              <span>Τρόπος σύνδεσης</span>
              <select value={transport} onChange={(e) => setTransport(e.target.value as 'smtp' | 'resend_api')}>
                {deliverySettings.available_transports.map((item) => (
                  <option key={item} value={item}>
                    {formatTransportLabel(item)}
                  </option>
                ))}
              </select>
              <span className="settings-note">
                Το `Resend API` χρησιμοποιεί HTTPS στο port `443`. Το `SMTP` χρησιμοποιεί mail ports όπως `587` ή `465`.
              </span>
              <span className="settings-note">
                Το `Resend` sender εδώ είναι `onboarding@resend.dev`. Σύμφωνα με τα docs του Resend, αυτό είναι για testing
                και μπορεί να στείλει μόνο στο email του λογαριασμού σου, αλλιώς θα πάρεις `403`.
              </span>
            </label>

            <label className="settings-stack">
              <span>Παραλήπτες</span>
              <textarea
                rows={5}
                value={recipientDraft}
                onChange={(e) => setRecipientDraft(e.target.value)}
                placeholder={'name@example.com\nteam@example.com'}
              />
              <span className="settings-note">Ένα email ανά γραμμή ή χωρισμένα με κόμμα.</span>
            </label>

            <label className="settings-toggle">
              <input
                type="checkbox"
                checked={autoSendEnabled}
                onChange={(e) => setAutoSendEnabled(e.target.checked)}
              />
              <span>
                Αυτόμαλη αποστολή μετά το daily briefing στις{' '}
                {formatSchedulerTime(deliverySettings.schedule_hour, deliverySettings.schedule_minute)}
              </span>
            </label>

            <div className="settings-save-row">
              <button className="btn btn-primary" type="button" onClick={handleSaveDelivery} disabled={deliverySaving}>
                {deliverySaving ? 'Αποθήκευση...' : 'Αποθήκευση email ρυθμίσεων'}
              </button>
            </div>
          </div>
        </section>
      )}

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
