"""Episode ShortSummary text. Packaged JSON is the source; HTTP is optional."""

from __future__ import annotations

import json
import re
from importlib import resources
from urllib.parse import quote

from tv90.config import HARRY_SHOW_STEM, KIPPER_SHOW_STEM, OSWALD_SHOW_STEM
from tv90.ports.metadata import HttpGetter

WIKIPEDIA_PLOT_PAGES = {
    KIPPER_SHOW_STEM: "List_of_Kipper_episodes",
    OSWALD_SHOW_STEM: "Oswald_(TV_series)",
    HARRY_SHOW_STEM: "Harry_and_His_Bucket_Full_of_Dinosaurs",
}
WIKIPEDIA_PARSE_URL = (
    "https://en.wikipedia.org/w/api.php?action=parse&page={page}"
    "&prop=wikitext&format=json&formatversion=2&redirects=1"
)
WIKIPEDIA_USER_AGENT = "tv90/0.1 (90s Cable TV Nostalgia Box; maintenance tagger)"
WIKIPEDIA_ACCEPT_HEADER = "application/json"
TEMPLATE_OPEN = "{{"
TEMPLATE_CLOSE = "}}"
EPISODE_LIST_START = re.compile(r"\{\{\s*Episode list\b", re.IGNORECASE)
HR_SPLIT = re.compile(r'"?\s*<hr\s*/?>\s*"?', re.IGNORECASE)
WIKI_LINK = re.compile(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]")
WIKI_REF = re.compile(r"<ref\b[^>]*>.*?</ref>", re.IGNORECASE | re.DOTALL)
WIKI_BOLD = re.compile(r"'{2,}")
WIKI_TAG = re.compile(r"<[^>]+>")
NOTE_CUT = re.compile(r"\bNote:.*", re.IGNORECASE | re.DOTALL)
TITLE_SPLIT = " / "
WORD_PATTERN = re.compile(r"[a-z0-9]+")
TEXT_ENCODING = "utf-8"
JSON_WIKITEXT_KEY = "wikitext"
JSON_PARSE_KEY = "parse"
PLOTS_PACKAGE = "tv90.data"
PLOTS_FILENAME = "episode_plots.json"


def wikipedia_parse_url(page: str) -> str:
    return WIKIPEDIA_PARSE_URL.format(page=quote(page, safe="_()"))


def wikipedia_headers() -> dict[str, str]:
    return {
        "User-Agent": WIKIPEDIA_USER_AGENT,
        "Accept": WIKIPEDIA_ACCEPT_HEADER,
    }


def normalize_plot_title(title: str) -> str:
    return " ".join(WORD_PATTERN.findall(title.lower()))


def parse_episode_list_plots(wikitext: str) -> dict[str, str]:
    plots: dict[str, str] = {}
    for template in _episode_list_templates(wikitext):
        fields = _template_fields(template)
        titles = _titles_from_field(fields.get("title", ""))
        summaries = _summaries_from_field(fields.get("shortsummary", ""))
        if len(titles) == 1 and len(summaries) != 1:
            summaries = (_plain_wiki_text(fields.get("shortsummary", "")),)
        if len(titles) == 2 and len(summaries) == 1 and TITLE_SPLIT in summaries[0]:
            summaries = tuple(
                part.strip() for part in summaries[0].split(TITLE_SPLIT) if part.strip()
            )
        for title, summary in zip(titles, summaries, strict=False):
            key = normalize_plot_title(title)
            cleaned = _plain_wiki_text(summary)
            if key and cleaned:
                plots.setdefault(key, cleaned)
    return plots


def load_packaged_episode_plots() -> dict[str, dict[str, str]]:
    plots_file = resources.files(PLOTS_PACKAGE).joinpath(PLOTS_FILENAME)
    try:
        raw = plots_file.read_text(encoding=TEXT_ENCODING)
    except OSError:
        return {}
    try:
        loaded: object = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    catalog: dict[str, dict[str, str]] = {}
    for show_stem, plots in loaded.items():
        if not isinstance(show_stem, str) or not isinstance(plots, dict):
            continue
        cleaned: dict[str, str] = {}
        for title_key, summary in plots.items():
            if isinstance(title_key, str) and isinstance(summary, str) and summary:
                cleaned[title_key] = summary
        catalog[show_stem] = cleaned
    return catalog


