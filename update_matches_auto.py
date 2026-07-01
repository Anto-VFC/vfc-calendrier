from __future__ import annotations

import html
import json
import re
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

MATCHES_FILE = Path("matches.json")
MAX_SAFE_SHIFT_DAYS = 3

# Calendrier de base issu de l'image officielle VFC. Sert de garde-fou anti-faux positifs.
BASELINE = {
    1: "2026-08-07", 2: "2026-08-14", 3: "2026-08-20", 4: "2026-08-29",
    5: "2026-09-05", 6: "2026-09-12", 7: "2026-09-19", 8: "2026-09-26",
    9: "2026-10-03", 10: "2026-10-17", 11: "2026-10-31", 12: "2026-11-07",
    13: "2026-11-21", 14: "2026-12-05", 15: "2026-12-12", 16: "2027-01-16",
    17: "2027-01-23", 18: "2027-01-30", 19: "2027-02-06", 20: "2027-02-13",
    21: "2027-02-20", 22: "2027-02-27", 23: "2027-03-06", 24: "2027-03-13",
    25: "2027-03-20", 26: "2027-03-27", 27: "2027-04-03", 28: "2027-04-10",
    29: "2027-04-17", 30: "2027-04-24", 31: "2027-05-01", 32: "2027-05-08",
    33: "2027-05-14", 34: "2027-05-21",
}

FIXED_SOURCES = [
    "https://www.fff.fr/article/17019-j1-j2-j3-la-programmation-officialisee.html",
    "https://www.fff.fr/article/17022-le-calendrier-2026-2027-est-servi.html",
    "https://ligue1.com/fr/articles/l1_article_5407-ligue-3-le-calendrier-de-la-saison-2026-2027",
]
FFF_SITEMAPS = [f"https://www.fff.fr/sitemap-articles-{i}.xml" for i in range(1, 40)]

MONTHS = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "août": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12,
}
MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))

VFC_ALIASES = [
    "vfc", "vendee fc", "vendée fc", "vendee football club", "vendée football club",
    "vendee fc la roche", "vendée fc la roche", "la roche sur yon", "la roche-sur-yon",
    "la roche/yon", "la roche yon",
]

TEAM_ALIASES = {
    "FC Versailles": ["fc versailles", "versailles"],
    "Amiens SC": ["amiens sc", "amiens"],
    "AS Cannes": ["as cannes", "cannes"],
    "US Orléans": ["us orleans", "us orléans", "orleans", "orléans"],
    "QRM": ["qrm", "quevilly rouen", "quevilly rouen metropole", "quevilly rouen métropole"],
    "FC Villefranche Beaujolais": ["fc villefranche beaujolais", "villefranche beaujolais", "villefranche"],
    "Valenciennes FC": ["valenciennes fc", "valenciennes"],
    "US Thionville Lusitanos": ["us thionville lusitanos", "thionville lusitanos", "thionville"],
    "SC Aubagne Air Bel": ["sc aubagne air bel", "aubagne air bel", "aubagne"],
    "SM Caen": ["sm caen", "caen"],
    "FC Bourg en Bresse P01": ["fc bourg en bresse p01", "bourg en bresse", "bourg-en-bresse", "peronnas", "péronnas"],
    "Paris 13 Atlético": ["paris 13 atletico", "paris 13 atlético", "paris 13"],
    "US Concarneau": ["us concarneau", "concarneau"],
    "FC Rouen 1899": ["fc rouen 1899", "fc rouen", "rouen"],
    "FC Fleury 91": ["fc fleury 91", "fleury 91", "fleury"],
    "SC Bastia": ["sc bastia", "bastia"],
    "Le Puy-en-Velay FC": ["le puy-en-velay fc", "le puy en velay fc", "le puy-en-velay", "le puy en velay", "le puy"],
}


def log(message: str) -> None:
    print(message, flush=True)


