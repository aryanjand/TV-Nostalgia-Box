"""TVMaze episode metadata. Tests inject HTTP; this adapter may write a cache file."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen

from tv90.config import HARRY_SHOW_STEM, LITTLE_BEAR_SHOW_STEM, OSWALD_SHOW_STEM
from tv90.ports.metadata import (
    EpisodeMetadata,
    EpisodeMetadataNotFoundError,
    HttpGetter,
    HttpHeaders,
)

# Confirmed 2026-10-01 against api.tvmaze.com search + /shows/{id}/episodes.
TVMAZE_SHOW_IDS = {
    LITTLE_BEAR_SHOW_STEM: 18005,
    OSWALD_SHOW_STEM: 43569,
    HARRY_SHOW_STEM: 69573,
}
TVMAZE_API_ROOT = "https://api.tvmaze.com"
TVMAZE_EPISODES_PATH_PREFIX = "/shows/"
TVMAZE_EPISODES_PATH_SUFFIX = "/episodes"
TVMAZE_USER_AGENT = "tv90/0.1 (90s Cable TV Nostalgia Box; maintenance tagger)"
TVMAZE_ACCEPT_HEADER = "application/json"
TVMAZE_USER_AGENT_HEADER = "User-Agent"
TVMAZE_ACCEPT_HEADER_NAME = "Accept"
HTTP_TIMEOUT_SECONDS = 30
HTTP_GET_METHOD = "GET"
TEXT_ENCODING = "utf-8"
JSON_INDENT_SPACES = 2
METADATA_CACHE_FILENAME = ".tv90-metadata-cache.json"
CACHE_TITLE_KEY = "title"
CACHE_DESCRIPTION_KEY = "description"
JSON_NAME_KEY = "name"
JSON_SEASON_KEY = "season"
JSON_NUMBER_KEY = "number"
JSON_SUMMARY_KEY = "summary"
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")

ShowCatalog = dict[tuple[int, int], EpisodeMetadata]


class EpisodeMetadataFetchError(Exception):
    """The online metadata HTTP call failed or returned an unusable body."""

    def __init__(self, show_stem: str, reason: str) -> None:
        self.show_stem = show_stem
        self.reason = reason
        super().__init__(f"{show_stem}: {reason}")


class TvmazeEpisodeMetadataSource:
    def __init__(self, http_get: HttpGetter, cache_path: Path) -> None:
        self._http_get = http_get
        self._cache_path = cache_path
        self._memory: dict[str, ShowCatalog] = {}

    def lookup(
        self, show_stem: str, season_number: int, episode_number: int
    ) -> EpisodeMetadata:
        if show_stem not in TVMAZE_SHOW_IDS:
            raise EpisodeMetadataNotFoundError(show_stem, season_number, episode_number)
        catalog = self._catalog_for(show_stem)
        try:
            return catalog[(season_number, episode_number)]
        except KeyError:
            raise EpisodeMetadataNotFoundError(
                show_stem, season_number, episode_number
            ) from None

    def _catalog_for(self, show_stem: str) -> ShowCatalog:
        if show_stem in self._memory:
            return self._memory[show_stem]
        cached = _read_show_from_cache(self._cache_path, show_stem)
        if cached is not None:
            self._memory[show_stem] = cached
            return cached
        fetched = self._fetch_show(show_stem)
        _write_show_to_cache(self._cache_path, show_stem, fetched)
        self._memory[show_stem] = fetched
        return fetched

    def _fetch_show(self, show_stem: str) -> ShowCatalog:
        show_id = TVMAZE_SHOW_IDS[show_stem]
        url = tvmaze_episodes_url(show_id)
        try:
            body = self._http_get(url, _tvmaze_headers())
        except (OSError, TimeoutError) as error:
            raise EpisodeMetadataFetchError(
                show_stem, "TVMaze request failed"
            ) from error
        return _catalog_from_tvmaze_body(show_stem, body)


def tvmaze_episodes_url(show_id: int) -> str:
    return (
        f"{TVMAZE_API_ROOT}{TVMAZE_EPISODES_PATH_PREFIX}{show_id}"
        f"{TVMAZE_EPISODES_PATH_SUFFIX}"
    )


def urlopen_http_get(url: str, headers: HttpHeaders) -> str:
    """CLI wires this getter; tests inject a fake instead."""
    request = Request(url, headers=dict(headers), method=HTTP_GET_METHOD)
    with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        raw: object = response.read()
    if not isinstance(raw, (bytes, bytearray)):
        raise TypeError("TVMaze response body must be bytes")
    return bytes(raw).decode(TEXT_ENCODING)


def build_tvmaze_metadata_source(cache_path: Path) -> TvmazeEpisodeMetadataSource:
    return TvmazeEpisodeMetadataSource(urlopen_http_get, cache_path)


def _tvmaze_headers() -> dict[str, str]:
    return {
        TVMAZE_USER_AGENT_HEADER: TVMAZE_USER_AGENT,
        TVMAZE_ACCEPT_HEADER_NAME: TVMAZE_ACCEPT_HEADER,
    }


def _catalog_from_tvmaze_body(show_stem: str, body: str) -> ShowCatalog:
    try:
        loaded: object = json.loads(body)
    except json.JSONDecodeError as error:
        raise EpisodeMetadataFetchError(
            show_stem, "TVMaze response is not JSON"
        ) from error
    if not isinstance(loaded, list):
        raise EpisodeMetadataFetchError(
            show_stem, "TVMaze response is not a JSON array"
        )
    catalog: ShowCatalog = {}
    for raw_episode in loaded:
        parsed = _episode_from_tvmaze_object(raw_episode)
        if parsed is None:
            continue
        season_number, episode_number, metadata = parsed
        key = (season_number, episode_number)
        if key not in catalog:
            catalog[key] = metadata
    return catalog


def _episode_from_tvmaze_object(
    raw_episode: object,
) -> tuple[int, int, EpisodeMetadata] | None:
    if not isinstance(raw_episode, dict):
        return None
    title = raw_episode.get(JSON_NAME_KEY)
    season_number = raw_episode.get(JSON_SEASON_KEY)
    episode_number = raw_episode.get(JSON_NUMBER_KEY)
    if not isinstance(title, str) or title == "":
        return None
    if not isinstance(season_number, int) or isinstance(season_number, bool):
        return None
    if not isinstance(episode_number, int) or isinstance(episode_number, bool):
        return None
    description = _description_from_summary(raw_episode.get(JSON_SUMMARY_KEY))
    return (
        season_number,
        episode_number,
        EpisodeMetadata(title=title, description=description),
    )


def _description_from_summary(summary: object) -> str:
    if summary is None:
        return ""
    if not isinstance(summary, str):
        return ""
    without_tags = HTML_TAG_PATTERN.sub(" ", html.unescape(summary))
    return WHITESPACE_PATTERN.sub(" ", without_tags).strip()


def _read_show_from_cache(cache_path: Path, show_stem: str) -> ShowCatalog | None:
    payload = _load_cache_payload(cache_path)
    if payload is None:
        return None
    raw_show: object = payload.get(show_stem)
    catalog = _catalog_from_cache_show(raw_show)
    if catalog is None:
        return None
    return catalog


def _write_show_to_cache(
    cache_path: Path, show_stem: str, catalog: ShowCatalog
) -> None:
    payload = _load_cache_payload(cache_path)
    if payload is None:
        payload = {}
    payload[show_stem] = _cache_show_from_catalog(catalog)
    cache_path.write_text(
        json.dumps(payload, indent=JSON_INDENT_SPACES, sort_keys=True) + "\n",
        encoding=TEXT_ENCODING,
    )


def _load_cache_payload(cache_path: Path) -> dict[str, object] | None:
    try:
        text = cache_path.read_text(encoding=TEXT_ENCODING)
    except OSError:
        return None
    try:
        loaded: object = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    return {str(key): value for key, value in loaded.items()}


def _catalog_from_cache_show(raw_show: object) -> ShowCatalog | None:
    if not isinstance(raw_show, dict):
        return None
    catalog: ShowCatalog = {}
    for season_key, season_value in raw_show.items():
        if not isinstance(season_value, dict):
            continue
        try:
            season_number = int(season_key)
        except (TypeError, ValueError):
            continue
        for episode_key, episode_value in season_value.items():
            metadata = _metadata_from_cache_entry(episode_value)
            if metadata is None:
                continue
            try:
                episode_number = int(episode_key)
            except (TypeError, ValueError):
                continue
            catalog[(season_number, episode_number)] = metadata
    return catalog


def _metadata_from_cache_entry(entry: object) -> EpisodeMetadata | None:
    if not isinstance(entry, dict):
        return None
    title = entry.get(CACHE_TITLE_KEY)
    description = entry.get(CACHE_DESCRIPTION_KEY)
    if not isinstance(title, str) or not isinstance(description, str):
        return None
    return EpisodeMetadata(title=title, description=description)


def _cache_show_from_catalog(
    catalog: ShowCatalog,
) -> dict[str, dict[str, dict[str, str]]]:
    nested: dict[str, dict[str, dict[str, str]]] = {}
    for (season_number, episode_number), metadata in catalog.items():
        season_map = nested.setdefault(str(season_number), {})
        season_map[str(episode_number)] = {
            CACHE_TITLE_KEY: metadata.title,
            CACHE_DESCRIPTION_KEY: metadata.description,
        }
    return nested
