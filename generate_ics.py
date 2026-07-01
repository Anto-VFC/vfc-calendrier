from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

CAL_NAME = "VFC Ligue 3 2026-2027"
TEAM = "VFC"
TEAM_FULL = "Vendée FC La Roche-sur-Yon"
TZID = "Europe/Paris"
OUTPUT_DIR = Path("public")
OUTPUT_FILE = OUTPUT_DIR / "vfc-ligue3.ics"


def ics_escape(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def fold_line(line: str) -> str:
    # RFC 5545: fold at 75 octets. Simple UTF-8-safe implementation.
    out = []
    current = ""
    for ch in line:
        if len((current + ch).encode("utf-8")) > 75:
            out.append(current)
            current = " " + ch
        else:
            current += ch
    out.append(current)
    return "\r\n".join(out)


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9àâäéèêëïîôöùûüçñ -]", "", value)
    value = value.replace("à", "a").replace("â", "a").replace("ä", "a")
    value = value.replace("é", "e").replace("è", "e").replace("ê", "e").replace("ë", "e")
    value = value.replace("ï", "i").replace("î", "i")
    value = value.replace("ô", "o").replace("ö", "o")
    value = value.replace("ù", "u").replace("û", "u").replace("ü", "u")
    value = value.replace("ç", "c").replace("ñ", "n")
    value = re.sub(r"\s+", "-", value).strip("-")
    return value


def add_prop(lines: list[str], key: str, value: str) -> None:
    lines.append(fold_line(f"{key}:{ics_escape(value)}"))


def generate() -> None:
    matches = json.loads(Path("matches.json").read_text(encoding="utf-8"))
    OUTPUT_DIR.mkdir(exist_ok=True)
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//VFC Calendar GitHub//VFC Ligue 3 2026-2027//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:" + CAL_NAME,
        "X-WR-TIMEZONE:" + TZID,
        "X-APPLE-CALENDAR-COLOR:#E30613",
        "BEGIN:VTIMEZONE",
        "TZID:Europe/Paris",
        "X-LIC-LOCATION:Europe/Paris",
        "BEGIN:DAYLIGHT",
        "TZOFFSETFROM:+0100",
        "TZOFFSETTO:+0200",
        "TZNAME:CEST",
        "DTSTART:19700329T020000",
        "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU",
        "END:DAYLIGHT",
        "BEGIN:STANDARD",
        "TZOFFSETFROM:+0200",
        "TZOFFSETTO:+0100",
        "TZNAME:CET",
        "DTSTART:19701025T030000",
        "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]

    for match in matches:
        start = datetime.strptime(match["date"] + " " + match["time"], "%Y-%m-%d %H:%M")
        end = start + timedelta(hours=2)
        opponent = match["opponent"]
        home = bool(match["home"])
        summary = f"🏠 {TEAM} - {opponent}" if home else f"✈️ {opponent} - {TEAM}"
        home_txt = "Domicile" if home else "Extérieur"
        official_note = "Horaire officialisé." if match.get("official") else "Horaire à confirmer : événement placé à l’heure indiquée par défaut."
        description = f"J{match['round']} - Ligue 3 2026-2027\n{TEAM_FULL} vs {opponent}\n{home_txt}\n{official_note}"
        uid = f"j{match['round']}-{match['date']}-{slugify(opponent)}@vfc-ligue3-2026-2027"
        lines.extend([
            "BEGIN:VEVENT",
            fold_line(f"UID:{uid}"),
            f"DTSTAMP:{dtstamp}",
            f"DTSTART;TZID={TZID}:{start.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND;TZID={TZID}:{end.strftime('%Y%m%dT%H%M%S')}",
        ])
        add_prop(lines, "SUMMARY", summary)
        add_prop(lines, "LOCATION", match.get("location", "Stade Henri-Desgrange, La Roche-sur-Yon" if home else "Extérieur"))
        add_prop(lines, "DESCRIPTION", description)
        add_prop(lines, "CATEGORIES", ("Domicile" if home else "Extérieur") + ",Ligue 3,VFC")
        lines.extend([
            "TRANSP:OPAQUE",
            "STATUS:CONFIRMED",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    OUTPUT_FILE.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")

    (OUTPUT_DIR / ".nojekyll").write_text("", encoding="utf-8")
    (OUTPUT_DIR / "index.html").write_text("""<!doctype html>
<html lang=\"fr\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>Calendrier VFC Ligue 3 2026-2027</title>
</head>
<body>
  <h1>Calendrier VFC Ligue 3 2026-2027</h1>
  <p>URL d’abonnement iPhone :</p>
  <p><a href=\"vfc-ligue3.ics\">vfc-ligue3.ics</a></p>
</body>
</html>
""", encoding="utf-8")


if __name__ == "__main__":
    generate()
