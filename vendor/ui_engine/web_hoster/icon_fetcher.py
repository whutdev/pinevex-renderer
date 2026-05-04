"""Fetch Roblox asset thumbnails for Pinevex icon references in a tree."""

import hashlib
import io
import json
import re
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path

import requests
from PIL import Image

try:
    from tqdm import tqdm
except Exception:  # pragma: no cover - optional dependency
    tqdm = None

THUMBNAIL_API = "https://thumbnails.roblox.com/v1/assets"
THUMBNAIL_SIZE = "420x420"
# Roblox Thumbnail API bug: batch size 100 can swap neighboring URLs.
# Keep this aligned with data_processor/resolve_tokens.py.
THUMBNAIL_BATCH = 50
MAX_RETRIES = 5
THUMBNAIL_DELAY = 0.15
THUMBNAIL_READY_POLLS = 6
THUMBNAIL_READY_DELAY = 0.45
FETCH_WORKERS = 16
_STATE_FILE = "_thumbnail_state.json"
_PERMANENT_ERRORS = {"not_an_image"}
_SAVE_EVERY = 100

# Known placeholder image MD5 hashes (Roblox returns these instead of real thumbnails)
PLACEHOLDER_HASHES = {
    "a3dd54a897e452a2c6ea835194882df6",  # blank file placeholder from Roblox API
}

_RBXASSET_RE = re.compile(r"rbxassetid://(\d+)")
_ROBLOX_ASSET_URL_RE = re.compile(r"https?://(?:www\.)?roblox\.com/asset/\?id=(\d+)", re.IGNORECASE)
_ICON_TOKEN_RE = re.compile(r"<\|icon:(.+?)\|>")


def _extract_asset_id(value: str) -> str | None:
    """Extract numeric Roblox asset ID from supported image reference formats."""
    m = _RBXASSET_RE.search(value)
    if m:
        return m.group(1)
    m = _ROBLOX_ASSET_URL_RE.search(value)
    if m:
        return m.group(1)
    return None


@lru_cache(maxsize=1)
def _load_icon_manifest() -> dict:
    icon_library_dir = Path(__file__).resolve().parents[2] / "icon_library"
    manifest_path = icon_library_dir / "manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _asset_id_from_manifest_key(value: str) -> str | None:
    token_match = _ICON_TOKEN_RE.search(value)
    if token_match:
        value = token_match.group(1)

    manifest = _load_icon_manifest()
    normalized = value.replace("\\", "/")
    candidate_keys = [value, normalized]
    if normalized.lower().endswith(".png"):
        candidate_keys.append(normalized[:-4])
    else:
        candidate_keys.append(f"{normalized}.png")

    seen = set()
    for candidate in candidate_keys:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        entry = manifest.get(candidate)
        if not isinstance(entry, dict):
            continue
        image_id = entry.get("imageId")
        if isinstance(image_id, str):
            aid = _extract_asset_id(image_id)
            if aid:
                return aid
    return None


def collect_asset_ids(obj) -> set[str]:
    """Walk a PinevexObject tree and collect numeric IDs from icon fields."""
    ids = set()
    if isinstance(obj, dict):
        icon = obj.get("icon", "")
        if isinstance(icon, str):
            aid = _extract_asset_id(icon)
            if not aid:
                aid = _asset_id_from_manifest_key(icon)
            if aid:
                ids.add(aid)
        for v in obj.values():
            ids |= collect_asset_ids(v)
    elif isinstance(obj, list):
        for item in obj:
            ids |= collect_asset_ids(item)
    return ids


def _state_path(cache_dir: Path) -> Path:
    return cache_dir / _STATE_FILE


