from __future__ import annotations

import html
import json
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

MATCHES_FILE = Path("matches.json")
TIMEOUT = 20
MAX_DATE_SHIFT_DAYS = 5
MAX_URLS_PER_DOMAIN = 80

SEASON_START = date(2026, 7, 1)
SEASON_END = date(2027, 6, 30)

# Une source avec un nombre plus petit est prioritaire.
SOURCE_PRIORITY = {
    "fff.fr": 1,
    "vfclaroche.com": 2,
    "ligue1.com": 3,
    "lfp.fr": 3,
}

START_URLS = [
    "https://www.fff.fr/",
    "https://www.fff.fr/sitemap.xml",
    "https://vfclaroche.com/",
    "https://vfclaroche.com/sitemap_index.xml",
    "https://ligue1.com/fr",
    "https://ligue1.com/sitemap.xml",
    "https://www.lfp.fr/",
    "https://www.lfp.fr/sitemap.xml",
]

KNOWN_OFFICIAL_PAGES = [
    "https://www.fff.fr/article/17019-j1-j2-j3-la-programmation-officialisee.html",
    "https://www.fff.fr/article/17022-le-calendrier-2026-2027-est-servi.html",
    "https://www.fff.fr/article/17087-j4-a-j8-le-programme-des-matches-decales.html",
    "https://vfclaroche.com/calendrier-2026-2027/",
    "https://ligue1.com/fr/articles/l1_article_5407-ligue-3-le-calendrier-de-la-saison-2026-2027",
]

VFC_ALIASES = [
    "vfc",
    "vendée fc",
    "vendee fc",
    "vendée football club",
    "vendee football club",
    "vendée fc la roche-sur-yon",
    "vendee fc la roche-sur-yon",
    "la roche-sur-yon",
    "la roche sur yon",
    "la roche/yon",
]

TEAM_ALIASES = {
    "FC Versailles": ["fc versailles", "versailles"],
    "Amiens SC": ["amiens sc", "amiens"],
    "AS Cannes": ["as cannes", "cannes"],
    "US Orléans": ["us orléans", "us orleans", "orléans", "orleans"],
    "QRM": ["qrm", "quevilly rouen", "quevilly-rouen"],
    "FC Villefranche Beaujolais": ["fc villefranche beaujolais", "villefranche beaujolais", "villefranche"],
    "Valenciennes FC": ["valenciennes fc", "valenciennes", "va-fc", "vafc"],
    "US Thionville Lusitanos": ["us thionville lusitanos", "thionville lusitanos", "thionville"],
    "SC Aubagne Air Bel": ["sc aubagne air bel", "aubagne air bel", "aubagne"],
    "SM Caen": ["sm caen", "stade malherbe caen", "caen"],
    "FC Bourg en Bresse P01": ["fc bourg en bresse p01", "bourg en bresse", "bourg-en-bresse", "fbbp01"],
    "Paris 13 Atlético": ["paris 13 atlético", "paris 13 atletico", "paris 13"],
    "US Concarneau": ["us concarneau", "concarneau"],
    "FC Rouen 1899": ["fc rouen 1899", "fc rouen", "rouen"],
    "FC Fleury 91": ["fc fleury 91", "fleury 91", "fleury"],
    "SC Bastia": ["sc bastia", "sporting club de bastia", "sporting bastia", "bastia"],
    "Le Puy-en-Velay FC": ["le puy-en-velay fc", "le puy en velay fc", "le puy-en-velay", "le puy en velay", "le puy"],
}



