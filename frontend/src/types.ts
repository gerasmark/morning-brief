export type ClusterSource = {
  article_id: string;
  title: string;
  url: string;
  source: string;
  published_at: string | null;
};

export type ClusterCardData = {
  id: string;
  score: number;
  title: string;
  url: string;
  source: string;
  topics: string[];
  is_strike_related: boolean;
  summary_md: string;
  sources: ClusterSource[];
};

export type Briefing = {
  id?: string;
  day: string;
  created_at?: string;
  weather: {
    city?: string;
    day?: string;
    temperature_min?: number;
    temperature_max?: number;
    precipitation_probability?: number;
    wind_speed?: number;
    current_temperature?: number;
    current_apparent_temperature?: number;
    current_precipitation?: number;
    current_wind_speed?: number;
    current_weather_code?: number;
    current_condition?: string;
    observed_at?: string;
    error?: string;
    provider?: string;
    tls_warning?: string | null;
    unavailable?: boolean;
  } | null;
  birthdays: {
    provider?: string;
    day?: string;
    source_url?: string;
    names: string[];
    unavailable?: boolean;
    error?: string | null;
  } | null;
  top_stories: ClusterCardData[];
  strikes: ClusterCardData[];
};

export type SourceItem = {
  id: number;
  name: string;
  base_url: string;
  type: 'rss' | 'sitemap';
  feed_url: string | null;
  sitemap_url: string | null;
  enabled: boolean;
  weight: number;
};

export type BriefingMeta = {
  id: string;
  day: string;
  created_at: string | null;
  top_count: number;
  strike_count: number;
};

export type ArticleItem = {
  id: string;
  title: string;
  url: string;
  snippet: string | null;
  published_at: string | null;
  created_at: string | null;
  source: string;
};