def _load_state(cache_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Load persistent thumbnail URL/failure cache."""
    path = _state_path(cache_dir)
    if not path.exists():
        return {}, {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        url_cache = raw.get("url_cache", {})
        fail_cache = raw.get("fail_cache", {})
        if not isinstance(url_cache, dict):
            url_cache = {}
        if not isinstance(fail_cache, dict):
            fail_cache = {}
        url_cache = {str(k): str(v) for k, v in url_cache.items() if v}
        fail_cache = {str(k): str(v) for k, v in fail_cache.items() if v}
        # Older runs treated placeholder responses as permanent failures.
        # They are often transient on Roblox's side, so do not preserve them.
        fail_cache = {k: v for k, v in fail_cache.items() if v != "placeholder"}
        return url_cache, fail_cache
    except Exception:
        return {}, {}


def _save_state(cache_dir: Path, url_cache: dict[str, str], fail_cache: dict[str, str]) -> None:
    """Persist thumbnail URL/failure cache atomically."""
    path = _state_path(cache_dir)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "version": 1,
        "url_cache": url_cache,
        "fail_cache": fail_cache,
    }
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def resolve_thumbnail_urls(asset_ids, session, show_tqdm: bool = False):
    """Batch-resolve asset IDs to CDN image URLs via the Thumbnail API.

    Processes up to THUMBNAIL_BATCH IDs per API call with rate limiting.
    Returns dict: asset_id -> image_url for thumbnails that reached Completed.
    """
    url_map = {}
    pending = [str(aid) for aid in asset_ids]

    for poll_idx in range(THUMBNAIL_READY_POLLS):
        if not pending:
            break

        batches = [pending[i:i + THUMBNAIL_BATCH] for i in range(0, len(pending), THUMBNAIL_BATCH)]
        batch_iter = batches
        if show_tqdm and tqdm is not None:
            batch_iter = tqdm(batches, desc="Resolving thumbnail URLs", unit="batch")

        still_pending: set[str] = set()
        for batch in batch_iter:
            ids_str = ",".join(batch)
            params = {
                "assetIds": ids_str,
                "returnPolicy": "PlaceHolder",
                "size": THUMBNAIL_SIZE,
                "format": "Png",
            }

            for attempt in range(MAX_RETRIES):
                try:
                    resp = session.get(THUMBNAIL_API, params=params, timeout=15)

                    if resp.status_code == 429:
                        delay = min(30, 2 ** attempt) + random.uniform(0, 1)
                        time.sleep(delay)
                        continue

                    resp.raise_for_status()
                    data = resp.json()

                    seen = set()
                    if "data" in data:
                        for item in data["data"]:
                            aid = str(item["targetId"])
                            seen.add(aid)
                            img_url = item.get("imageUrl")
                            state = item.get("state", "")
                            if img_url and state == "Completed":
                                url_map[aid] = img_url
                            elif state in ("Pending", "InReview", "Blocked"):
                                still_pending.add(aid)
                    still_pending.update(str(aid) for aid in batch if str(aid) not in seen and str(aid) not in url_map)
                    break

                except requests.exceptions.RequestException:
                    delay = min(30, 2 ** attempt) + random.uniform(0, 1)
                    time.sleep(delay)

            time.sleep(THUMBNAIL_DELAY)

        pending = sorted(aid for aid in still_pending if aid not in url_map)
        if pending and poll_idx < THUMBNAIL_READY_POLLS - 1:
            time.sleep(THUMBNAIL_READY_DELAY * (poll_idx + 1))

    return url_map


def fetch_image_from_url(aid, url, _session=None):
    """Fetch an image from a CDN URL. Returns (asset_id, bytes, error).

    Uses a fresh requests.Session per call to avoid cross-wired HTTP
    responses when called from multiple threads.
    """
    session = requests.Session()
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, timeout=15)

            if resp.status_code == 429:
                delay = min(30, 2 ** attempt) + random.uniform(0, 1)
                time.sleep(delay)
                continue

            resp.raise_for_status()

            # Validate it's an image and not a placeholder
            try:
                img = Image.open(io.BytesIO(resp.content))
                img.verify()
                content_hash = hashlib.md5(resp.content).hexdigest()
                if content_hash in PLACEHOLDER_HASHES:
                    return aid, None, "placeholder"
                return aid, resp.content, None
            except Exception:
                return aid, None, "not_an_image"

        except requests.exceptions.RequestException:
            delay = min(30, 2 ** attempt) + random.uniform(0, 1)
            time.sleep(delay)

    return aid, None, "max_retries_exceeded"


def fetch_icons(
    asset_ids: set[str],
    cache_dir: Path,
    workers: int = FETCH_WORKERS,
    show_tqdm: bool = False,
):
    """Download missing icon thumbnails from Roblox CDN.

    Yields progress messages as each icon is downloaded.
    Skips already-cached IDs.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    url_cache, fail_cache = _load_state(cache_dir)
    try:
        if show_tqdm:
            yield f"Thumbnail state: {len(url_cache)} URLs, {len(fail_cache)} failure entries"

        uncached = []
        skipped_permanent = 0
        for aid in sorted(asset_ids):
            cache_path = cache_dir / f"{aid}.png"
            if cache_path.exists() and cache_path.stat().st_size > 0:
                continue
            if fail_cache.get(aid) in _PERMANENT_ERRORS:
                skipped_permanent += 1
                continue
            uncached.append(aid)
        if skipped_permanent:
            yield f"Skipping {skipped_permanent} IDs with known permanent failures"
        if not uncached:
            return

        resolve_ids = [aid for aid in uncached if aid not in url_cache]
        resolved_this_run: set[str] = set()

        if resolve_ids:
            yield f"Resolving {len(resolve_ids)} thumbnail URLs..."
            session = requests.Session()
            resolved_map = resolve_thumbnail_urls(resolve_ids, session, show_tqdm=show_tqdm)
            yield f"URLs resolved: {len(resolved_map)}/{len(resolve_ids)}"
            for aid, url in resolved_map.items():
                url_cache[aid] = url
                fail_cache.pop(aid, None)
                resolved_this_run.add(aid)
            missing = [aid for aid in resolve_ids if aid not in resolved_map]
            for aid in missing:
                fail_cache[aid] = "no_thumbnail_url"
            _save_state(cache_dir, url_cache, fail_cache)
        else:
            yield "Resolving 0 thumbnail URLs (all from URL cache)"

        ids_to_fetch = [aid for aid in uncached if aid in url_cache]
        if not ids_to_fetch:
            return

        yield f"Fetching {len(ids_to_fetch)} images ({workers} threads)..."

        retry_resolve: list[str] = []
        processed = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(fetch_image_from_url, aid, url_cache[aid]): aid
                for aid in ids_to_fetch
            }
            futures_iter = as_completed(futures)
            if show_tqdm and tqdm is not None:
                futures_iter = tqdm(futures_iter, total=len(futures), desc="Downloading icons", unit="icon")
            for future in futures_iter:
                aid = futures[future]
                try:
                    fetched_aid, img_bytes, error = future.result()
                    if img_bytes:
                        (cache_dir / f"{fetched_aid}.png").write_bytes(img_bytes)
                        fail_cache.pop(fetched_aid, None)
                    elif error:
                        # Cached CDN URLs can expire; re-resolve once on transient failures.
                        if aid not in resolved_this_run and error not in _PERMANENT_ERRORS:
                            retry_resolve.append(aid)
                        else:
                            fail_cache[aid] = error
                            yield f"Skip rbxassetid://{aid}: {error}"
                except Exception as e:
                    err = str(e)
                    if aid not in resolved_this_run:
                        retry_resolve.append(aid)
                    else:
                        fail_cache[aid] = err
                        yield f"Skip rbxassetid://{aid}: {err}"
                processed += 1
                if processed % _SAVE_EVERY == 0:
                    _save_state(cache_dir, url_cache, fail_cache)

        if retry_resolve:
            retry_ids = sorted(set(retry_resolve))
            yield f"Re-resolving {len(retry_ids)} stale thumbnail URLs..."
            session = requests.Session()
            refresh_map = resolve_thumbnail_urls(retry_ids, session, show_tqdm=show_tqdm)
            for aid, url in refresh_map.items():
                url_cache[aid] = url
            missing_retry = [aid for aid in retry_ids if aid not in refresh_map]
            for aid in missing_retry:
                fail_cache[aid] = "no_thumbnail_url"
            _save_state(cache_dir, url_cache, fail_cache)

            retry_fetch_ids = [aid for aid in retry_ids if aid in refresh_map]
            if retry_fetch_ids:
                yield f"Retry-fetching {len(retry_fetch_ids)} images ({workers} threads)..."
                processed_retry = 0
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {
                        pool.submit(fetch_image_from_url, aid, url_cache[aid]): aid
                        for aid in retry_fetch_ids
                    }
                    futures_iter = as_completed(futures)
                    if show_tqdm and tqdm is not None:
                        futures_iter = tqdm(
                            futures_iter,
                            total=len(futures),
                            desc="Retry downloading icons",
                            unit="icon",
                        )
                    for future in futures_iter:
                        aid = futures[future]
                        try:
                            fetched_aid, img_bytes, error = future.result()
                            if img_bytes:
                                (cache_dir / f"{fetched_aid}.png").write_bytes(img_bytes)
                                fail_cache.pop(fetched_aid, None)
                            elif error:
                                fail_cache[aid] = error
                                yield f"Skip rbxassetid://{aid}: {error}"
                        except Exception as e:
                            fail_cache[aid] = str(e)
                            yield f"Skip rbxassetid://{aid}: {e}"
                        processed_retry += 1
                        if processed_retry % _SAVE_EVERY == 0:
                            _save_state(cache_dir, url_cache, fail_cache)
    finally:
        _save_state(cache_dir, url_cache, fail_cache)
