import json

from tv90.adapters.enriched_metadata import WikipediaEnrichedMetadataSource
from tv90.adapters.fake_metadata import FakeEpisodeMetadataSource
from tv90.adapters.wikipedia_plots import (
    WikipediaPlotIndex,
    normalize_plot_title,
    parse_episode_list_plots,
)
from tv90.application.tagging import packaged_keyword_rules, preview_tags
from tv90.domain.filename import parse_filename
from tv90.ports.metadata import EpisodeMetadata

KIPPER_TEMPLATE = """
{{Episode list
| EpisodeNumber=1
| Title=The Visitor
| ShortSummary=Kipper lets a lost gosling stay during a [[thunderstorm]].
}}
{{Episode list
| EpisodeNumber=9
| Title=Snowy Day
| ShortSummary=Kipper and Tiger enjoy playing in the snow.
}}
"""

OSWALD_TEMPLATE = """
{{Episode list
 |Title=Chasing the Ice-Cream Truck"<hr>"The Camping Trip
 |EpisodeNumber=1
 |ShortSummary=Oswald chases Johnny's ice cream truck. / They go camping.
}}
"""

UMBRELLA_TEMPLATE = (
    "{{Episode list|Title=The Umbrella"
    "|ShortSummary=Kipper uses an umbrella as a fishing rod.}}"
)


def test_parse_kipper_short_summaries_by_title() -> None:
    plots = parse_episode_list_plots(KIPPER_TEMPLATE)

    assert plots[normalize_plot_title("The Visitor")].startswith("Kipper lets a lost")
    assert "thunderstorm" in plots[normalize_plot_title("The Visitor")]
    assert "snow" in plots[normalize_plot_title("Snowy Day")]


def test_parse_oswald_splits_paired_titles_and_plots() -> None:
    plots = parse_episode_list_plots(OSWALD_TEMPLATE)
    ice_cream = plots[normalize_plot_title("Chasing the Ice-Cream Truck")]

    assert "ice cream truck" in ice_cream
    assert "camping" in plots[normalize_plot_title("The Camping Trip")]


def test_normalize_matches_punctuation_differences() -> None:
    assert normalize_plot_title("Echo, Echo") == normalize_plot_title("Echo Echo")
    assert normalize_plot_title("Water, Water Everywhere!") == normalize_plot_title(
        "Water Water Everywhere"
    )


def test_enricher_fills_empty_tvmaze_description() -> None:
    inner = FakeEpisodeMetadataSource(
        {("Kipper", 1, 2): EpisodeMetadata("The Umbrella", "")}
    )
    plots = WikipediaPlotIndex(_plot_http(KIPPER_TEMPLATE))
    plots._by_show["Kipper"] = parse_episode_list_plots(UMBRELLA_TEMPLATE)
    source = WikipediaEnrichedMetadataSource(inner, plots)

    metadata = source.lookup("Kipper", 1, 2)

    assert metadata.title == "The Umbrella"
    assert "umbrella" in metadata.description


def test_enricher_keeps_tvmaze_description() -> None:
    inner = FakeEpisodeMetadataSource(
        {("Kipper", 1, 1): EpisodeMetadata("The Visitor", "Keep warm in the snow.")}
    )
    plots = WikipediaPlotIndex(_forbidden_http)
    source = WikipediaEnrichedMetadataSource(inner, plots)

    metadata = source.lookup("Kipper", 1, 1)

    assert metadata.description == "Keep warm in the snow."


def test_wiki_plot_tags_kipper_from_description() -> None:
    inner = FakeEpisodeMetadataSource(
        {("Kipper", 1, 1): EpisodeMetadata("The Visitor", "")}
    )
    plots = WikipediaPlotIndex(_forbidden_http)
    plots._by_show["Kipper"] = {
        normalize_plot_title("The Visitor"): (
            "Kipper lets a lost gosling stay at his house during a night thunderstorm."
        )
    }
    source = WikipediaEnrichedMetadataSource(inner, plots)

    preview = preview_tags(
        (parse_filename("Kipper_S01E01.mp4"),), source, packaged_keyword_rules()
    )

    assert preview.rows[0].proposed_tags == ("NIGHT",)


def test_harry_season_two_fallback_uses_wiki_plots() -> None:
    plots = WikipediaPlotIndex(_forbidden_http)
    plots._by_show["Harry"] = {
        normalize_plot_title("I See a Seashell!"): (
            "Harry finds a seashell at the beach and takes it to Dino-World."
        ),
        normalize_plot_title("Jump"): "Harry learns to jump.",
    }
    source = WikipediaEnrichedMetadataSource(FakeEpisodeMetadataSource({}), plots)

    preview = preview_tags(
        (parse_filename("Harry_S02E10.mp4"),), source, packaged_keyword_rules()
    )

    assert preview.rows[0].proposed_tags == ("SUMMER",)
    assert "beach" in source.description_for_title("Harry", preview.rows[0].title)


def test_wikipedia_http_failure_leaves_empty_plots() -> None:
    def fail(url: str, headers: dict[str, str]) -> str:
        raise OSError("network down")

    index = WikipediaPlotIndex(fail)

    assert index.description_for_title("Kipper", "The Visitor") == ""


def test_wikipedia_non_parse_json_is_empty() -> None:
    index = WikipediaPlotIndex(lambda url, headers: json.dumps([1, 2, 3]))

    assert index.description_for_title("Kipper", "The Visitor") == ""


def _plot_http(wikitext: str):
    body = json.dumps({"parse": {"wikitext": wikitext}})

    def getter(url: str, headers: dict[str, str]) -> str:
        return body

    return getter


def _forbidden_http(url: str, headers: dict[str, str]) -> str:
    raise AssertionError(f"must not call HTTP for {url}")