def normalize(value: str) -> str:
    value = value.replace("œ", "oe").replace("Œ", "oe").replace("’", "'")
    value = unicodedata.normalize("NFD", value)
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = value.lower()
    value = re.sub(r"[^a-z0-9/:' .-]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def fetch(url: str, timeout: int = 20) -> str | None:
    try:
        req = Request(url, headers={
            "User-Agent": "VFC-Calendar-Updater/2.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        with urlopen(req, timeout=timeout) as response:
            data = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return data.decode(charset, errors="replace")
    except (HTTPError, URLError, TimeoutError) as exc:
        log(f"Source inaccessible ignorée: {url} ({exc})")
        return None


def html_to_text(raw: str) -> str:
    raw = re.sub(r"<script\b.*?</script>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<style\b.*?</style>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"</(p|li|h1|h2|h3|h4|div|section|article|tr|td|th)>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
    raw = re.sub(r"\n\s*\n+", "\n", raw)
    return raw.strip()


def sitemap_urls() -> list[str]:
    urls: set[str] = set()
    for sitemap in FFF_SITEMAPS:
        raw = fetch(sitemap, timeout=15)
        if not raw:
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            continue
        for item in root.iter():
            if not item.tag.endswith("loc") or not item.text:
                continue
            url = item.text.strip()
            lower = url.lower()
            if "/article/" in lower and any(k in lower for k in ["ligue-3", "programmation", "programme", "calendrier", "horaire"]):
                urls.add(url)
    return sorted(urls)


def candidate_sources() -> list[str]:
    urls = set(FIXED_SOURCES)
    urls.update(sitemap_urls())
    return sorted(urls)


def parse_date(day: str, month_name: str, year_text: str | None) -> date | None:
    month = MONTHS.get(month_name.lower()) or MONTHS.get(normalize(month_name))
    if not month:
        return None
    year = int(year_text) if year_text else (2027 if month <= 6 else 2026)
    try:
        return date(year, month, int(day))
    except ValueError:
        return None


def find_dates_times(text: str) -> list[tuple[date, str]]:
    results: list[tuple[date, str]] = []
    patterns = [
        rf"(?P<day>\d{{1,2}})(?:er)?\s+(?P<month>{MONTH_RE})(?:\s+(?P<year>20\d{{2}}))?.{{0,100}}?(?:a|à|de|,|:|-)?\s*(?P<hour>\d{{1,2}})\s*(?:h|:|heures?)\s*(?P<minute>\d{{2}})?",
        rf"(?P<hour>\d{{1,2}})\s*(?:h|:|heures?)\s*(?P<minute>\d{{2}})?.{{0,100}}?(?P<day>\d{{1,2}})(?:er)?\s+(?P<month>{MONTH_RE})(?:\s+(?P<year>20\d{{2}}))?",
    ]
    for pattern in patterns:
        for m in re.finditer(pattern, text, flags=re.I | re.S):
            d = parse_date(m.group("day"), m.group("month"), m.groupdict().get("year"))
            if not d:
                continue
            hour = int(m.group("hour"))
            minute = int(m.group("minute") or 0)
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                item = (d, f"{hour:02d}:{minute:02d}")
                if item not in results:
                    results.append(item)
    return results


def aliases_for(opponent: str) -> list[str]:
    return [normalize(a) for a in TEAM_ALIASES.get(opponent, [opponent])]


def has_alias(text_norm: str, aliases: list[str]) -> bool:
    return any(alias and re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text_norm) for alias in aliases)


def safe_to_apply(round_no: int, new_date: date) -> bool:
    baseline = datetime.strptime(BASELINE[round_no], "%Y-%m-%d").date()
    shift = abs((new_date - baseline).days)
    return shift <= MAX_SAFE_SHIFT_DAYS


def repair_against_baseline(matches: list[dict]) -> bool:
    changed = False
    for match in matches:
        round_no = int(match["round"])
        baseline = BASELINE.get(round_no)
        if not baseline:
            continue
        current = match.get("date")
        try:
            current_date = datetime.strptime(current, "%Y-%m-%d").date()
            baseline_date = datetime.strptime(baseline, "%Y-%m-%d").date()
        except Exception:
            current_date = None
            baseline_date = datetime.strptime(baseline, "%Y-%m-%d").date()
        if current_date is None or abs((current_date - baseline_date).days) > MAX_SAFE_SHIFT_DAYS:
            log(f"J{round_no}: correction garde-fou {current} -> {baseline}")
            match["date"] = baseline
            match["official"] = False if round_no > 3 else bool(match.get("official", False))
            match["note"] = "Horaire à confirmer" if round_no > 3 else match.get("note", "Horaire officialisé")
            changed = True
    return changed


def fixture_windows(text: str, match: dict) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    windows: list[str] = []
    for i in range(len(lines)):
        chunk = " ".join(lines[i:i + 4])[:900]
        norm = normalize(chunk)
        if has_alias(norm, [normalize(a) for a in VFC_ALIASES]) and has_alias(norm, aliases_for(match["opponent"])):
            windows.append(chunk)
    return windows


def update_from_source(matches: list[dict], url: str, text: str) -> bool:
    changed = False
    norm_all = normalize(text)
    if not any(k in norm_all for k in ["ligue 3", "national", "calendrier", "programmation", "horaire", "journee"]):
        return False

    for match in matches:
        round_no = int(match["round"])
        for chunk in fixture_windows(text, match)[:5]:
            candidates = find_dates_times(chunk)
            if not candidates:
                continue
            baseline_date = datetime.strptime(BASELINE[round_no], "%Y-%m-%d").date()
            candidates.sort(key=lambda item: abs((item[0] - baseline_date).days))
            new_date, new_time = candidates[0]
            if not safe_to_apply(round_no, new_date):
                log(f"J{round_no}: candidat ignoré {new_date} {new_time} trop éloigné de la date de base")
                continue
            new_date_text = new_date.isoformat()
            if match.get("date") != new_date_text:
                log(f"J{round_no}: date {match.get('date')} -> {new_date_text}")
                match["date"] = new_date_text
                changed = True
            if match.get("time") != new_time:
                log(f"J{round_no}: heure {match.get('time')} -> {new_time}")
                match["time"] = new_time
                changed = True
            if changed or not match.get("official"):
                match["official"] = True
                match["note"] = "Horaire officialisé automatiquement"
                match["source_url"] = url
                match["last_checked"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            break
    return changed


def main() -> int:
    if not MATCHES_FILE.exists():
        log("matches.json introuvable")
        return 1

    matches = json.loads(MATCHES_FILE.read_text(encoding="utf-8"))
    changed = repair_against_baseline(matches)

    sources = candidate_sources()
    log(f"Sources à vérifier: {len(sources)}")
    for url in sources:
        raw = fetch(url)
        if not raw:
            continue
        text = html_to_text(raw)
        if update_from_source(matches, url, text):
            log(f"Mise à jour depuis: {url}")
            changed = True
        time.sleep(0.2)

    if changed:
        MATCHES_FILE.write_text(json.dumps(matches, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log("matches.json mis à jour")
    else:
        log("Aucune modification officielle détectée")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
