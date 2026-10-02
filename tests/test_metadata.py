import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from tv90.adapters.tvmaze_metadata import (
    METADATA_CACHE_FILENAME,
    TVMAZE_SHOW_IDS,
    TVMAZE_USER_AGENT,
    EpisodeMetadataFetchError,
    TvmazeEpisodeMetadataSource,
    tvmaze_episodes_url,
)
from tv90.config import HARRY_SHOW_STEM, KIPPER_SHOW_STEM, OSWALD_SHOW_STEM
from tv90.ports.metadata import EpisodeMetadataNotFoundError

KIPPER_EPISODES_JSON = json.dumps(
    [
        {
            "name": "The Visitor",
            "season": 1,
            "number": 1,
            "summary": "<p>Keep warm in the snow.</p>",
        },
        {
            "name": "The Umbrella",
            "season": 1,
            "number": 2,
            "summary": None,
        },
    ]
)


class RecordingHttpGetter:
    def __init__(self, body: str) -> None:
        self.body = body
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: Mapping[str, str]) -> str:
        self.calls.append((url, dict(headers)))
        return self.body


def _forbidden_http(url: str, headers: Mapping[str, str]) -> str:
    raise AssertionError(f"must not call HTTP for {url} with {dict(headers)}")


def test_lookup_uses_injected_http_and_strips_html(tmp_path: Path) -> None:
    http = RecordingHttpGetter(KIPPER_EPISODES_JSON)
    source = TvmazeEpisodeMetadataSource(http, tmp_path / METADATA_CACHE_FILENAME)

    metadata = source.lookup(KIPPER_SHOW_STEM, 1, 1)

    assert metadata.title == "The Visitor"
    assert metadata.description == "Keep warm in the snow."
    assert "<p>" not in metadata.description
    assert len(http.calls) == 1
    url, headers = http.calls[0]
    assert url == tvmaze_episodes_url(TVMAZE_SHOW_IDS[KIPPER_SHOW_STEM])
    assert headers["User-Agent"] == TVMAZE_USER_AGENT


def test_second_lookup_does_not_call_http(tmp_path: Path) -> None:
    http = RecordingHttpGetter(KIPPER_EPISODES_JSON)
    source = TvmazeEpisodeMetadataSource(http, tmp_path / METADATA_CACHE_FILENAME)

    first = source.lookup(KIPPER_SHOW_STEM, 1, 1)
    second = source.lookup(KIPPER_SHOW_STEM, 1, 2)

    assert first.title == "The Visitor"
    assert second.title == "The Umbrella"
    assert second.description == ""
    assert len(http.calls) == 1


def test_cache_file_satisfies_a_new_source_without_http(tmp_path: Path) -> None:
    cache_path = tmp_path / METADATA_CACHE_FILENAME
    warming = TvmazeEpisodeMetadataSource(
        RecordingHttpGetter(KIPPER_EPISODES_JSON), cache_path
    )
    warming.lookup(KIPPER_SHOW_STEM, 1, 1)
    cached = TvmazeEpisodeMetadataSource(_forbidden_http, cache_path)

    metadata = cached.lookup(KIPPER_SHOW_STEM, 1, 2)

    assert metadata.title == "The Umbrella"
    assert cache_path.is_file()


def test_missing_episode_raises_not_found(tmp_path: Path) -> None:
    source = TvmazeEpisodeMetadataSource(
        RecordingHttpGetter(KIPPER_EPISODES_JSON),
        tmp_path / METADATA_CACHE_FILENAME,
    )

    with pytest.raises(EpisodeMetadataNotFoundError) as caught:
        source.lookup(KIPPER_SHOW_STEM, 9, 99)

    assert caught.value.show_stem == KIPPER_SHOW_STEM
    assert caught.value.season_number == 9
    assert caught.value.episode_number == 99


def test_unknown_show_stem_raises_not_found_without_http(tmp_path: Path) -> None:
    source = TvmazeEpisodeMetadataSource(
        _forbidden_http, tmp_path / METADATA_CACHE_FILENAME
    )

    with pytest.raises(EpisodeMetadataNotFoundError):
        source.lookup("NotAShow", 1, 1)


