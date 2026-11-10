"""Regenerate app/data/wcag21.json from the W3C WCAG quickref data.

Keeps WCAG 2.1 level A and AA success criteria only (the v1 audit scope).

Run from backend/: python scripts/build_wcag_data.py
"""

import json
import re
import urllib.request
from pathlib import Path

SOURCE = "https://raw.githubusercontent.com/w3c/wai-wcag-quickref/gh-pages/_data/wcag21.json"
OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "wcag21.json"


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def _details(details: list[dict]) -> list[str]:
    """Flatten a criterion's exceptions and notes into plain-text lines."""
    lines: list[str] = []
    for block in details:
        if block.get("text"):
            lines.append(_text(block["text"]))
        for item in block.get("items", []):
            label = f"{item['handle']}: " if item.get("handle") else ""
            lines.append(_text(label + item.get("text", "")))
    return lines


def main() -> None:
    with urllib.request.urlopen(SOURCE) as resp:
        data = json.load(resp)

    criteria = []
    for principle in data["principles"]:
        for guideline in principle["guidelines"]:
            for sc in guideline["successcriteria"]:
                if "2.1" not in sc["versions"] or sc["level"] not in ("A", "AA"):
                    continue
                criteria.append({
                    "num": sc["num"],
                    "name": sc["handle"],
                    "level": sc["level"],
                    "principle": principle["handle"],
                    "guideline": f"{guideline['num']} {guideline['handle']}",
                    "text": _text(sc["title"]),
                    "details": _details(sc.get("details", [])),
                    "url": f"https://www.w3.org/WAI/WCAG21/Understanding/{sc['id'].split(':')[1]}.html",
                })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(criteria, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(criteria)} criteria to {OUT}")


if __name__ == "__main__":
    main()
