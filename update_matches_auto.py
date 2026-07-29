from __future__ import annotations

import html
import json
import re
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET


MATCHES_FILE = Path("matches.json")

REQUEST_TIMEOUT = 20
MAX_DATE_SHIFT_DAYS = 4
MAX_FFF_ARTICLES = 120

SEASON_START = date(2026, 7, 1)
SEASON_END = date(2027, 6, 30)

# Calendrier de référence officiel.
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

# Programmations déjà confirmées.
# Ces données servent aussi de sécurité si une page officielle devient
# temporairement inaccessible.
CONFIRMED_MATCHES = {
    1: {
        "date": "2026-08-07",
        "time": "20:45",
        "source_url": (
            "https://www.fff.fr/article/"
            "17019-j1-j2-j3-la-programmation-officialisee.html"
        ),
    },
    2: {
        "date": "2026-08-14",
        "time": "19:00",
        "source_url": (
            "https://www.fff.fr/article/"
            "17019-j1-j2-j3-la-programmation-officialisee.html"
        ),
    },
    3: {
        "date": "2026-08-20",
        "time": "20:45",
        "source_url": (
            "https://www.fff.fr/article/"
            "17019-j1-j2-j3-la-programmation-officialisee.html"
        ),
    },
    # La FFF a publié les cinq affiches décalées des J4 à J8.
    # Le VFC ne figure dans aucune affiche décalée :
    # son match reste donc dans le créneau principal du samedi à 15h.
    4: {
        "date": "2026-08-29",
        "time": "15:00",
        "source_url": (
            "https://www.fff.fr/article/"
            "17087-j4-a-j8-le-programme-des-matches-decales.html"
        ),
    },
    5: {
        "date": "2026-09-05",
        "time": "15:00",
        "source_url": (
            "https://www.fff.fr/article/"
            "17087-j4-a-j8-le-programme-des-matches-decales.html"
        ),
    },
    6: {
        "date": "2026-09-12",
        "time": "15:00",
        "source_url": (
            "https://www.fff.fr/article/"
            "17087-j4-a-j8-le-programme-des-matches-decales.html"
        ),
    },
    7: {
        "date": "2026-09-19",
        "time": "15:00",
        "source_url": (
            "https://www.fff.fr/article/"
            "17087-j4-a-j8-le-programme-des-matches-decales.html"
        ),
    },
    8: {
        "date": "2026-09-26",
        "time": "15:00",
        "source_url": (
            "https://www.fff.fr/article/"
            "17087-j4-a-j8-le-programme-des-matches-decales.html"
        ),
    },
}

OFFICIAL_SOURCES = [
    # FFF
    "https://www.fff.fr/article/17019-j1-j2-j3-la-programmation-officialisee.html",
    "https://www.fff.fr/article/17022-le-calendrier-2026-2027-est-servi.html",
    "https://www.fff.fr/article/17087-j4-a-j8-le-programme-des-matches-decales.html",

    # VFC
    "https://vfclaroche.com/",
    "https://vfclaroche.com/calendrier-2026-2027/",

    # LFP / Ligue 1+
    "https://ligue1.com/fr/articles/l1_article_5407-ligue-3-le-calendrier-de-la-saison-2026-2027",

    # Sites officiels des adversaires
    "https://fcversailles.com/",
    "https://www.amiensfootball.com/",
    "https://www.as-cannes.com/",
    "https://orleansloiretfoot.com/",
    "https://qrm.fr/",
    "https://www.fcvb.fr/",
    "https://www.va-fc.com/",
    "https://www.ustl.fr/",
    "https://www.scaab.fr/",
    "https://www.smcaen.fr/",
    "https://fbbp01.fr/",
    "https://paris13atletico.fr/",
    "https://www.usc-concarneau.com/",
    "https://fcr1899.com/",
    "https://www.fcfleury91.fr/",
    "https://sc-bastia.corsica/",
    "https://lepuyfoot43.fr/",
]

