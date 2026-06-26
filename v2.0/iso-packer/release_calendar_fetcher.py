#!/usr/bin/env python3
"""Blu-ray release calendar fetcher.

The homepage reads a local JSON cache. This module refreshes that cache from
Blu-ray.com on demand, then optionally enriches names and posters from TMDB.
Manual Chinese review fields are preserved across refreshes.
"""

from __future__ import annotations

import html
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
from ast import literal_eval
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

BLURAY_RELEASE_URL = "https://www.blu-ray.com/movies/releasedates.php"
DEFAULT_TMDB_API_DOMAIN = "api.themoviedb.org"
DEFAULT_TMDB_IMAGE_DOMAIN = "image.tmdb.org"
USER_AGENT = "ISO-Packer/2.0 local release calendar refresh"

MOVIE_BLOCK_RE = re.compile(r"movies\[\d+\]\s*=\s*\{(.*?)\};", re.S)
FIELD_RE = re.compile(r"(\w+):\s*('(?:\\.|[^'\\])*'|-?\d+)", re.S)
COVER_URL_RE = re.compile(
    r"https?:\/\/images\.static-bluray\.com\/movies\/covers\/[^\"'<>]+?(?:_large)?\.(?:jpg|jpeg|png)",
    re.I,
)

REVIEW_SOURCES = [
    {"name": "碟影", "usage": "中文碟讯与片单校对。"},
    {"name": "正版蓝光吧 / 百度贴吧", "usage": "社区碟讯参考，仅人工校对，不做稳定抓取依赖。"},
    {"name": "豆瓣豆列 / 厂牌片单", "usage": "厂牌、修复版和收藏向条目补充。"},
]

MANUAL_REVIEW_FIELDS = (
    "title_zh",
    "title_status",
    "poster_url",
    "poster_source",
    "poster_status",
    "review",
    "tmdb_id",
    "tmdb_title",
    "tmdb_original_title",
    "tmdb_status",
)

PLACEHOLDER_TITLE_STATUSES = {"待中文名", "中文名待校对", "显示原名"}
PLACEHOLDER_POSTER_STATUSES = {"待补海报", "海报待补", "外网海报"}


def has_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text or "")


def clean_tmdb_query(title: str) -> str:
    query = re.sub(r"\b(4K|UHD|Blu-ray|BD|SteelBook)\b", " ", title or "", flags=re.I)
    query = re.sub(r"\s+", " ", query).strip(" -:/")
    return query or (title or "").strip()


def normalize_domain(value: str, fallback: str) -> str:
    raw = str(value or "").strip().strip("/")
    if not raw:
        raw = fallback
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return f"https://{raw}"


def tmdb_settings(tmdb_config: Dict | None = None) -> Dict:
    cfg = tmdb_config or {}
    api_token = str(
        cfg.get("api_key")
        or cfg.get("tmdb_api_token")
        or os.environ.get("TMDB_API_KEY")
        or ""
    ).strip()
    bearer_token = str(
        cfg.get("bearer_token")
        or cfg.get("tmdb_bearer_token")
        or os.environ.get("TMDB_BEARER_TOKEN")
        or ""
    ).strip()
    enabled = bool(cfg.get("enabled", cfg.get("tmdb_api_enabled", bool(api_token or bearer_token))))
    return {
        "enabled": enabled,
        "api_key": api_token,
        "bearer_token": bearer_token,
        "api_base": normalize_domain(
            str(cfg.get("api_domain") or cfg.get("tmdb_api_domain") or ""),
            DEFAULT_TMDB_API_DOMAIN,
        ),
        "image_base": normalize_domain(
            str(cfg.get("image_domain") or cfg.get("tmdb_image_domain") or ""),
            DEFAULT_TMDB_IMAGE_DOMAIN,
        ),
    }


def tmdb_image_url(image_base: str, poster_path: str) -> str:
    return f"{image_base}/t/p/w342{poster_path}"


