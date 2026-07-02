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

# Sécurité anti-faux positifs :
# le script accepte uniquement une modification proche de la date de base officielle.
MAX_SAFE_SHIFT_DAYS = 3

# Pour garder une vérification large sans bloquer 10 minutes tous les matins.
MAX_DYNAMIC_FFF_ARTICLES = 80
REQUEST_TIMEOUT = 15
REQUEST_PAUSE_SECONDS = 0.15

# Dates de base reprises de l'image officielle VFC 26/27.
# Le script s'en sert comme garde-fou.
BASELINE = {
    1: "2026-08-07",
    2: "2026-08-14",
    3: "2026-08-20",
    4: "2026-08-29",
    5: "2026-09-05",
    6: "2026-09-12",
    7: "2026-09-19",
    8: "2026-09-26",
    9: "2026-10-03",
    10: "2026-10-17",
    11: "2026-10-31",
    12: "2026-11-07",
    13: "2026-11-21",
    14: "2026-12-05",
    15: "2026-12-12",
    16: "2027-01-16",
    17: "2027-01-23",
    18: "2027-01-30",
    19: "2027-02-06",
    20: "2027-02-13",
    21: "2027-02-20",
    22: "2027-02-27",
    23: "2027-03-06",
    24: "2027-03-13",
    25: "2027-03-20",
    26: "2027-03-27",
    27: "2027-04-03",
    28: "2027-04-10",
    29: "2027-04-17",
    30: "2027-04-24",
    31: "2027-05-01",
    32: "2027-05-08",
    33: "2027-05-14",
    34: "2027-05-21",
}

# Sources officielles prioritaires.
# On privilégie : FFF/Ligue 3, VFC, puis les sites officiels des adversaires.
FIXED_SOURCES = [
    # FFF / Ligue 3
    "https://www.fff.fr/article/17019-j1-j2-j3-la-programmation-officialisee.html",
    "https://www.fff.fr/article/17022-le-calendrier-2026-2027-est-servi.html",
    "https://ligue1.com/fr/articles/l1_article_5407-ligue-3-le-calendrier-de-la-saison-2026-2027",

    # VFC officiel
    "https://vfclaroche.com/",
    "https://vfclaroche.com/calendrier-2026-2027/",

    # FC Versailles
    "https://fcversailles.com/",
    "https://fcversailles.com/national/calendrier-resultats/",

    # Amiens SC
    "https://www.amiensfootball.com/",

    # AS Cannes
    "https://www.as-cannes.com/",
    "https://www.as-cannes.com/calendrier/",

    # US Orléans
    "https://orleansloiretfoot.com/accueil/",
    "https://orleansloiretfoot.com/calendrier/",

    # QRM
    "https://qrm.fr/",
    "https://qrm.fr/calendrier-classement/",

    # FC Villefranche Beaujolais
    "https://www.fcvb.fr/",
    "https://www.fcvb.fr/equipe-pro/calendrier-resultats-equipe-pro",

    # Valenciennes FC
    "https://www.va-fc.com/",

    # US Thionville Lusitanos
    "https://www.ustl.fr/",
    "https://www.ustl.fr/equipes",

    # SC Aubagne Air Bel
    "https://www.scaab.fr/",

    # SM Caen
    "https://www.smcaen.fr/",

    # FC Bourg-en-Bresse Péronnas 01
    "https://fbbp01.fr/",

    # Paris 13 Atlético
    "https://paris13atletico.fr/",

    # US Concarneau
    "https://www.usc-concarneau.com/accueil/",
    "https://www.usc-concarneau.com/pros/calendrier/",

    # FC Rouen 1899
    "https://fcr1899.com/",
    "https://fcr1899.com/calendrier-et-resultats/",

    # FC Fleury 91
    "https://www.fcfleury91.fr/",

    # SC Bastia
    "https://sc-bastia.corsica/",

    # Le Puy-en-Velay FC
    "https://lepuyfoot43.fr/",
]

# Sitemaps FFF : on ne prend que les articles récents pertinents.
# Ça évite de dépendre uniquement des liens fixes quand la FFF publie une nouvelle programmation.
FFF_SITEMAPS = [f"https://www.fff.fr/sitemap-articles-{i}.xml" for i in range(1, 40)]

MONTHS = {
    "janvier": 1,
    "fevrier": 2,
    "février": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "août": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
    "décembre": 12,
}

MONTHS_NORM = {}


