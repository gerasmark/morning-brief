const SOURCE_DOMAIN_BY_NAME: Record<string, string> = {
  'τα νεα': 'tanea.gr',
  ναυτεμπορικη: 'naftemporiki.gr',
  iefimerida: 'iefimerida.gr',
  news247: 'news247.gr',
  newsbomb: 'newsbomb.gr',
  'πρωτο θεμα': 'protothema.gr',
};

function normalizeSourceName(value: string): string {
  return value
    .toLocaleLowerCase('el-GR')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

export function sourceIconUrl(sourceName: string): string | null {
  const normalized = normalizeSourceName(sourceName);
  const domain = SOURCE_DOMAIN_BY_NAME[normalized];
  if (!domain) {
    return null;
  }
  return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=64`;
}