def tmdb_get_json(path: str, params: Dict, tmdb_config: Dict | None = None, timeout: int = 15) -> Dict:
    settings = tmdb_settings(tmdb_config)
    if not settings["enabled"] or (not settings["api_key"] and not settings["bearer_token"]):
        raise RuntimeError("TMDB 未配置 API Key")
    query = dict(params)
    if settings["api_key"]:
        query["api_key"] = settings["api_key"]
    url = f"{settings['api_base']}/3{path}?{urllib.parse.urlencode(query)}"
    headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if settings["bearer_token"]:
        headers["Authorization"] = f"Bearer {settings['bearer_token']}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def tmdb_search_movie(title: str, year: str = "", tmdb_config: Dict | None = None) -> Dict:
    query = clean_tmdb_query(title)
    attempts = []
    if year:
        attempts.append({"query": query, "year": year})
    attempts.append({"query": query})
    if query != title:
        attempts.append({"query": title})

    for params in attempts:
        payload = tmdb_get_json(
            "/search/movie",
            {
                "language": "zh-CN",
                "include_adult": "false",
                **params,
            },
            tmdb_config=tmdb_config,
        )
        results = payload.get("results") or []
        if results:
            return results[0]
    return {}


def apply_tmdb_result(item: Dict, result: Dict, tmdb_config: Dict | None = None) -> Dict:
    if not result:
        item["tmdb_status"] = item.get("tmdb_status") or "TMDB 未匹配"
        if not item.get("title_zh"):
            item["title_status"] = "显示原名"
        return item

    settings = tmdb_settings(tmdb_config)
    tmdb_title = str(result.get("title") or "").strip()
    original_title = str(result.get("original_title") or "").strip()
    poster_path = str(result.get("poster_path") or "").strip()
    item["tmdb_id"] = result.get("id") or item.get("tmdb_id") or ""
    item["tmdb_title"] = tmdb_title
    item["tmdb_original_title"] = original_title
    item["tmdb_status"] = "TMDB 已匹配"

    if not item.get("title_zh") and tmdb_title and has_cjk(tmdb_title):
        item["title_zh"] = tmdb_title
        item["title_status"] = "TMDB 中文名"
    elif not item.get("title_zh"):
        item["title_status"] = "显示原名"

    poster_source = str(item.get("poster_source") or "").strip()
    poster_is_manual = poster_source not in {"", "Blu-ray.com", "TMDB"}
    if poster_path and not poster_is_manual:
        item["poster_url"] = tmdb_image_url(settings["image_base"], poster_path)
        item["poster_source"] = "TMDB"
        item["poster_status"] = "TMDB 海报"
    return item


def enrich_items_with_tmdb(items: Iterable[Dict], tmdb_config: Dict | None = None) -> Tuple[List[Dict], Dict]:
    settings = tmdb_settings(tmdb_config)
    enriched = [dict(item) for item in items]
    if not settings["enabled"] or (not settings["api_key"] and not settings["bearer_token"]):
        for item in enriched:
            item.setdefault("tmdb_status", "TMDB 未配置")
            if not item.get("title_zh"):
                item["title_status"] = "显示原名"
        return enriched, {
            "enabled": False,
            "status": "not_configured",
            "message": "在系统设置填写 TMDB API Key 后可自动补中文名和海报",
            "matched_count": 0,
        }

    matched = 0
    errors: List[str] = []
    for item in enriched:
        try:
            result = tmdb_search_movie(str(item.get("title") or ""), str(item.get("year") or ""), tmdb_config=tmdb_config)
            if result:
                matched += 1
            apply_tmdb_result(item, result, tmdb_config=tmdb_config)
        except Exception as exc:
            item["tmdb_status"] = "TMDB 查询失败"
            if not item.get("title_zh"):
                item["title_status"] = "显示原名"
            errors.append(str(exc))
    return enriched, {
        "enabled": True,
        "status": "ok" if not errors else "partial",
        "message": "TMDB 补全完成" if not errors else f"TMDB 部分失败：{errors[0]}",
        "matched_count": matched,
    }


def decode_js_value(value: str):
    if value.startswith("'"):
        try:
            decoded = literal_eval(value)
        except Exception:
            decoded = value.strip("'")
        return html.unescape(str(decoded)).strip()
    try:
        return int(value)
    except ValueError:
        return value


