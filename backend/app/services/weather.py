from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from app.config import Settings

WEATHER_CODE_LABELS = {
    0: "Αίθριος",
    1: "Κυρίως αίθριος",
    2: "Μερική συννεφιά",
    3: "Συννεφιά",
    45: "Ομίχλη",
    48: "Πάχνη",
    51: "Ελαφρά ψιχάλα",
    53: "Μέτρια ψιχάλα",
    55: "Ισχυρή ψιχάλα",
    61: "Ελαφρά βροχή",
    63: "Μέτρια βροχή",
    65: "Ισχυρή βροχή",
    66: "Παγωμένη βροχή",
    67: "Ισχυρή παγωμένη βροχή",
    71: "Ασθενές χιόνι",
    73: "Μέτριο χιόνι",
    75: "Ισχυρή χιονόπτωση",
    77: "Χιονοκόκκοι",
    80: "Μπόρες ασθενείς",
    81: "Μπόρες μέτριες",
    82: "Μπόρες ισχυρές",
    85: "Χιονομπόρες ασθενείς",
    86: "Χιονομπόρες ισχυρές",
    95: "Καταιγίδα",
    96: "Καταιγίδα με χαλάζι",
    99: "Ισχυρή καταιγίδα με χαλάζι",
}


class WeatherService:
    async def fetch_today(self, settings: Settings, day: date) -> dict:
        base_params = {
            "latitude": settings.weather_lat,
            "longitude": settings.weather_lon,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max,weather_code",
            "timezone": settings.timezone,
            "forecast_days": 4,
        }
        url = "https://api.open-meteo.com/v1/forecast"
        payload: dict[str, Any] | None = None
        last_error: Exception | None = None
        tls_warning: str | None = None

        async with httpx.AsyncClient(verify=_verify_config(settings), trust_env=True) as client:
            try:
                payload = await _fetch_payload(
                    client,
                    url,
                    {
                        **base_params,
                        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation",
                    },
                )
            except Exception as exc:
                last_error = exc
                try:
                    payload = await _fetch_payload(
                        client,
                        url,
                        {
                            **base_params,
                            "current_weather": "true",
                        },
                    )
                except Exception as legacy_exc:
                    last_error = legacy_exc

        if payload is None and settings.weather_allow_insecure_fallback and _is_tls_error(last_error):
            try:
                async with httpx.AsyncClient(verify=False, trust_env=True) as insecure_client:
                    payload = await _fetch_payload(
                        insecure_client,
                        url,
                        {
                            **base_params,
                            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation",
                        },
                    )
                tls_warning = "Weather fetched with SSL verification disabled fallback."
            except Exception as insecure_exc:
                last_error = insecure_exc

        if payload is None:
            return {
                "provider": "open-meteo",
                "city": settings.weather_city_name,
                "day": str(day),
                "unavailable": True,
                "error": _error_hint(last_error),
            }

        daily = payload.get("daily", {})
        current = payload.get("current") or payload.get("current_weather", {})
        dates = daily.get("time", [])
        idx = 0
        day_str = str(day)
        if day_str in dates:
            idx = dates.index(day_str)

        weather_code = current.get("weather_code", current.get("weathercode"))
        weather_label = WEATHER_CODE_LABELS.get(weather_code, "Άγνωστη κατάσταση")
        forecast = _build_forecast(daily, idx, 4)

        return {
            "provider": "open-meteo",
            "city": settings.weather_city_name,
            "day": day_str,
            "temperature_min": _pick(daily.get("temperature_2m_min", []), idx),
            "temperature_max": _pick(daily.get("temperature_2m_max", []), idx),
            "precipitation_probability": _pick(daily.get("precipitation_probability_max", []), idx),
            "wind_speed": _pick(daily.get("wind_speed_10m_max", []), idx),
            "current_temperature": current.get("temperature_2m", current.get("temperature")),
            "current_apparent_temperature": current.get("apparent_temperature"),
            "current_precipitation": current.get("precipitation"),
            "current_wind_speed": current.get("wind_speed_10m", current.get("windspeed")),
            "current_weather_code": weather_code,
            "current_condition": weather_label,
            "observed_at": current.get("time"),
            "forecast": forecast,
            "tls_warning": tls_warning,
            "alerts": [],
        }


def _pick(values: list, idx: int):
    if idx < len(values):
        return values[idx]
    return None


def _build_forecast(daily: dict[str, Any], start_idx: int, days: int) -> list[dict[str, Any]]:
    forecast: list[dict[str, Any]] = []
    times = daily.get("time", [])
    max_values = daily.get("temperature_2m_max", [])
    min_values = daily.get("temperature_2m_min", [])
    precipitation_values = daily.get("precipitation_probability_max", [])
    wind_values = daily.get("wind_speed_10m_max", [])
    weather_codes = daily.get("weather_code", [])

    for offset in range(days):
        idx = start_idx + offset
        day_value = _pick(times, idx)
        if day_value is None:
            continue
        weather_code = _pick(weather_codes, idx)
        forecast.append(
            {
                "day": day_value,
                "temperature_min": _pick(min_values, idx),
                "temperature_max": _pick(max_values, idx),
                "precipitation_probability": _pick(precipitation_values, idx),
                "wind_speed": _pick(wind_values, idx),
                "weather_code": weather_code,
                "condition": WEATHER_CODE_LABELS.get(weather_code, "Άγνωστη κατάσταση"),
            }
        )
    return forecast


async def _fetch_payload(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> dict[str, Any]:
    response = await client.get(url, params=params, timeout=20.0)
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(str(payload.get("reason") or payload.get("message") or "Weather API returned error"))
    if not isinstance(payload, dict):
        raise RuntimeError("Weather API returned invalid payload")
    return payload


def _verify_config(settings: Settings) -> bool | str:
    if settings.weather_ca_bundle:
        return settings.weather_ca_bundle
    return settings.weather_ssl_verify


def _is_tls_error(exc: Exception | None) -> bool:
    if exc is None:
        return False
    lowered = str(exc).lower()
    return "certificate verify failed" in lowered or "ssl" in lowered


def _error_hint(exc: Exception | None) -> str:
    if exc is None:
        return "Unknown weather error"
    base = str(exc)
    if _is_tls_error(exc):
        return (
            f"{base}. Configure WEATHER_CA_BUNDLE with your corporate/root CA, or set "
            "WEATHER_SSL_VERIFY=false (or WEATHER_ALLOW_INSECURE_FALLBACK=true for fallback)."
        )[:280]
    return base[:280]