def test_http_failure_raises_fetch_error(tmp_path: Path) -> None:
    def fail(url: str, headers: Mapping[str, str]) -> str:
        raise OSError("network down")

    source = TvmazeEpisodeMetadataSource(fail, tmp_path / METADATA_CACHE_FILENAME)

    with pytest.raises(EpisodeMetadataFetchError):
        source.lookup(KIPPER_SHOW_STEM, 1, 1)


def test_invalid_json_raises_fetch_error(tmp_path: Path) -> None:
    source = TvmazeEpisodeMetadataSource(
        RecordingHttpGetter("not-json"), tmp_path / METADATA_CACHE_FILENAME
    )

    with pytest.raises(EpisodeMetadataFetchError):
        source.lookup(KIPPER_SHOW_STEM, 1, 1)


def test_non_array_json_raises_fetch_error(tmp_path: Path) -> None:
    source = TvmazeEpisodeMetadataSource(
        RecordingHttpGetter(json.dumps({"name": "nope"})),
        tmp_path / METADATA_CACHE_FILENAME,
    )

    with pytest.raises(EpisodeMetadataFetchError):
        source.lookup(KIPPER_SHOW_STEM, 1, 1)


def test_corrupt_cache_is_ignored_and_refetched(tmp_path: Path) -> None:
    cache_path = tmp_path / METADATA_CACHE_FILENAME
    cache_path.write_text("{not json", encoding="utf-8")
    http = RecordingHttpGetter(KIPPER_EPISODES_JSON)
    source = TvmazeEpisodeMetadataSource(http, cache_path)

    metadata = source.lookup(KIPPER_SHOW_STEM, 1, 1)

    assert metadata.title == "The Visitor"
    assert len(http.calls) == 1


def test_read_only_source_does_not_write_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / METADATA_CACHE_FILENAME
    http = RecordingHttpGetter(KIPPER_EPISODES_JSON)
    source = TvmazeEpisodeMetadataSource(http, cache_path, writable=False)

    metadata = source.lookup(KIPPER_SHOW_STEM, 1, 1)

    assert metadata.title == "The Visitor"
    assert len(http.calls) == 1
    assert not cache_path.exists()


def test_writable_source_writes_cache_after_fetch(tmp_path: Path) -> None:
    cache_path = tmp_path / METADATA_CACHE_FILENAME
    http = RecordingHttpGetter(KIPPER_EPISODES_JSON)
    source = TvmazeEpisodeMetadataSource(http, cache_path, writable=True)

    source.lookup(KIPPER_SHOW_STEM, 1, 1)

    assert cache_path.is_file()


def test_read_only_source_reads_existing_cache_without_http(tmp_path: Path) -> None:
    cache_path = tmp_path / METADATA_CACHE_FILENAME
    warming = TvmazeEpisodeMetadataSource(
        RecordingHttpGetter(KIPPER_EPISODES_JSON), cache_path, writable=True
    )
    warming.lookup(KIPPER_SHOW_STEM, 1, 1)
    source = TvmazeEpisodeMetadataSource(_forbidden_http, cache_path, writable=False)

    metadata = source.lookup(KIPPER_SHOW_STEM, 1, 2)

    assert metadata.title == "The Umbrella"
    assert cache_path.is_file()


def test_show_ids_cover_the_three_cartoon_stems() -> None:
    assert set(TVMAZE_SHOW_IDS) == {
        KIPPER_SHOW_STEM,
        OSWALD_SHOW_STEM,
        HARRY_SHOW_STEM,
    }
    assert TVMAZE_SHOW_IDS[KIPPER_SHOW_STEM] == 18014
    assert TVMAZE_SHOW_IDS[OSWALD_SHOW_STEM] == 43569
    assert TVMAZE_SHOW_IDS[HARRY_SHOW_STEM] == 69573