# Base de départ utilisée uniquement pour nettoyer les données erronées déjà
# présentes dans matches.json. Après ce premier nettoyage, seules les sources
# officielles peuvent modifier les rencontres.
INITIAL_SCHEDULE = {
    1: ("2026-08-07", "20:45"),
    2: ("2026-08-14", "19:00"),
    3: ("2026-08-20", "20:45"),
    4: ("2026-08-29", "14:45"),
    5: ("2026-09-05", "14:45"),
    6: ("2026-09-12", "14:45"),
    7: ("2026-09-19", "14:45"),
    8: ("2026-09-26", "14:45"),
    9: ("2026-10-03", "14:45"),
    10: ("2026-10-17", "14:45"),
    11: ("2026-10-31", "20:00"),
    12: ("2026-11-07", "20:00"),
    13: ("2026-11-21", "20:00"),
    14: ("2026-12-05", "20:00"),
    15: ("2026-12-12", "20:00"),
    16: ("2027-01-16", "20:00"),
    17: ("2027-01-23", "20:00"),
    18: ("2027-01-30", "20:00"),
    19: ("2027-02-06", "20:00"),
    20: ("2027-02-13", "20:00"),
    21: ("2027-02-20", "20:00"),
    22: ("2027-02-27", "20:00"),
    23: ("2027-03-06", "20:00"),
    24: ("2027-03-13", "20:00"),
    25: ("2027-03-20", "20:00"),
    26: ("2027-03-27", "20:00"),
    27: ("2027-04-03", "20:00"),
    28: ("2027-04-10", "20:00"),
    29: ("2027-04-17", "20:00"),
    30: ("2027-04-24", "20:00"),
    31: ("2027-05-01", "20:00"),
    32: ("2027-05-08", "20:00"),
    33: ("2027-05-14", "20:00"),
    34: ("2027-05-21", "20:00"),
}

MONTHS = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3,
    "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
    "aout": 8, "août": 8, "septembre": 9, "octobre": 10,
    "novembre": 11, "decembre": 12, "décembre": 12,
}


def log(message: str) -> None:
    print(message, flush=True)


def normalize(value: str) -> str:
    value = value.replace("œ", "oe").replace("Œ", "OE")
    value = value.replace("’", "'").replace("–", "-").replace("—", "-")
    value = unicodedata.normalize("NFD", value)
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    value = value.lower()
    value = re.sub(r"[^a-z0-9:/.' -]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def domain_of(url: str) -> str:
    match = re.search(r"https?://(?:www\.)?([^/]+)", url.lower())
    return match.group(1) if match else ""


def priority_of(url: str) -> int:
    domain = domain_of(url)
    for expected, priority in SOURCE_PRIORITY.items():
        if domain == expected or domain.endswith("." + expected):
            return priority
    return 99


def fetch(url: str) -> str | None:
    try:
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 VFC-Calendar-Updater/6.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fr-FR,fr;q=0.9",
                "Cache-Control": "no-cache",
            },
        )
        with urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        log(f"Source inaccessible : {url} — {error}")
        return None


def html_to_text(raw: str) -> str:
    raw = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<style\b[^>]*>.*?</style>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"</(?:p|li|h1|h2|h3|h4|div|section|article|tr|td|th)>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
    raw = re.sub(r"\n\s*\n+", "\n", raw)
    return raw.strip()


def sitemap_urls(raw: str, base_url: str) -> list[str]:
    urls: list[str] = []
    try:
        root = ET.fromstring(raw)
        for node in root.iter():
            if node.tag.endswith("loc") and node.text:
                urls.append(urljoin(base_url, node.text.strip()))
    except ET.ParseError:
        urls.extend(
            urljoin(base_url, value)
            for value in re.findall(r'href=["\']([^"\']+)["\']', raw, flags=re.I)
        )
    return urls


def relevant_url(url: str) -> bool:
    normalized = normalize(url)
    keywords = (
        "ligue-3", "ligue3", "calendrier", "programmation",
        "programme", "horaire", "journee", "match",
    )
    return any(keyword in normalized for keyword in keywords)


def discover_sources() -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    queue = list(START_URLS)
    per_domain: defaultdict[str, int] = defaultdict(int)

    for url in KNOWN_OFFICIAL_PAGES:
        if url not in seen:
            seen.add(url)
            result.append(url)

    while queue:
        url = queue.pop(0)
        domain = domain_of(url)
        if not domain or per_domain[domain] >= MAX_URLS_PER_DOMAIN:
            continue

        raw = fetch(url)
        if not raw:
            continue

        per_domain[domain] += 1
        discovered = sitemap_urls(raw, url)

        for found in discovered:
            found_domain = domain_of(found)
            if found_domain != domain:
                continue
            if found in seen:
                continue
            seen.add(found)

            if found.endswith(".xml") or "sitemap" in found.lower():
                queue.append(found)
            elif relevant_url(found):
                result.append(found)

    # Priorité FFF > VFC > LFP, puis URL.
    result = sorted(set(result), key=lambda u: (priority_of(u), u))
    log(f"Sources officielles retenues : {len(result)}")
    return result


