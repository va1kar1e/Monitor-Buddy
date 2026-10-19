"""The data behind the pages a Monitor Buddy shows, for the desktop app.

The Buddy fetches its weather, GitHub and stock numbers itself, so the app
cannot ask it for them; it asks the same public services the Buddy asks, with
the same settings (location, GitHub user, ticker). The clock, Claude, Codex,
status and Wi-Fi pages come from this PC and from the Buddy over USB.

Everything here is plain functions with the network passed in (`fetch_json`),
so the tests need no internet. Standard library only.
"""
import datetime as dt
import json
import urllib.error
import urllib.parse
import urllib.request

# Page order on the Buddy; the moon page was removed. "face" has no data.
PAGES = [("face", "Face"), ("clock", "Clock"), ("date", "Date"), ("weather", "Weather"),
         ("stock", "Stock"), ("github", "GitHub"), ("claude", "Claude"), ("codex", "Codex"),
         ("status", "Status"), ("wifi", "Wi-Fi")]

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class FetchError(Exception):
    """Something a person can read: no network, bad key, unknown name."""


def fetch_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "monitor-buddy-app"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise FetchError(f"{e.code} from {urllib.parse.urlparse(url).netloc}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise FetchError(f"cannot reach {urllib.parse.urlparse(url).netloc}: {getattr(e, 'reason', e)}") from e


def clock_page(now):
    """('22:24:36', 'Monday', '19 October 2026')."""
    return now.strftime("%H:%M:%S"), WEEKDAYS[now.weekday()], f"{now.day} {now.strftime('%B %Y')}"


def weather_text(code):
    """The words the Buddy prints for a WMO weather code."""
    if code == 0:
        return "CLEAR"
    if code in (1, 2):
        return "PARTLY CLOUDY"
    if code == 3:
        return "CLOUDY"
    if code in (45, 48):
        return "FOG"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "RAIN"
    if 71 <= code <= 77:
        return "SNOW"
    if code >= 95:
        return "STORM"
    return "WEATHER"


def weather_page(lat, lon, fahrenheit=False, mph=False, fetch=fetch_json):
    """{'temp', 'humidity', 'wind', 'text', 'is_day', 'unit', 'wind_unit'} from Open-Meteo."""
    try:
        float(lat), float(lon)
    except (TypeError, ValueError):
        raise FetchError("set a latitude and longitude") from None
    url = ("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
        "temperature_unit": "fahrenheit" if fahrenheit else "celsius",
        "wind_speed_unit": "mph" if mph else "kmh"}))
    cur = (fetch(url) or {}).get("current")
    if not isinstance(cur, dict) or "temperature_2m" not in cur:
        raise FetchError("the weather service sent nothing usable")
    return {"temp": round(cur["temperature_2m"]), "humidity": round(cur.get("relative_humidity_2m", 0)),
            "wind": round(cur.get("wind_speed_10m", 0)), "text": weather_text(int(cur.get("weather_code", -1))),
            "is_day": bool(cur.get("is_day", 1)), "unit": "F" if fahrenheit else "C",
            "wind_unit": "MPH" if mph else "KMH"}


def github_page(user, fetch=fetch_json):
    """{'followers', 'repos'} for a GitHub user name."""
    user = (user or "").strip()
    if not user:
        raise FetchError("set a GitHub user")
    if not all(c.isalnum() or c == "-" for c in user):
        raise FetchError("that is not a GitHub user name")
    d = fetch("https://api.github.com/users/" + user) or {}
    if "followers" not in d:
        raise FetchError("the GitHub reply had no follower count")
    return {"followers": int(d["followers"]), "repos": int(d.get("public_repos", 0))}


def stock_page(ticker, key, fetch=fetch_json):
    """{'price', 'open', 'high', 'low', 'change_pct'} from Finnhub."""
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise FetchError("set a ticker")
    if not (key or "").strip():
        raise FetchError("set a Finnhub key (a free account at finnhub.io)")
    d = fetch("https://finnhub.io/api/v1/quote?" + urllib.parse.urlencode({"symbol": ticker, "token": key.strip()})) or {}
    if not d.get("c"):
        raise FetchError(f"Finnhub has no price for {ticker}")
    prev = d.get("pc") or 0
    return {"price": d["c"], "open": d.get("o", 0), "high": d.get("h", 0), "low": d.get("l", 0),
            "change_pct": (d["c"] - prev) / prev * 100 if prev else 0.0}
