from __future__ import annotations

import html
import json
import re
import sys
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

MATCHES_FILE = Path("matches.json")

# Sources officielles connues + découverte automatique via les sitemaps FFF.
FIXED_SOURCES = [
    "https://www.fff.fr/article/17019-j1-j2-j3-la-programmation-officialisee.html",
    "https://www.fff.fr/article/17022-le-calendrier-2026-2027-est-servi.html",
    "https://ligue1.com/fr/articles/l1_article_5407-ligue-3-le-calendrier-de-la-saison-2026-2027",
]

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

MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))

VFC_ALIASES = [
    "vfc",
    "vendee fc",
    "vendee football club",
    "vendee fc la roche",
    "vendee fc la roche yon",
    "vendee fc la roche/yon",
    "la roche sur yon",
    "la roche-sur-yon",
    "la roche/yon",
    "la roche yon",
    "la roche vf",
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

ROUND_WORDS = {
    1: ["premiere journee", "1ere journee", "1re journee", "j1", "coup d'envoi", "coup d’envoi"],
    2: ["deuxieme journee", "2e journee", "2eme journee", "j2"],
    3: ["troisieme journee", "3e journee", "3eme journee", "j3"],
    4: ["quatrieme journee", "4e journee", "4eme journee", "j4"],
    5: ["cinquieme journee", "5e journee", "5eme journee", "j5"],
    6: ["sixieme journee", "6e journee", "6eme journee", "j6"],
    7: ["septieme journee", "7e journee", "7eme journee", "j7"],
    8: ["huitieme journee", "8e journee", "8eme journee", "j8"],
    9: ["neuvieme journee", "9e journee", "9eme journee", "j9"],
    10: ["dixieme journee", "10e journee", "10eme journee", "j10"],
}

for n in range(11, 35):
    ROUND_WORDS[n] = [f"j{n}", f"{n}e journee", f"{n}eme journee"]


def log(message: str) -> None:
    print(message, flush=True)


def normalize(value: str) -> str:
    value = value.replace("œ", "oe").replace("Œ", "oe").replace("’", "'")
    value = unicodedata.normalize("NFD", value)
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = value.lower()
    value = re.sub(r"[^a-z0-9/:' -]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def fetch(url: str, timeout: int = 20) -> str | None:
    try:
        req = Request(
            url,
            headers={
                "User-Agent": "VFC-Calendar-Updater/1.0 (+https://github.com/Anto-VFC/vfc-calendrier)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        with urlopen(req, timeout=timeout) as response:
            content = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return content.decode(charset, errors="replace")
    except (HTTPError, URLError, TimeoutError) as exc:
        log(f"Source inaccessible ignorée: {url} ({exc})")
        return None


def html_to_text(raw: str) -> str:
    raw = re.sub(r"<script\b.*?</script>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<style\b.*?</style>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"</(p|li|h1|h2|h3|h4|div|section|article|tr)>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
    raw = re.sub(r"\n\s*\n+", "\n", raw)
    return raw.strip()


def extract_title(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:30]:
        if 8 <= len(line) <= 120 and not line.lower().startswith(("univers", "se connecter")):
            return line
    return lines[0] if lines else ""


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
            if "/article/" not in url:
                continue
            lower = url.lower()
            # On limite aux articles plausibles pour éviter de lire tout fff.fr.
            if any(k in lower for k in ["ligue-3", "programmation", "programme", "calendrier", "horaire", "j1", "j2", "j3", "j4", "j5", "j6", "j7", "j8", "j9"]):
                urls.add(url)
    return sorted(urls)


def candidate_sources() -> list[str]:
    urls = set(FIXED_SOURCES)
    urls.update(sitemap_urls())
    return sorted(urls)


def infer_year(month: int, existing: date | None = None) -> int:
    if existing:
        # On reste proche de la saison du match existant.
        return existing.year
    return 2027 if month <= 6 else 2026


def parse_date(day: int, month_name: str, year_text: str | None, existing: date | None = None) -> date | None:
    month = MONTHS.get(month_name.lower()) or MONTHS.get(normalize(month_name))
    if not month:
        return None
    year = int(year_text) if year_text else infer_year(month, existing)
    try:
        return date(year, month, int(day))
    except ValueError:
        return None


def find_date_times(context: str, existing: date | None = None) -> list[tuple[date, str]]:
    candidates: list[tuple[date, str]] = []

    patterns = [
        # vendredi 7 août 2026 à 20h45 / vendredi 14 août à 19 heures
        rf"(?P<day>\d{{1,2}})(?:er)?\s+(?P<month>{MONTH_RE})(?:\s+(?P<year>20\d{{2}}))?.{{0,120}}?(?:a|à|de|,|:|-)?\s*(?P<hour>\d{{1,2}})\s*(?:h|:|heures?)\s*(?P<minute>\d{{2}})?",
        # 20h45 : vendredi 7 août 2026
        rf"(?P<hour>\d{{1,2}})\s*(?:h|:|heures?)\s*(?P<minute>\d{{2}})?.{{0,120}}?(?P<day>\d{{1,2}})(?:er)?\s+(?P<month>{MONTH_RE})(?:\s+(?P<year>20\d{{2}}))?",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, context, flags=re.I | re.S):
            d = parse_date(match.group("day"), match.group("month"), match.groupdict().get("year"), existing)
            if not d:
                continue
            hour = int(match.group("hour"))
            minute = int(match.group("minute") or 0)
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                candidates.append((d, f"{hour:02d}:{minute:02d}"))

    # Supprime les doublons en gardant l'ordre.
    unique: list[tuple[date, str]] = []
    seen = set()
    for item in candidates:
        if item not in seen:
            unique.append(item)
            seen.add(item)
    return unique


def best_candidate(candidates: list[tuple[date, str]], existing_date: str) -> tuple[date, str] | None:
    if not candidates:
        return None
    existing = datetime.strptime(existing_date, "%Y-%m-%d").date()
    candidates = sorted(candidates, key=lambda item: abs((item[0] - existing).days))
    best = candidates[0]
    # Évite de confondre une autre journée trop éloignée.
    if abs((best[0] - existing).days) > 10:
        return None
    return best


def aliases_for(opponent: str) -> list[str]:
    aliases = TEAM_ALIASES.get(opponent, [opponent])
    return [normalize(a) for a in aliases]


def contains_any(norm_context: str, aliases: list[str]) -> bool:
    return any(alias and alias in norm_context for alias in aliases)


def update_match(match: dict, new_date: date, new_time: str, source_url: str, reason: str) -> bool:
    changed = False
    date_text = new_date.isoformat()
    if match.get("date") != date_text:
        log(f"J{match['round']}: date {match.get('date')} -> {date_text}")
        match["date"] = date_text
        changed = True
    if match.get("time") != new_time:
        log(f"J{match['round']}: heure {match.get('time')} -> {new_time}")
        match["time"] = new_time
        changed = True
    if changed or not match.get("official"):
        match["official"] = True
        match["note"] = f"Horaire officialisé automatiquement ({reason})"
        match["source_url"] = source_url
        match["last_checked"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    return changed


def update_from_source(matches: list[dict], url: str, text: str) -> bool:
    changed = False
    norm = normalize(text)

    if "ligue 3" not in norm and "la roche" not in norm and "vendee fc" not in norm:
        return False
    if not any(k in norm for k in ["programmation", "programme", "programmee", "programme tv", "calendrier", "horaire", "journee"]):
        return False

    # 1) Détection précise : ligne/zone qui contient le VFC + l'adversaire.
    for match in matches:
        existing = datetime.strptime(match["date"], "%Y-%m-%d").date()
        opp_aliases = aliases_for(match["opponent"])
        positions: list[int] = []

        for alias in opp_aliases:
            for m in re.finditer(re.escape(alias), norm):
                start = max(0, m.start() - 450)
                end = min(len(norm), m.end() + 450)
                window_norm = norm[start:end]
                if contains_any(window_norm, [normalize(a) for a in VFC_ALIASES]):
                    positions.append(m.start())

        for pos in positions[:5]:
            context = text[max(0, pos - 700): min(len(text), pos + 700)]
            cand = best_candidate(find_date_times(context, existing), match["date"])
            if cand:
                changed |= update_match(match, cand[0], cand[1], url, "source officielle FFF/LFP")
                break

    # 2) Détection par journée : utile quand un article annonce un horaire commun pour toute une journée.
    for match in matches:
        existing = datetime.strptime(match["date"], "%Y-%m-%d").date()
        round_no = int(match["round"])
        round_aliases = ROUND_WORDS.get(round_no, [f"j{round_no}", f"{round_no}e journee"])
        found_positions: list[int] = []

        for alias in round_aliases:
            # Pour j1, évite de matcher j10/j11.
            pattern = rf"(?<![a-z0-9]){re.escape(normalize(alias))}(?![a-z0-9])"
            for m in re.finditer(pattern, norm):
                found_positions.append(m.start())

        for pos in found_positions[:5]:
            context = text[max(0, pos - 350): min(len(text), pos + 650)]
            cand = best_candidate(find_date_times(context, existing), match["date"])
            if cand:
                changed |= update_match(match, cand[0], cand[1], url, "programmation de la journée")
                break

    return changed


def main() -> int:
    if not MATCHES_FILE.exists():
        log("matches.json introuvable")
        return 1

    matches = json.loads(MATCHES_FILE.read_text(encoding="utf-8"))
    sources = candidate_sources()
    log(f"Sources à vérifier: {len(sources)}")

    changed = False
    for url in sources:
        raw = fetch(url)
        if not raw:
            continue
        text = html_to_text(raw)
        title = extract_title(text)
        if update_from_source(matches, url, text):
            log(f"Mise à jour depuis: {title} / {url}")
            changed = True
        time.sleep(0.2)

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