FFF_SITEMAPS = [
    f"https://www.fff.fr/sitemap-articles-{number}.xml"
    for number in range(1, 45)
]

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
    "US Orléans": ["us orleans", "us orléans", "orléans", "orleans"],
    "QRM": [
        "qrm",
        "quevilly rouen",
        "quevilly-rouen",
        "quevilly rouen métropole",
    ],
    "FC Villefranche Beaujolais": [
        "fc villefranche beaujolais",
        "villefranche beaujolais",
        "villefranche",
    ],
    "Valenciennes FC": [
        "valenciennes fc",
        "valenciennes",
        "va-fc",
        "vafc",
    ],
    "US Thionville Lusitanos": [
        "us thionville lusitanos",
        "thionville lusitanos",
        "thionville",
    ],
    "SC Aubagne Air Bel": [
        "sc aubagne air bel",
        "aubagne air bel",
        "aubagne",
    ],
    "SM Caen": ["sm caen", "stade malherbe caen", "caen"],
    "FC Bourg en Bresse P01": [
        "fc bourg en bresse p01",
        "bourg en bresse",
        "bourg-en-bresse",
        "fbbp01",
        "péronnas",
        "peronnas",
    ],
    "Paris 13 Atlético": [
        "paris 13 atlético",
        "paris 13 atletico",
        "paris 13",
    ],
    "US Concarneau": ["us concarneau", "concarneau"],
    "FC Rouen 1899": ["fc rouen 1899", "fc rouen", "rouen"],
    "FC Fleury 91": ["fc fleury 91", "fleury 91", "fleury"],
    "SC Bastia": [
        "sc bastia",
        "sporting club de bastia",
        "sporting bastia",
        "bastia",
    ],
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


def normalize(value: str) -> str:
    value = value.replace("œ", "oe").replace("Œ", "OE")
    value = value.replace("’", "'").replace("–", "-").replace("—", "-")
    value = unicodedata.normalize("NFD", value)
    value = "".join(
        character
        for character in value
        if unicodedata.category(character) != "Mn"
    )
    value = value.lower()
    value = re.sub(r"[^a-z0-9:/.' -]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


MONTHS_NORMALIZED = {
    normalize(name): number
    for name, number in MONTHS.items()
}

MONTH_PATTERN = "|".join(
    sorted(
        (re.escape(name) for name in MONTHS_NORMALIZED),
        key=len,
        reverse=True,
    )
)


def fetch(url: str) -> str | None:
    try:
        request = Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 VFC-Calendar-Updater/4.0 "
                    "(GitHub Actions)"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,"
                    "application/xml;q=0.9,*/*;q=0.8"
                ),
                "Accept-Language": "fr-FR,fr;q=0.9",
                "Cache-Control": "no-cache",
            },
        )

        with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")

    except (HTTPError, URLError, TimeoutError, OSError) as error:
        log(f"Source inaccessible : {url} — {error}")
        return None


def html_to_text(raw: str) -> str:
    raw = re.sub(
        r"<script\b[^>]*>.*?</script>",
        " ",
        raw,
        flags=re.I | re.S,
    )
    raw = re.sub(
        r"<style\b[^>]*>.*?</style>",
        " ",
        raw,
        flags=re.I | re.S,
    )
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(
        r"</(?:p|li|h1|h2|h3|h4|div|section|article|tr|td|th)>",
        "\n",
        raw,
        flags=re.I,
    )
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
    raw = re.sub(r"\n\s*\n+", "\n", raw)
    return raw.strip()


def parse_lastmod(value: str | None) -> datetime:
    if not value:
        return datetime.min

    try:
        return datetime.fromisoformat(
            value.strip().replace("Z", "+00:00")
        ).replace(tzinfo=None)
    except ValueError:
        return datetime.min


def discover_fff_articles() -> list[str]:
    found: list[tuple[datetime, str]] = []
    seen: set[str] = set()

    keywords = (
        "ligue-3",
        "programmation",
        "programme",
        "calendrier",
        "horaire",
        "journee",
        "matches",
        "matchs",
    )

    for sitemap_url in FFF_SITEMAPS:
        raw = fetch(sitemap_url)

        if not raw:
            continue

        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            continue

        for node in root.iter():
            if not node.tag.endswith("url"):
                continue

            location = ""
            lastmod = ""

            for child in node:
                if child.tag.endswith("loc"):
                    location = (child.text or "").strip()
                elif child.tag.endswith("lastmod"):
                    lastmod = (child.text or "").strip()

            if not location or location in seen:
                continue

            lower_url = location.lower()

            if "/article/" not in lower_url:
                continue

            if not any(keyword in lower_url for keyword in keywords):
                continue

            seen.add(location)
            found.append((parse_lastmod(lastmod), location))

    found.sort(key=lambda item: item[0], reverse=True)

    articles = [
        url
        for _, url in found[:MAX_FFF_ARTICLES]
    ]

    log(f"Articles FFF dynamiques trouvés : {len(articles)}")
    return articles


def candidate_sources() -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for url in OFFICIAL_SOURCES + discover_fff_articles():
        if url not in seen:
            result.append(url)
            seen.add(url)

    return result


def contains_alias(text: str, aliases: list[str]) -> bool:
    normalized_text = normalize(text)

    for alias in aliases:
        normalized_alias = normalize(alias)

        if re.search(
            rf"(?<![a-z0-9]){re.escape(normalized_alias)}(?![a-z0-9])",
            normalized_text,
        ):
            return True

    return False


