"""Library half-hours that hold two TVMaze shorts. No I/O."""

from collections.abc import Sequence

from tv90.config import HARRY_SHOW_STEM, OSWALD_SHOW_STEM
from tv90.ports.metadata import EpisodeMetadata

PAIRED_SHORT_SHOW_STEMS = frozenset({OSWALD_SHOW_STEM, HARRY_SHOW_STEM})
SHORTS_PER_BROADCAST = 2
TITLE_JOIN = " / "
DESCRIPTION_JOIN = " "

# TVMaze lists Harry as one season of shorts. Season 2 library files are
# still two-short half-hours; titles match the Archive.org broadcast names.
HARRY_SEASON_TWO_BROADCAST_TITLES = {
    1: "What's Thunder? / Once Upon a Time",
    2: "Superheroes Don't Dance! / I Love Strawberries!",
    3: "I Wish I Could Fly! / What a Cold Nose!",
    4: "Can I Help? / Harry, Bug Hunter!",
    5: "Zoom / I'm King Harry",
    6: "Mirror Mirror / Splash",
    7: "I Want to Go Faster! / Two Plus Two Make Four",
    8: "My Tooth Came Out! / Costume Party",
    9: "Harry the Explorer / I Wish It Were Yesterday",
    10: "I See a Seashell! / Jump",
    11: "Yee Haw! / Somebody's Moving",
    12: "Is That Really a Lamp? / Aaarrgh, Treasure!",
    13: "Hurray for Pizza! / Harry the Inventor",
    14: "Join the Parade! / Choo Choo!",
    15: "Cool Shadow! / Do You Like My Tent?",
    16: "Home! / It's an Alien",
    17: "I Want to Make a Movie! / Jungle Harry",
    18: "Emergency! / Dino Snap!",
    19: "I've Got the Giggles! / I'm Really Hot!",
    20: "The Silly Pencil / Now You See Me, Now You Don't",
    21: "It's an Elephostriche / My Hair Is Short!",
    22: "Back to School / Where Did the Wind Go?",
    23: "There's Got to Be Something! / That's Strong",
    24: "I'm on a Quest / What Does This Key Open?",
    25: "Blast Off / Space Captain Harry",
    26: "Let's Go to Africa! / Where's My Penguin?",
}


def uses_paired_shorts(show_stem: str) -> bool:
    return show_stem in PAIRED_SHORT_SHOW_STEMS


def catalog_short_numbers(broadcast_episode_number: int) -> tuple[int, int]:
    first = (broadcast_episode_number - 1) * SHORTS_PER_BROADCAST + 1
    return (first, first + 1)


def join_short_metadata(parts: Sequence[EpisodeMetadata]) -> EpisodeMetadata:
    titles = tuple(part.title for part in parts if part.title)
    descriptions = tuple(part.description for part in parts if part.description)
    return EpisodeMetadata(
        title=TITLE_JOIN.join(titles),
        description=DESCRIPTION_JOIN.join(descriptions),
    )


def fallback_broadcast_title(
    show_stem: str, season_number: int, episode_number: int
) -> str | None:
    if show_stem != HARRY_SHOW_STEM or season_number != 2:
        return None
    return HARRY_SEASON_TWO_BROADCAST_TITLES.get(episode_number)
