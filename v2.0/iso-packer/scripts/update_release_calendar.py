#!/usr/bin/env python3
"""Refresh the local Blu-ray release calendar cache."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from release_calendar_fetcher import BLURAY_RELEASE_URL, refresh_release_calendar_cache


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh data/release_calendar.json from Blu-ray.com")
    parser.add_argument("--limit", type=int, default=12, help="Maximum release items to cache")
    parser.add_argument("--url", default=BLURAY_RELEASE_URL, help="Blu-ray.com release calendar URL")
    parser.add_argument("--output", default=str(ROOT / "data" / "release_calendar.json"), help="JSON cache path")
    parser.add_argument("--dry-run", action="store_true", help="print parsed payload without writing")
    parser.add_argument("--no-tmdb", action="store_true", help="skip TMDB title/poster enrichment")
    parser.add_argument("--tmdb-api-domain", default="", help="Override TMDB API domain, for example api.themoviedb.org")
    parser.add_argument("--tmdb-image-domain", default="", help="Override TMDB image domain, for example image.tmdb.org")
    args = parser.parse_args()
    tmdb_config = None
    if args.tmdb_api_domain or args.tmdb_image_domain:
        tmdb_config = {
            "enabled": True,
            "tmdb_api_domain": args.tmdb_api_domain,
            "tmdb_image_domain": args.tmdb_image_domain,
        }

    target = Path(args.output)
    if args.dry_run:
        from release_calendar_fetcher import build_payload, enrich_items_with_tmdb, fetch_bluray_release_items

        items = fetch_bluray_release_items(url=args.url, limit=args.limit)
        tmdb_meta = None
        if not args.no_tmdb:
            items, tmdb_meta = enrich_items_with_tmdb(items, tmdb_config=tmdb_config)
        payload = build_payload(items, source_url=args.url, tmdb=tmdb_meta)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    payload = refresh_release_calendar_cache(target, limit=args.limit, url=args.url, enrich_tmdb=not args.no_tmdb, tmdb_config=tmdb_config)
    print(json.dumps({
        "ok": True,
        "file": str(target),
        "count": len(payload.get("items", [])),
        "updated_at": payload.get("updated_at"),
        "fetched_at": payload.get("fetched_at"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