def fixture_sections(text: str, opponent: str) -> list[str]:
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    opponent_aliases = TEAM_ALIASES.get(opponent, [opponent])
    sections: list[str] = []
    seen: set[str] = set()

    # Analyse par petits blocs de lignes afin d'éviter d'associer
    # l'heure d'un autre match à celui du VFC.
    for index in range(len(lines)):
        start = max(0, index - 3)
        end = min(len(lines), index + 7)
        section = " ".join(lines[start:end])

        if not contains_alias(section, VFC_ALIASES):
            continue

        if not contains_alias(section, opponent_aliases):
            continue

        key = normalize(section)

        if key not in seen:
            seen.add(key)
            sections.append(section[:1800])

    return sections[:15]


def parse_date(
    day_text: str,
    month_text: str,
    year_text: str | None,
) -> date | None:
    month = MONTHS_NORMALIZED.get(normalize(month_text))

    if month is None:
        return None

    if year_text:
        year = int(year_text)
    else:
        year = 2027 if month <= 6 else 2026

    try:
        result = date(year, month, int(day_text))
    except ValueError:
        return None

    if not SEASON_START <= result <= SEASON_END:
        return None

    return result


def valid_time(hour_text: str, minute_text: str | None) -> str | None:
    try:
        hour = int(hour_text)
        minute = int(minute_text or "00")
    except ValueError:
        return None

    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None

    return f"{hour:02d}:{minute:02d}"


def extract_candidates(section: str) -> list[tuple[date, str | None]]:
    text = normalize(section)
    candidates: list[tuple[date, str | None]] = []

    expressions = [
        re.compile(
            rf"(?P<day>\d{{1,2}})(?:er)?\s+"
            rf"(?P<month>{MONTH_PATTERN})"
            rf"(?:\s+(?P<year>20\d{{2}}))?"
            rf".{{0,100}}?"
            rf"(?P<hour>\d{{1,2}})\s*(?:h|:|heures?)"
            rf"\s*(?P<minute>\d{{2}})?",
            flags=re.I | re.S,
        ),
        re.compile(
            rf"(?P<hour>\d{{1,2}})\s*(?:h|:|heures?)"
            rf"\s*(?P<minute>\d{{2}})?"
            rf".{{0,100}}?"
            rf"(?P<day>\d{{1,2}})(?:er)?\s+"
            rf"(?P<month>{MONTH_PATTERN})"
            rf"(?:\s+(?P<year>20\d{{2}}))?",
            flags=re.I | re.S,
        ),
    ]

    for expression in expressions:
        for match in expression.finditer(text):
            match_date = parse_date(
                match.group("day"),
                match.group("month"),
                match.groupdict().get("year"),
            )
            match_time = valid_time(
                match.group("hour"),
                match.groupdict().get("minute"),
            )

            if match_date and (match_date, match_time) not in candidates:
                candidates.append((match_date, match_time))

    # Format numérique : 29/08/2026 à 15h00
    numeric_expression = re.compile(
        r"(?P<day>\d{1,2})[/. -](?P<month>\d{1,2})"
        r"(?:[/. -](?P<year>20\d{2}))?"
        r".{0,100}?"
        r"(?P<hour>\d{1,2})\s*(?:h|:|heures?)"
        r"\s*(?P<minute>\d{2})?",
        flags=re.I | re.S,
    )

    for match in numeric_expression.finditer(text):
        month_number = int(match.group("month"))
        year_text = match.groupdict().get("year")
        year = int(year_text) if year_text else (
            2027 if month_number <= 6 else 2026
        )

        try:
            match_date = date(
                year,
                month_number,
                int(match.group("day")),
            )
        except ValueError:
            continue

        match_time = valid_time(
            match.group("hour"),
            match.groupdict().get("minute"),
        )

        if (
            SEASON_START <= match_date <= SEASON_END
            and (match_date, match_time) not in candidates
        ):
            candidates.append((match_date, match_time))

    return candidates


def candidate_is_safe(round_number: int, candidate_date: date) -> bool:
    baseline = datetime.strptime(
        BASELINE[round_number],
        "%Y-%m-%d",
    ).date()

    return abs((candidate_date - baseline).days) <= MAX_DATE_SHIFT_DAYS


def select_candidate(
    round_number: int,
    candidates: list[tuple[date, str | None]],
) -> tuple[date, str] | None:
    baseline = datetime.strptime(
        BASELINE[round_number],
        "%Y-%m-%d",
    ).date()

    safe = [
        item
        for item in candidates
        if item[1] and candidate_is_safe(round_number, item[0])
    ]

    if not safe:
        return None

    safe.sort(
        key=lambda item: (
            abs((item[0] - baseline).days),
            item[0],
            item[1],
        )
    )

    selected_date, selected_time = safe[0]

    if selected_time is None:
        return None

    return selected_date, selected_time


