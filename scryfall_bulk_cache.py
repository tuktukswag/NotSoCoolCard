from __future__ import annotations

import json
import os
import time
from pathlib import Path

from tqdm import tqdm


DEFAULT_BULK_MAX_AGE_HOURS = 24
BULK_CACHE_DIRNAME = ".cache"
BULK_JSON_FILENAME = "scryfall_default_cards.json"
BULK_META_FILENAME = "scryfall_default_cards.meta.json"


def _cache_paths(base_dir: str | Path):
    root = Path(base_dir)
    cache_dir = root / BULK_CACHE_DIRNAME
    return cache_dir, cache_dir / BULK_JSON_FILENAME, cache_dir / BULK_META_FILENAME


def _load_json_file(path: Path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def _save_json_file(path: Path, payload) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    os.replace(tmp, path)


def _cache_is_fresh(path: Path, max_age_hours: float) -> bool:
    if not path.exists():
        return False
    max_age_seconds = max_age_hours * 3600
    age_seconds = time.time() - path.stat().st_mtime
    return age_seconds <= max_age_seconds


def load_default_cards_bulk(
    *,
    base_dir: str | Path,
    safe_get,
    tqdm_kwargs: dict,
    max_age_hours: float = DEFAULT_BULK_MAX_AGE_HOURS,
    prefer_cache: bool = True,
    force_refresh: bool = False,
):
    cache_dir, json_path, meta_path = _cache_paths(base_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    if not json_path.exists():
        print("No cached Scryfall bulk data found", flush=True)

    if prefer_cache and not force_refresh and _cache_is_fresh(json_path, max_age_hours):
        print(f"Using cached Scryfall bulk data: {json_path}", flush=True)
        return _load_json_file(json_path, [])

    print("Fetching Scryfall bulk-data index...", flush=True)
    bulk_index = safe_get(
        "https://api.scryfall.com/bulk-data",
        headers={"Accept": "application/json"},
        request_label="bulk-data index",
    )
    if not bulk_index:
        if json_path.exists():
            if force_refresh:
                print("Bulk-data index unavailable during refresh, using cached Scryfall bulk data", flush=True)
            else:
                print("Bulk-data index unavailable, using cached Scryfall bulk data", flush=True)
            return _load_json_file(json_path, [])
        raise RuntimeError("Could not fetch Scryfall bulk-data index")

    data = bulk_index.json().get("data", [])
    chosen = next((item for item in data if item.get("type") == "default_cards"), None)
    if not chosen or not chosen.get("download_uri"):
        if json_path.exists():
            if force_refresh:
                print("default_cards entry missing during refresh, using cached Scryfall bulk data", flush=True)
            else:
                print("default_cards entry missing, using cached Scryfall bulk data", flush=True)
            return _load_json_file(json_path, [])
        raise RuntimeError("Could not find Scryfall default_cards bulk file")

    meta = _load_json_file(meta_path, {})
    download_uri = chosen["download_uri"]
    if prefer_cache and not force_refresh and json_path.exists() and meta.get("download_uri") == download_uri:
        print(f"Using cached Scryfall bulk data: {json_path}", flush=True)
        return _load_json_file(json_path, [])

    print("Downloading Scryfall default_cards bulk file...", flush=True)
    response = safe_get(
        download_uri,
        headers={"Accept": "application/json"},
        timeout=120,
        stream=True,
        request_label="default_cards bulk download",
    )
    if not response:
        if json_path.exists():
            if force_refresh:
                print("Bulk download unavailable during refresh, using cached Scryfall bulk data", flush=True)
            else:
                print("Bulk download unavailable, using cached Scryfall bulk data", flush=True)
            return _load_json_file(json_path, [])
        raise RuntimeError(f"Could not download bulk JSON from {download_uri}")

    total = int(response.headers.get("Content-Length", 0))
    chunks = []
    with tqdm(
        total=total if total > 0 else None,
        desc="Downloading Scryfall bulk JSON",
        unit="B",
        unit_scale=True,
        **tqdm_kwargs,
    ) as pbar:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            chunks.append(chunk)
            pbar.update(len(chunk))

    raw = b"".join(chunks)
    payload = json.loads(raw.decode("utf-8"))
    _save_json_file(json_path, payload)
    _save_json_file(
        meta_path,
        {
            "download_uri": download_uri,
            "updated_at_unix": int(time.time()),
        },
    )
    return payload