def parse_movie_block(block: str) -> Dict:
    parsed: Dict = {}
    for key, value in FIELD_RE.findall(block):
        parsed[key] = decode_js_value(value)
    return parsed


def manual_review_index(path: Path) -> Dict[str, Dict]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    index: Dict[str, Dict] = {}
    for item in payload.get("items", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("source_url") or item.get("url") or item.get("title") or "").strip()
        if key:
            index[key] = item
    return index


def apply_manual_review_fields(items: Iterable[Dict], existing: Dict[str, Dict]) -> List[Dict]:
    merged: List[Dict] = []
    for item in items:
        key = str(item.get("source_url") or item.get("url") or item.get("title") or "").strip()
        manual = existing.get(key) or {}
        next_item = dict(item)
        for field in MANUAL_REVIEW_FIELDS:
            value = manual.get(field)
            if field == "title_status" and value in PLACEHOLDER_TITLE_STATUSES:
                value = None
            if field == "poster_status" and value in PLACEHOLDER_POSTER_STATUSES and next_item.get("poster_url"):
                value = None
            if value not in (None, ""):
                next_item[field] = value
        merged.append(next_item)
    return merged


def parse_release_date(value: str) -> tuple[str, str]:
    if not value:
        return "待定", ""
    try:
        parsed = datetime.strptime(value, "%B %d, %Y")
        return parsed.strftime("%m.%d"), parsed.date().isoformat()
    except ValueError:
        return value, ""


def item_release_date(item: Dict):
    raw_date = str(item.get("sort_date") or "")[:10]
    try:
        return datetime.strptime(raw_date, "%Y-%m-%d").date()
    except ValueError:
        return None


def select_release_window(items: List[Dict], limit: int) -> List[Dict]:
    today = datetime.now().date()
    upcoming = [item for item in items if (item_release_date(item) or today) >= today]
    recent = [item for item in items if (item_release_date(item) or today) < today]
    undated = [item for item in items if item_release_date(item) is None]
    if upcoming:
        selected = sorted(
            upcoming,
            key=lambda item: (item.get("sort_date") or "9999-12-31", item.get("popularity") or 999999, item.get("title") or ""),
        )
    else:
        selected = sorted(
            recent,
            key=lambda item: (
                item_release_date(item) or datetime.min.date(),
                -(item.get("popularity") or 999999),
                item.get("title") or "",
            ),
            reverse=True,
        )
    selected.extend([item for item in undated if item not in selected])
    return selected[:limit]


def source_url_for(movie: Dict) -> str:
    movie_id = movie.get("id")
    keywords = str(movie.get("title_keywords") or "").strip("/")
    if not movie_id or not keywords:
        return BLURAY_RELEASE_URL
    return f"https://www.blu-ray.com/movies/{keywords}-Blu-ray/{movie_id}/"


def specs_for(movie: Dict) -> str:
    title = f"{movie.get('title') or ''} {movie.get('title_keywords') or ''}"
    format_label = "4K UHD" if "4K" in title.upper() else "Blu-ray"
    parts = [format_label]
    for key in ("casing", "edition", "extended"):
        value = str(movie.get(key) or "").strip()
        if value:
            parts.append(value)
    year = str(movie.get("year") or "").strip()
    if year:
        parts.append(year)
    return " / ".join(parts[:4])


def normalize_movie(movie: Dict) -> Dict:
    date_label, date_iso = parse_release_date(str(movie.get("releasedate") or ""))
    title = str(movie.get("title") or movie.get("title_sort") or "未命名发行条目").strip()
    studio = str(movie.get("studio") or "Unknown").strip()
    artwork_url = str(movie.get("artworkurl") or "").strip()
    return {
        "date": date_label,
        "sort_date": date_iso or "9999-12-31",
        "release_label": date_iso or date_label,
        "studio": studio,
        "title": title,
        "title_zh": "",
        "title_status": "显示原名",
        "year": str(movie.get("year") or ""),
        "specs": specs_for(movie),
        "region": "US",
        "status": "外网抓取",
        "accent": "emerald" if "4K" in title.upper() else "blue",
        "source": "Blu-ray.com",
        "url": source_url_for(movie),
        "source_url": source_url_for(movie),
        "poster_url": artwork_url,
        "poster_source": "Blu-ray.com" if artwork_url else "",
        "poster_status": "外网海报" if artwork_url else "待补海报",
        "popularity": int(movie.get("popularity") or 9999),
        "review": "待中文校对",
    }