def apply_confirmed_matches(matches: list[dict]) -> bool:
    changed = False
    checked_at = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    for match in matches:
        round_number = int(match["round"])
        confirmation = CONFIRMED_MATCHES.get(round_number)

        if not confirmation:
            continue

        new_date = confirmation["date"]
        new_time = confirmation["time"]

        local_change = False

        if match.get("date") != new_date:
            log(
                f"J{round_number} : "
                f"date {match.get('date')} -> {new_date}"
            )
            match["date"] = new_date
            local_change = True

        if match.get("time") != new_time:
            log(
                f"J{round_number} : "
                f"heure {match.get('time')} -> {new_time}"
            )
            match["time"] = new_time
            local_change = True

        if (
            local_change
            or not match.get("official")
            or match.get("source_url") != confirmation["source_url"]
        ):
            match["official"] = True
            match["note"] = "Horaire officialisé"
            match["source_url"] = confirmation["source_url"]
            match["last_checked"] = checked_at
            changed = True

    return changed


def update_from_source(
    matches: list[dict],
    source_url: str,
    page_text: str,
) -> bool:
    normalized_page = normalize(page_text)

    useful_keywords = (
        "ligue 3",
        "programmation",
        "calendrier",
        "horaire",
        "journee",
        "match",
        "vfc",
        "la roche",
    )

    if not any(keyword in normalized_page for keyword in useful_keywords):
        return False

    changed = False
    checked_at = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    for match in matches:
        round_number = int(match["round"])
        opponent = str(match["opponent"])

        sections = fixture_sections(page_text, opponent)

        if not sections:
            continue

        candidates: list[tuple[date, str | None]] = []

        for section in sections:
            for candidate in extract_candidates(section):
                if candidate not in candidates:
                    candidates.append(candidate)

        selected = select_candidate(round_number, candidates)

        if not selected:
            continue

        new_date, new_time = selected
        new_date_text = new_date.isoformat()

        # Une nouvelle source explicite peut remplacer une ancienne
        # programmation confirmée.
        local_change = False

        if match.get("date") != new_date_text:
            log(
                f"J{round_number} : "
                f"date {match.get('date')} -> {new_date_text}"
            )
            match["date"] = new_date_text
            local_change = True

        if match.get("time") != new_time:
            log(
                f"J{round_number} : "
                f"heure {match.get('time')} -> {new_time}"
            )
            match["time"] = new_time
            local_change = True

        if local_change:
            match["official"] = True
            match["note"] = "Horaire officialisé automatiquement"
            match["source_url"] = source_url
            match["last_checked"] = checked_at
            changed = True

    return changed


def validate_matches(matches: list[dict]) -> None:
    rounds = set()

    for match in matches:
        round_number = int(match["round"])

        if round_number in rounds:
            raise ValueError(f"Journée dupliquée : J{round_number}")

        rounds.add(round_number)

        if round_number not in BASELINE:
            raise ValueError(f"Journée inconnue : J{round_number}")

        datetime.strptime(match["date"], "%Y-%m-%d")
        datetime.strptime(match["time"], "%H:%M")

        if not match.get("opponent"):
            raise ValueError(
                f"Adversaire absent pour la J{round_number}"
            )

    expected = set(range(1, 35))

    if rounds != expected:
        missing = sorted(expected - rounds)
        raise ValueError(f"Journées manquantes : {missing}")


def main() -> int:
    if not MATCHES_FILE.exists():
        log("ERREUR : matches.json est introuvable")
        return 1

    try:
        matches = json.loads(
            MATCHES_FILE.read_text(encoding="utf-8")
        )
        validate_matches(matches)
    except Exception as error:
        log(f"ERREUR dans matches.json : {error}")
        return 1

    changed = apply_confirmed_matches(matches)

    sources = candidate_sources()
    log(f"Nombre total de sources à vérifier : {len(sources)}")

    for index, source_url in enumerate(sources, start=1):
        log(f"[{index}/{len(sources)}] {source_url}")

        raw = fetch(source_url)

        if not raw:
            continue

        page_text = html_to_text(raw)

        if update_from_source(matches, source_url, page_text):
            log(f"Modification trouvée depuis {source_url}")
            changed = True

    validate_matches(matches)

    if changed:
        MATCHES_FILE.write_text(
            json.dumps(
                matches,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        log("matches.json a été mis à jour")
    else:
        log("Aucun changement officiel détecté")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())