def contains_alias(text: str, aliases: list[str]) -> bool:
    normalized_text = normalize(text)
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(normalize(alias))}(?![a-z0-9])", normalized_text)
        for alias in aliases
    )


def fixture_windows(text: str, opponent: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    opponent_aliases = TEAM_ALIASES.get(opponent, [opponent])
    windows: list[str] = []
    seen: set[str] = set()

    for index, line in enumerate(lines):
        # Le VFC et l'adversaire doivent être dans une petite zone commune.
        start = max(0, index - 2)
        end = min(len(lines), index + 4)
        window = " ".join(lines[start:end])

        if not contains_alias(window, VFC_ALIASES):
            continue
        if not contains_alias(window, opponent_aliases):
            continue

        normalized = normalize(window)
        if normalized not in seen:
            seen.add(normalized)
            windows.append(window[:900])

    return windows[:10]


def parse_date(day_text: str, month_text: str, year_text: str | None) -> date | None:
    month = MONTHS.get(month_text.lower())
    if month is None:
        month = MONTHS.get(normalize(month_text))
    if month is None:
        return None

    year = int(year_text) if year_text else (2027 if month <= 6 else 2026)
    try:
        result = date(year, month, int(day_text))
    except ValueError:
        return None
    return result if SEASON_START <= result <= SEASON_END else None


def valid_time(hour_text: str, minute_text: str | None) -> str | None:
    hour = int(hour_text)
    minute = int(minute_text or "00")

    # Évite les faux positifs 03:00, numéros de journées, dates, etc.
    if not 12 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return f"{hour:02d}:{minute:02d}"


MONTH_PATTERN = "|".join(sorted((re.escape(m) for m in MONTHS), key=len, reverse=True))


def extract_explicit_candidates(window: str) -> list[tuple[date, str]]:
    text = normalize(window)
    candidates: list[tuple[date, str]] = []

    patterns = [
        re.compile(
            rf"(?P<day>\d{{1,2}})(?:er)?\s+(?P<month>{MONTH_PATTERN})"
            rf"(?:\s+(?P<year>20\d{{2}}))?"
            rf".{{0,60}}?(?:a|à|vers|-)?\s*"
            rf"(?P<hour>\d{{1,2}})\s*(?:h|:)\s*(?P<minute>\d{{2}})?",
            flags=re.I | re.S,
        ),
        re.compile(
            r"(?P<day>\d{1,2})[/. -](?P<month>\d{1,2})"
            r"(?:[/. -](?P<year>20\d{2}))?"
            r".{0,60}?(?:a|à|vers|-)?\s*"
            r"(?P<hour>\d{1,2})\s*(?:h|:)\s*(?P<minute>\d{2})?",
            flags=re.I | re.S,
        ),
        re.compile(
            r"(?P<year>20\d{2})-(?P<month>\d{2})-(?P<day>\d{2})"
            r"[T ](?P<hour>\d{2}):(?P<minute>\d{2})",
            flags=re.I,
        ),
    ]

    for pattern in patterns:
        for match in pattern.finditer(text):
            values = match.groupdict()
            try:
                if values["month"].isdigit():
                    month = int(values["month"])
                    year = int(values.get("year") or (2027 if month <= 6 else 2026))
                    candidate_date = date(year, month, int(values["day"]))
                    if not SEASON_START <= candidate_date <= SEASON_END:
                        continue
                else:
                    candidate_date = parse_date(values["day"], values["month"], values.get("year"))
                    if candidate_date is None:
                        continue

                candidate_time = valid_time(values["hour"], values.get("minute"))
                if candidate_time and (candidate_date, candidate_time) not in candidates:
                    candidates.append((candidate_date, candidate_time))
            except (TypeError, ValueError):
                continue

    return candidates


def safe_for_match(match: dict, candidate_date: date) -> bool:
    current_date = datetime.strptime(match["date"], "%Y-%m-%d").date()
    return abs((candidate_date - current_date).days) <= MAX_DATE_SHIFT_DAYS


def collect_candidates(matches: list[dict], sources: list[str]) -> dict[int, list[dict]]:
    found: dict[int, list[dict]] = defaultdict(list)

    for index, source_url in enumerate(sources, start=1):
        log(f"[{index}/{len(sources)}] {source_url}")
        raw = fetch(source_url)
        if not raw:
            continue

        text = html_to_text(raw)

        for match in matches:
            windows = fixture_windows(text, str(match["opponent"]))
            for window in windows:
                for candidate_date, candidate_time in extract_explicit_candidates(window):
                    if not safe_for_match(match, candidate_date):
                        continue
                    found[int(match["round"])].append({
                        "date": candidate_date.isoformat(),
                        "time": candidate_time,
                        "source_url": source_url,
                        "priority": priority_of(source_url),
                    })

    return found


def choose_candidate(candidates: list[dict]) -> dict | None:
    if not candidates:
        return None

    # Déduplique.
    unique: dict[tuple[str, str, str], dict] = {}
    for item in candidates:
        unique[(item["date"], item["time"], item["source_url"])] = item
    candidates = list(unique.values())

    # La meilleure source officielle gagne.
    best_priority = min(item["priority"] for item in candidates)
    best = [item for item in candidates if item["priority"] == best_priority]

    # À priorité identique, il faut une valeur non ambiguë.
    values = {(item["date"], item["time"]) for item in best}
    if len(values) != 1:
        log(f"Candidats contradictoires ignorés : {sorted(values)}")
        return None

    return best[0]



def repair_existing_bad_data(matches: list[dict]) -> bool:
    """Nettoie une seule fois les valeurs introduites par l'ancien script."""
    changed = False
    bad_source = "17087-j4-a-j8-le-programme-des-matches-decales.html"

    for match in matches:
        round_number = int(match["round"])
        expected_date, expected_time = INITIAL_SCHEDULE[round_number]
        current_time = str(match.get("time", ""))
        source_url = str(match.get("source_url", ""))

        poisoned = (
            current_time.startswith("03:")
            or (4 <= round_number <= 8 and bad_source in source_url)
            or (round_number == 3 and current_time == "19:00")
        )

        if not poisoned:
            continue

        log(
            f"Nettoyage J{round_number} : "
            f"{match.get('date')} {current_time} -> "
            f"{expected_date} {expected_time}"
        )
        match["date"] = expected_date
        match["time"] = expected_time
        match["official"] = False
        match["note"] = "Base de départ corrigée, en attente de confirmation officielle"
        match["source_url"] = ""
        match["last_checked"] = ""
        changed = True

    return changed


def validate_matches(matches: list[dict]) -> None:
    rounds: set[int] = set()

    for match in matches:
        round_number = int(match["round"])
        if round_number in rounds:
            raise ValueError(f"Journée dupliquée : J{round_number}")
        rounds.add(round_number)

        datetime.strptime(match["date"], "%Y-%m-%d")
        parsed_time = datetime.strptime(match["time"], "%H:%M").time()
        if parsed_time.hour < 12:
            raise ValueError(
                f"Horaire suspect pour J{round_number} : {match['time']}. "
                "Corrige matches.json avant de relancer."
            )
        if not match.get("opponent"):
            raise ValueError(f"Adversaire absent pour J{round_number}")

    if rounds != set(range(1, 35)):
        raise ValueError("matches.json doit contenir les journées 1 à 34")


def main() -> int:
    if not MATCHES_FILE.exists():
        log("ERREUR : matches.json est introuvable")
        return 1

    try:
        matches = json.loads(MATCHES_FILE.read_text(encoding="utf-8"))
        repaired = repair_existing_bad_data(matches)
        validate_matches(matches)
    except Exception as error:
        log(f"ERREUR : {error}")
        return 1

    sources = discover_sources()
    candidates_by_round = collect_candidates(matches, sources)
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    changed = repaired

    for match in matches:
        round_number = int(match["round"])
        selected = choose_candidate(candidates_by_round.get(round_number, []))
        if not selected:
            continue

        new_date = selected["date"]
        new_time = selected["time"]

        if match["date"] == new_date and match["time"] == new_time:
            continue

        log(
            f"J{round_number} : "
            f"{match['date']} {match['time']} -> {new_date} {new_time}"
        )
        match["date"] = new_date
        match["time"] = new_time
        match["official"] = True
        match["note"] = "Date et horaire détectés automatiquement sur une source officielle"
        match["source_url"] = selected["source_url"]
        match["last_checked"] = checked_at
        changed = True

    if changed:
        validate_matches(matches)
        MATCHES_FILE.write_text(
            json.dumps(matches, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        log("matches.json mis à jour")
    else:
        log("Aucun changement officiel détecté")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