def fetch_text(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "latin-1"
        return response.read().decode(charset, "replace")


def fetch_cover_url(source_url: str, timeout: int = 12) -> str:
    if not source_url or source_url == BLURAY_RELEASE_URL:
        return ""
    try:
        html_text = fetch_text(source_url, timeout=timeout)
    except Exception:
        return ""
    matches = [html.unescape(match.group(0)) for match in COVER_URL_RE.finditer(html_text)]
    if not matches:
        return ""
    large = [url for url in matches if "_large." in url]
    return (large or matches)[0]


def parse_bluray_release_items(html_text: str, limit: int = 12) -> List[Dict]:
    raw_movies = [parse_movie_block(match.group(1)) for match in MOVIE_BLOCK_RE.finditer(html_text)]
    movies = [movie for movie in raw_movies if movie.get("title") and movie.get("releasedate")]
    normalized = [normalize_movie(movie) for movie in movies]
    normalized.sort(key=lambda item: (item.get("sort_date") or "9999-12-31", item.get("popularity") or 999999, item.get("title") or ""))
    seen = set()
    unique: List[Dict] = []
    for item in normalized:
        if any("\ufffd" in str(item.get(key, "")) for key in ("studio", "title", "specs")):
            continue
        key = (item["sort_date"], item["title"], item["studio"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    unique = select_release_window(unique, limit)
    for item in unique:
        if item.get("poster_url"):
            continue
        cover_url = fetch_cover_url(str(item.get("source_url") or item.get("url") or ""))
        if cover_url:
            item["poster_url"] = cover_url
            item["poster_source"] = "Blu-ray.com"
            item["poster_status"] = "外网海报"
    return unique


def fetch_bluray_release_items(url: str = BLURAY_RELEASE_URL, limit: int = 12, timeout: int = 25) -> List[Dict]:
    html_text = fetch_text(url, timeout=timeout)
    items = parse_bluray_release_items(html_text, limit=limit)
    if not items:
        raise RuntimeError("Blu-ray.com 页面未解析到发行条目")
    return items


def build_payload(items: Iterable[Dict], source_url: str = BLURAY_RELEASE_URL, tmdb: Dict | None = None) -> Dict:
    now = datetime.now().replace(microsecond=0)
    return {
        "version": 2,
        "updated_at": now.date().isoformat(),
        "fetched_at": now.isoformat(),
        "mode": "external_cache_with_review_layer",
        "generated_by": "scripts/update_release_calendar.py",
        "primary_source": {
            "name": "Blu-ray.com Release Calendar",
            "url": source_url,
            "usage": "外网基础发行日历源；首页读取本地缓存，不在渲染时实时抓取。",
        },
        "review_sources": REVIEW_SOURCES,
        "tmdb": tmdb or {
            "enabled": False,
            "status": "not_configured",
            "message": "在系统设置填写 TMDB API Key 后可自动补中文名和海报",
            "matched_count": 0,
        },
        "items": list(items),
    }


def write_payload(path: Path, payload: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temp_path = Path(handle.name)
        handle.write(text)
    temp_path.replace(path)


def refresh_release_calendar_cache(
    path: Path,
    limit: int = 12,
    url: str = BLURAY_RELEASE_URL,
    enrich_tmdb: bool = True,
    tmdb_config: Dict | None = None,
) -> Dict:
    items = fetch_bluray_release_items(url=url, limit=limit)
    items = apply_manual_review_fields(items, manual_review_index(path))
    tmdb_meta = None
    if enrich_tmdb:
        items, tmdb_meta = enrich_items_with_tmdb(items, tmdb_config=tmdb_config)
    payload = build_payload(items, source_url=url, tmdb=tmdb_meta)
    write_payload(path, payload)
    return payload