def normalize(value: str) -> str:
    value = value.replace("œ", "oe").replace("Œ", "oe").replace("’", "'")
    value = unicodedata.normalize("NFD", value)
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = value.lower()
    value = re.sub(r"[^a-z0-9/:' .-]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


for month_name, month_number in MONTHS.items():
    MONTHS_NORM[normalize(month_name)] = month_number

MONTH_RE = "|".join(sorted(MONTHS_NORM, key=len, reverse=True))

VFC_ALIASES = [
    "vfc",
    "vendee fc",
    "vendée fc",
    "vendee football club",
    "vendée football club",
    "vendee fc la roche",
    "vendée fc la roche",
    "la roche sur yon",
    "la roche-sur-yon",
    "la roche/yon",
    "la roche yon",
    "vendée football club la roche-sur-yon",
    "vendee football club la roche sur yon",
]

TEAM_ALIASES = {
    "FC Versailles": ["fc versailles", "versailles"],
    "Amiens SC": ["amiens sc", "amiens"],
    "AS Cannes": ["as cannes", "cannes"],
    "US Orléans": ["us orleans", "us orléans", "orleans", "orléans"],
    "QRM": ["qrm", "quevilly rouen", "quevilly rouen metropole", "quevilly rouen métropole"],
    "FC Villefranche Beaujolais": ["fc villefranche beaujolais", "villefranche beaujolais", "villefranche"],
    "Valenciennes FC": ["valenciennes fc", "valenciennes", "vafc", "va-fc"],
    "US Thionville Lusitanos": ["us thionville lusitanos", "thionville lusitanos", "thionville"],
    "SC Aubagne Air Bel": ["sc aubagne air bel", "aubagne air bel", "aubagne"],
    "SM Caen": ["sm caen", "caen"],
    "FC Bourg en Bresse P01": [
        "fc bourg en bresse p01",
        "fc bourg en bresse",
        "bourg en bresse",
        "bourg-en-bresse",
        "peronnas",
        "péronnas",
        "fbbp01",
    ],
    "Paris 13 Atlético": ["paris 13 atletico", "paris 13 atlético", "paris 13"],
    "US Concarneau": ["us concarneau", "concarneau"],
    "FC Rouen 1899": ["fc rouen 1899", "fc rouen", "rouen"],
    "FC Fleury 91": ["fc fleury 91", "fleury 91", "fleury"],
    "SC Bastia": ["sc bastia", "bastia", "sporting club de bastia"],
    "Le Puy-en-Velay FC": [
        "le puy-en-velay fc",
        "le puy en velay fc",
        "le puy-en-velay",
        "le puy en velay",
        "le puy",
    ],
}


def log(message: str) -> None:
    print(message, flush=True)


def fetch(url: str, timeout: int = REQUEST_TIMEOUT) -> str | None:
    try:
        req = Request(
            url,
            headers={
                "User-Agent": "VFC-Calendar-Updater/3.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
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


def parse_sitemap_lastmod(value: str | None) -> datetime:
    if not value:
        return datetime.min
    value = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        return datetime.min


def sitemap_urls() -> list[str]:
    candidates: list[tuple[datetime, str]] = []
    seen: set[str] = set()

    for sitemap in FFF_SITEMAPS:
        raw = fetch(sitemap, timeout=REQUEST_TIMEOUT)
        if not raw:
            continue

        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            continue

        for url_node in root.iter():
            if not url_node.tag.endswith("url"):
                continue

            loc = None
            lastmod = None
            for child in url_node:
                if child.tag.endswith("loc"):
                    loc = (child.text or "").strip()
                elif child.tag.endswith("lastmod"):
                    lastmod = (child.text or "").strip()

            if not loc or loc in seen:
                continue

            lower = loc.lower()
            if "/article/" not in lower:
                continue

            keywords = ["ligue-3", "programmation", "programme", "calendrier", "horaire", "journee", "journée", "national"]
            if not any(keyword in lower for keyword in keywords):
                continue

            seen.add(loc)
            candidates.append((parse_sitemap_lastmod(lastmod), loc))

    candidates.sort(key=lambda item: item[0], reverse=True)
    limited = [url for _, url in candidates[:MAX_DYNAMIC_FFF_ARTICLES]]
    log(f"Articles FFF dynamiques retenus: {len(limited)}")
    return limited


def candidate_sources() -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    for url in FIXED_SOURCES:
        if url not in seen:
            urls.append(url)
            seen.add(url)

    for url in sitemap_urls():
        if url not in seen:
            urls.append(url)
            seen.add(url)

    return urls


def parse_french_date(day: str, month_name: str, year_text: str | None) -> date | None:
    month = MONTHS_NORM.get(normalize(month_name))
    if not month:
        return None

    year = int(year_text) if year_text else (2027 if month <= 6 else 2026)

    try:
        return date(year, month, int(day))
    except ValueError:
        return None


def parse_numeric_date(day: str, month: str, year_text: str | None) -> date | None:
    year = int(year_text) if year_text else (2027 if int(month) <= 6 else 2026)

    try:
        return date(year, int(month), int(day))
    except ValueError:
        return None


def clean_time(hour_text: str | None, minute_text: str | None) -> str | None:
    if hour_text is None:
        return None

    hour = int(hour_text)
    minute = int(minute_text or 0)

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    return f"{hour:02d}:{minute:02d}"


def find_date_time_candidates(text: str) -> list[tuple[date, str | None]]:
    norm = normalize(text)
    results: list[tuple[date, str | None]] = []

    def add_candidate(candidate_date: date | None, candidate_time: str | None) -> None:
        if not candidate_date:
            return
        item = (candidate_date, candidate_time)
        if item not in results:
            results.append(item)

    date_then_time = re.compile(
        rf"(?P<day>\d{{1,2}})(?:er)?[\s.\-/]+(?P<month>{MONTH_RE})(?:\s+(?P<year>20\d{{2}}))?"
        rf".{{0,80}}?"
        rf"(?P<hour>\d{{1,2}})\s*(?:h|:|heures?)\s*(?P<minute>\d{{2}})?",
        flags=re.I | re.S,
    )
    for match in date_then_time.finditer(norm):
        d = parse_french_date(match.group("day"), match.group("month"), match.groupdict().get("year"))
        t = clean_time(match.group("hour"), match.groupdict().get("minute"))
        add_candidate(d, t)

    time_then_date = re.compile(
        rf"(?P<hour>\d{{1,2}})\s*(?:h|:|heures?)\s*(?P<minute>\d{{2}})?"
        rf".{{0,80}}?"
        rf"(?P<day>\d{{1,2}})(?:er)?[\s.\-/]+(?P<month>{MONTH_RE})(?:\s+(?P<year>20\d{{2}}))?",
        flags=re.I | re.S,
    )
    for match in time_then_date.finditer(norm):
        d = parse_french_date(match.group("day"), match.group("month"), match.groupdict().get("year"))
        t = clean_time(match.group("hour"), match.groupdict().get("minute"))
        add_candidate(d, t)

    numeric_date_then_time = re.compile(
        r"(?P<day>\d{1,2})[/-](?P<month>\d{1,2})(?:[/-](?P<year>20\d{2}))?"
        r".{0,80}?"
        r"(?P<hour>\d{1,2})\s*(?:h|:|heures?)\s*(?P<minute>\d{2})?",
        flags=re.I | re.S,
    )
    for match in numeric_date_then_time.finditer(norm):
        d = parse_numeric_date(match.group("day"), match.group("month"), match.groupdict().get("year"))
        t = clean_time(match.group("hour"), match.groupdict().get("minute"))
        add_candidate(d, t)

    french_date_only = re.compile(
        rf"(?P<day>\d{{1,2}})(?:er)?[\s.\-/]+(?P<month>{MONTH_RE})(?:\s+(?P<year>20\d{{2}}))?",
        flags=re.I,
    )
    for match in french_date_only.finditer(norm):
        d = parse_french_date(match.group("day"), match.group("month"), match.groupdict().get("year"))
        add_candidate(d, None)

    numeric_date_only = re.compile(
        r"(?P<day>\d{1,2})[/-](?P<month>\d{1,2})(?:[/-](?P<year>20\d{2}))?",
        flags=re.I,
    )
    for match in numeric_date_only.finditer(norm):
        d = parse_numeric_date(match.group("day"), match.group("month"), match.groupdict().get("year"))
        add_candidate(d, None)

    return results


def aliases_for(opponent: str) -> list[str]:
    return [normalize(alias) for alias in TEAM_ALIASES.get(opponent, [opponent])]


def has_alias(text_norm: str, aliases: list[str]) -> bool:
    for alias in aliases:
        alias_norm = normalize(alias)
        if not alias_norm:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(alias_norm)}(?![a-z0-9])", text_norm):
            return True
    return False


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
            current_date = datetime.strptime(str(current), "%Y-%m-%d").date()
            baseline_date = datetime.strptime(baseline, "%Y-%m-%d").date()
        except Exception:
            current_date = None
            baseline_date = datetime.strptime(baseline, "%Y-%m-%d").date()

        if current_date is None or abs((current_date - baseline_date).days) > MAX_SAFE_SHIFT_DAYS:
            log(f"J{round_no}: correction garde-fou {current} -> {baseline}")
            match["date"] = baseline

            if round_no > 3:
                match["official"] = False
                match["note"] = "Horaire à confirmer"

            changed = True

    return changed


def fixture_windows(text: str, match: dict) -> list[str]:
    windows: list[str] = []
    seen: set[str] = set()

    vfc_aliases = [normalize(alias) for alias in VFC_ALIASES]
    opponent_aliases = aliases_for(match["opponent"])

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index in range(len(lines)):
        chunk = " ".join(lines[index:index + 8])[:1500]
        norm = normalize(chunk)

        if has_alias(norm, vfc_aliases) and has_alias(norm, opponent_aliases):
            if norm not in seen:
                windows.append(chunk)
                seen.add(norm)

    flat = normalize(text)
    if has_alias(flat, vfc_aliases) and has_alias(flat, opponent_aliases):
        for opponent_alias in opponent_aliases:
            for occurrence in re.finditer(rf"(?<![a-z0-9]){re.escape(opponent_alias)}(?![a-z0-9])", flat):
                start = max(0, occurrence.start() - 900)
                end = min(len(flat), occurrence.end() + 900)
                chunk = flat[start:end]

                if has_alias(chunk, vfc_aliases) and has_alias(chunk, opponent_aliases):
                    if chunk not in seen:
                        windows.append(chunk)
                        seen.add(chunk)

                if len(windows) >= 10:
                    return windows

    return windows


def choose_best_candidate(round_no: int, candidates: list[tuple[date, str | None]]) -> tuple[date, str | None] | None:
    safe_candidates = [(d, t) for d, t in candidates if safe_to_apply(round_no, d)]

    if not safe_candidates:
        return None

    baseline_date = datetime.strptime(BASELINE[round_no], "%Y-%m-%d").date()
    safe_candidates.sort(key=lambda item: (item[1] is None, abs((item[0] - baseline_date).days)))
    return safe_candidates[0]


def update_from_source(matches: list[dict], url: str, text: str) -> bool:
    changed = False
    norm_all = normalize(text)

    global_keywords = [
        "ligue 3",
        "national",
        "calendrier",
        "programmation",
        "horaire",
        "journee",
        "journée",
        "vfc",
        "la roche",
    ]
    if not any(keyword in norm_all for keyword in global_keywords):
        return False

    for match in matches:
        round_no = int(match["round"])
        windows = fixture_windows(text, match)

        if not windows:
            continue

        for chunk in windows:
            candidates = find_date_time_candidates(chunk)

            if not candidates:
                continue

            best = choose_best_candidate(round_no, candidates)

            if not best:
                sample = candidates[0]
                log(f"J{round_no}: candidat ignoré {sample[0]} {sample[1] or ''} trop éloigné de la date de base")
                continue

            new_date, new_time = best
            new_date_text = new_date.isoformat()
            local_change = False

            if match.get("date") != new_date_text:
                log(f"J{round_no}: date {match.get('date')} -> {new_date_text}")
                match["date"] = new_date_text
                local_change = True

            if new_time and match.get("time") != new_time:
                log(f"J{round_no}: heure {match.get('time')} -> {new_time}")
                match["time"] = new_time
                local_change = True

            if local_change or not match.get("official"):
                match["official"] = True
                match["source_url"] = url
                match["last_checked"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

                if new_time:
                    match["note"] = "Horaire officialisé automatiquement"
                else:
                    match["note"] = "Date officialisée automatiquement - horaire à confirmer"

            changed = changed or local_change
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

    for index, url in enumerate(sources, start=1):
        log(f"[{index}/{len(sources)}] Vérification: {url}")
        raw = fetch(url)

        if not raw:
            continue

        text = html_to_text(raw)

        if update_from_source(matches, url, text):
            log(f"Mise à jour détectée depuis: {url}")
            changed = True

        time.sleep(REQUEST_PAUSE_SECONDS)

    if changed:
        MATCHES_FILE.write_text(
            json.dumps(matches, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        log("matches.json mis à jour")
    else:
        log("Aucune modification officielle détectée")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
