from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
    parts: list[str] = []
    current = ""

    for character in line:
        candidate = current + character
        if len(candidate.encode("utf-8")) > 75:
            parts.append(current)
            current = " " + character
        else:
            current = candidate

    parts.append(current)
    return "\r\n".join(parts)


def add_property(lines: list[str], key: str, value: str) -> None:
    lines.append(fold_line(f"{key}:{ics_escape(value)}"))


def generate() -> None:
    matches = json.loads(Path("matches.json").read_text(encoding="utf-8"))
    OUTPUT_DIR.mkdir(exist_ok=True)

    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Anto VFC//Calendrier Ligue 3 2026-2027//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{CAL_NAME}",
        f"X-WR-TIMEZONE:{TZID}",
        "X-APPLE-CALENDAR-COLOR:#E30613",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
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
        start = datetime.strptime(
            f"{match['date']} {match['time']}",
            "%Y-%m-%d %H:%M",
        )
        end = start + timedelta(hours=2)

        round_number = int(match["round"])
        opponent = str(match["opponent"])
        home = bool(match["home"])

        summary = (
            f"🏠 VFC - {opponent}"
            if home
            else f"✈️ {opponent} - VFC"
        )
        home_text = "Domicile" if home else "Extérieur"
        official_text = (
            "Date et horaire officialisés."
            if match.get("official")
            else "Date ou horaire encore susceptible d'être modifié."
        )

        description = (
            f"J{round_number} - Ligue 3 2026-2027\n"
            f"{TEAM_FULL} / {opponent}\n"
            f"{home_text}\n"
            f"{official_text}"
        )

        if match.get("source_url"):
            description += f"\nSource : {match['source_url']}"

        # UID volontairement stable : il ne contient ni la date ni l'heure.
        # Apple met donc à jour le même événement lors d'un changement.
        uid = f"vfc-ligue3-2026-2027-j{round_number:02d}@anto-vfc.github.io"

        lines.extend([
            "BEGIN:VEVENT",
            fold_line(f"UID:{uid}"),
            f"DTSTAMP:{dtstamp}",
            f"SEQUENCE:{int(match.get('sequence', 0))}",
            f"DTSTART;TZID={TZID}:{start.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND;TZID={TZID}:{end.strftime('%Y%m%dT%H%M%S')}",
        ])

        add_property(lines, "SUMMARY", summary)
        add_property(
            lines,
            "LOCATION",
            match.get(
                "location",
                "Stade Henri-Desgrange, La Roche-sur-Yon"
                if home else "Extérieur",
            ),
        )
        add_property(lines, "DESCRIPTION", description)
        add_property(
            lines,
            "CATEGORIES",
            f"{home_text},Ligue 3,VFC",
        )

        lines.extend([
            "TRANSP:OPAQUE",
            "STATUS:CONFIRMED",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")

    OUTPUT_FILE.write_text(
        "\r\n".join(lines) + "\r\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / ".nojekyll").write_text("", encoding="utf-8")
    (OUTPUT_DIR / "index.html").write_text(
        """<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Calendrier VFC Ligue 3 2026-2027</title>
</head>
<body>
  <h1>Calendrier VFC Ligue 3 2026-2027</h1>
  <p><a href="vfc-ligue3.ics">S'abonner au calendrier VFC</a></p>
</body>
</html>
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    generate()