class WikipediaPlotIndex:
    def __init__(
        self,
        http_get: HttpGetter | None = None,
        packaged: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self._http_get = http_get
        self._packaged = (
            packaged if packaged is not None else load_packaged_episode_plots()
        )
        self._by_show: dict[str, dict[str, str]] = {}

    def packaged_plot_count(self) -> int:
        return sum(len(plots) for plots in self._packaged.values())

    def description_for_title(self, show_stem: str, title: str) -> str:
        catalog = self._catalog_for(show_stem)
        parts = [part.strip() for part in title.split(TITLE_SPLIT) if part.strip()]
        if not parts:
            parts = [title]
        found = tuple(
            catalog[key]
            for part in parts
            if (key := normalize_plot_title(part)) in catalog
        )
        return TITLE_SPLIT.join(found)

    def _catalog_for(self, show_stem: str) -> dict[str, str]:
        if show_stem in self._by_show:
            return self._by_show[show_stem]
        catalog = dict(self._packaged.get(show_stem, {}))
        live = self._fetch_live_plots(show_stem)
        if live:
            catalog.update(live)
        self._by_show[show_stem] = catalog
        return self._by_show[show_stem]

    def _fetch_live_plots(self, show_stem: str) -> dict[str, str]:
        if self._http_get is None:
            return {}
        page = WIKIPEDIA_PLOT_PAGES.get(show_stem)
        if page is None:
            return {}
        try:
            body = self._http_get(wikipedia_parse_url(page), wikipedia_headers())
            wikitext = _wikitext_from_parse_body(body)
        except (OSError, TimeoutError, ValueError, TypeError, json.JSONDecodeError):
            return {}
        return parse_episode_list_plots(wikitext)


def _wikitext_from_parse_body(body: str) -> str:
    loaded: object = json.loads(body)
    if not isinstance(loaded, dict):
        return ""
    parsed: object = loaded.get(JSON_PARSE_KEY)
    if not isinstance(parsed, dict):
        return ""
    wikitext = parsed.get(JSON_WIKITEXT_KEY)
    if not isinstance(wikitext, str):
        return ""
    return wikitext


def _episode_list_templates(wikitext: str) -> tuple[str, ...]:
    templates: list[str] = []
    for match in EPISODE_LIST_START.finditer(wikitext):
        start = match.start()
        depth = 0
        index = start
        while index < len(wikitext):
            if wikitext.startswith(TEMPLATE_OPEN, index):
                depth += 1
                index += len(TEMPLATE_OPEN)
                continue
            if wikitext.startswith(TEMPLATE_CLOSE, index):
                depth -= 1
                index += len(TEMPLATE_CLOSE)
                if depth == 0:
                    templates.append(wikitext[start:index])
                    break
                continue
            index += 1
    return tuple(templates)


def _template_fields(template: str) -> dict[str, str]:
    inner = template.strip()
    if inner.startswith(TEMPLATE_OPEN):
        inner = inner[len(TEMPLATE_OPEN) :]
    if inner.endswith(TEMPLATE_CLOSE):
        inner = inner[: -len(TEMPLATE_CLOSE)]
    fields: dict[str, str] = {}
    current_name = ""
    current_value: list[str] = []
    depth = 0
    index = 0
    while index < len(inner):
        if inner.startswith(TEMPLATE_OPEN, index):
            depth += 1
            current_value.append(TEMPLATE_OPEN)
            index += len(TEMPLATE_OPEN)
            continue
        if inner.startswith(TEMPLATE_CLOSE, index):
            depth -= 1
            current_value.append(TEMPLATE_CLOSE)
            index += len(TEMPLATE_CLOSE)
            continue
        if depth == 0 and inner[index] == "|":
            rest = inner[index + 1 :]
            match = re.match(r"\s*([A-Za-z0-9]+)\s*=\s*", rest)
            if match is not None:
                if current_name:
                    fields[current_name] = "".join(current_value).strip()
                current_name = match.group(1).lower()
                current_value = []
                index += 1 + match.end()
                continue
        current_value.append(inner[index])
        index += 1
    if current_name:
        fields[current_name] = "".join(current_value).strip()
    return fields


def _titles_from_field(raw_title: str) -> tuple[str, ...]:
    parts = [part.strip(" \"'") for part in HR_SPLIT.split(raw_title) if part.strip()]
    if len(parts) > 1:
        return tuple(parts)
    cleaned = _plain_wiki_text(raw_title)
    return (cleaned,) if cleaned else ()


def _summaries_from_field(raw_summary: str) -> tuple[str, ...]:
    cleaned = _plain_wiki_text(raw_summary)
    if not cleaned:
        return ()
    if TITLE_SPLIT in cleaned:
        return tuple(
            part.strip() for part in cleaned.split(TITLE_SPLIT) if part.strip()
        )
    return (cleaned,)


def _plain_wiki_text(raw: str) -> str:
    text = NOTE_CUT.sub("", raw)
    text = WIKI_REF.sub("", text)
    text = WIKI_LINK.sub(r"\1", text)
    text = WIKI_BOLD.sub("", text)
    text = WIKI_TAG.sub(" ", text)
    return " ".join(text.split()).strip()
