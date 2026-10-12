"""Episode numbers: unique within a season, assigned or checked when an episode is created or renumbered."""
from __future__ import annotations

from typing import Any


class EpisodeNumberTaken(ValueError):
    """The series already has an episode with this number."""

    def __init__(self, number: int, holder_id: str) -> None:
        self.number = number
        self.holder_id = holder_id
        self.code = "episode_number_taken"
        super().__init__(f"Episode number {number} is already used by {holder_id}")


def require_episode_number(value: Any) -> int:
    """An explicit episode number: a real integer of 1 or more (a bool is not an integer)."""
    if type(value) is not int or value < 1:
        raise ValueError("Episode number must be an integer of 1 or more")
    return value


def episode_number_holder(episodes: Any, number: int, season_id: Any, except_id: str | None = None) -> str | None:
    """Id of the episode of season ``season_id`` that already uses ``number``, except ``except_id``.

    Numbers are per season (``create_series_episode`` counts them that way): season 2 has its own episode 1."""
    if not isinstance(episodes, dict):
        return None
    for episode_id, episode in episodes.items():
        if str(episode_id) == except_id or not isinstance(episode, dict) or episode.get("seasonId") != season_id:
            continue
        if episode.get("number") == number:
            return str(episode.get("id") or episode_id)
    return None


def assign_episode_number(series: dict, requested: int | None) -> int:
    """The next number, or ``requested`` when that integer is free in the season a new episode goes to (the first)."""
    episodes = series.get("episodesById") if isinstance(series.get("episodesById"), dict) else {}
    if requested is None:
        return max([item.get("number") or 0 for item in episodes.values() if isinstance(item, dict)] + [0]) + 1
    number = require_episode_number(requested)
    seasons = [item for item in series.get("seasons") or [] if isinstance(item, dict)]
    holder = episode_number_holder(episodes, number, seasons[0].get("id") if seasons else None)
    if holder:
        raise EpisodeNumberTaken(number, holder)
    return number


def guard_episode_number(episodes: Any, season_id: Any, patch: dict, episode_id: str | None = None) -> None:
    """Refuse an explicit number another episode of the season holds. Omitting it leaves the caller to assign one.

    Re-sending the episode's own number in its own season is not a change: the editor sends the whole episode on
    every save, and older episodes may already share a number."""
    if "number" not in patch:
        return
    current = episodes.get(episode_id) if episode_id and isinstance(episodes, dict) else None
    if isinstance(current, dict) and type(patch["number"]) is int and patch["number"] == current.get("number") \
            and season_id == current.get("seasonId"):
        return
    number = require_episode_number(patch["number"])
    holder = episode_number_holder(episodes, number, season_id, except_id=episode_id)
    if holder:
        raise EpisodeNumberTaken(number, holder)
