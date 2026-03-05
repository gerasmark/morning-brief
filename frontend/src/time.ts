const ATHENS_TZ = 'Europe/Athens';
const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

const dateTimeFormatter = new Intl.DateTimeFormat('el-GR', {
  timeZone: ATHENS_TZ,
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
});

function athensDayNumber(value: Date): number {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: ATHENS_TZ,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(value);

  let year = 0;
  let month = 0;
  let day = 0;

  for (const part of parts) {
    if (part.type === 'year') {
      year = Number(part.value);
    } else if (part.type === 'month') {
      month = Number(part.value);
    } else if (part.type === 'day') {
      day = Number(part.value);
    }
  }

  if (!year || !month || !day) {
    return Math.floor(value.getTime() / DAY_MS);
  }

  return Math.floor(Date.UTC(year, month - 1, day) / DAY_MS);
}

export function formatRelativeGreekTime(isoValue: string | null | undefined, now = new Date()): string {
  if (!isoValue) {
    return '';
  }

  const published = new Date(isoValue);
  if (Number.isNaN(published.getTime())) {
    return '';
  }

  let deltaMs = now.getTime() - published.getTime();
  if (deltaMs < 0) {
    deltaMs = 0;
  }

  if (deltaMs < MINUTE_MS) {
    return 'μόλις τώρα';
  }

  if (deltaMs < HOUR_MS) {
    const minutes = Math.floor(deltaMs / MINUTE_MS);
    if (minutes === 1) {
      return '1 λεπτό πριν';
    }
    return `${minutes} λεπτά πριν`;
  }

  if (deltaMs < DAY_MS) {
    const hours = Math.floor(deltaMs / HOUR_MS);
    if (hours === 1) {
      return 'μια ώρα πριν';
    }
    return `${hours} ώρες πριν`;
  }

  const dayDiff = athensDayNumber(now) - athensDayNumber(published);
  if (dayDiff === 1) {
    return 'χθες';
  }
  if (dayDiff === 2) {
    return 'προχθές';
  }
  if (dayDiff > 0 && dayDiff <= 6) {
    return `${dayDiff} ημέρες πριν`;
  }

  return dateTimeFormatter.format(published);
}

export function formatGreekDateTime(isoValue: string | null | undefined): string {
  if (!isoValue) {
    return '';
  }
  const parsed = new Date(isoValue);
  if (Number.isNaN(parsed.getTime())) {
    return '';
  }
  return dateTimeFormatter.format(parsed);
}
