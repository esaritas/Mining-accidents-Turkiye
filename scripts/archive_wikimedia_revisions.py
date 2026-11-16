"""Archive the Wikimedia revisions behind the published citations.

Role in the evidence flow: verifiability of source documents. Every Wikipedia
and Wikidata page keeps its full history, so the revision that was current
when a citation was retrieved can be fetched again at any later date. This
script does that for every Wikimedia citation in the public export, stores the
revision text under ``data/archive/`` (Wikidata is CC0, Wikipedia text is
CC BY-SA, both permit redistribution with attribution) and writes an index
with the revision id, its hash and a permanent link.

It was written after the working database and its raw retrievals were lost on
2026-11-11. The index lets a restored document carry a real content hash and a
link that will always show the text the citation was read from. It is
re-runnable: a revision already archived is not fetched again.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import urllib.parse
from pathlib import Path

from mining_accidents.adapters.wikidata import _http_get
from mining_accidents.database import utc_now_iso
from mining_accidents.provenance import sha256_bytes

PUBLIC_DIR = Path("data/public")
ARCHIVE_DIR = Path("data/archive")
INDEX_PATH = ARCHIVE_DIR / "index.json"
_HOSTS = re.compile(r"^https://((?:[a-z]+\.wikipedia|www\.wikidata)\.org)/wiki/(.+)$")


def _citations() -> list[tuple[str, str]]:
    """Distinct (url, retrieved_at) pairs cited to a Wikimedia page."""
    pairs: set[tuple[str, str]] = set()
    for name in ("sources.csv", "environmental_sources.csv"):
        with (PUBLIC_DIR / name).open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if _HOSTS.match(row["url"]) and row["retrieved_at"]:
                    pairs.add((row["url"], row["retrieved_at"]))
    return sorted(pairs)


def _revision_at(host: str, title: str, moment: str) -> dict:
    payload = _http_get(
        f"https://{host}/w/api.php",
        {
            "action": "query",
            "prop": "revisions",
            "titles": title,
            "rvprop": "ids|timestamp|content",
            "rvslots": "main",
            "rvstart": moment,
            "rvdir": "older",
            "rvlimit": "1",
            "format": "json",
            "formatversion": "2",
        },
    )
    page = json.loads(payload)["query"]["pages"][0]
    if "revisions" not in page:
        raise RuntimeError(f"{host}: no revision of {title!r} at or before {moment}")
    revision = page["revisions"][0]
    return {
        "revision_id": revision["revid"],
        "revision_timestamp": revision["timestamp"],
        "content": revision["slots"]["main"]["content"],
    }


def main() -> int:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    index = json.loads(INDEX_PATH.read_text("utf-8")) if INDEX_PATH.exists() else []
    known = {(entry["url"], entry["retrieved_at"]) for entry in index}
    for url, retrieved_at in _citations():
        if (url, retrieved_at) in known:
            continue
        host, quoted = _HOSTS.match(url).groups()  # type: ignore[union-attr]
        title = urllib.parse.unquote(quoted).replace("_", " ")
        revision = _revision_at(host, title, retrieved_at)
        data = revision["content"].encode("utf-8")
        extension = "json" if host == "www.wikidata.org" else "wikitext"
        slug = re.sub(r"[^0-9A-Za-zÇĞİÖŞÜçğıöşü]+", "_", title).strip("_")
        path = ARCHIVE_DIR / host / f"{slug}.{revision['revision_id']}.{extension}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        index.append(
            {
                "url": url,
                "retrieved_at": retrieved_at,
                "host": host,
                "title": title,
                "revision_id": revision["revision_id"],
                "revision_timestamp": revision["revision_timestamp"],
                "sha256": sha256_bytes(data),
                "path": path.as_posix(),
                "permalink": f"https://{host}/w/index.php?"
                + urllib.parse.urlencode({"title": title.replace(" ", "_")})
                + f"&oldid={revision['revision_id']}",
                "archived_at": utc_now_iso(),
            }
        )
        print(f"archived {host} {title} rev {revision['revision_id']}")
        index.sort(key=lambda entry: (entry["url"], entry["retrieved_at"]))
        INDEX_PATH.write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"{len(index)} revisions in {INDEX_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
