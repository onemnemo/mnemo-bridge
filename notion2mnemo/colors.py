"""
Notion colours -> Mnemo swatch tokens (``"swatch5"``), not hex values.

Matched by hue, not RGB distance: every Notion background is near white, so
distance maps all of them to ``swatch1``. Where two tokens fit equally well, the
one on Mnemo's formatting toolbar (``toolbar/palette.ts``) is used so the colour
stays editable. Nine Notion colours go into ten tokens, so some share one (text
brown and yellow, background brown and orange, background red and pink).
Override with ``--color-map FILE`` (see ``load_overrides``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

#: Notion text colour -> Mnemo foreground swatch token. Hexes in the comments are
#: Notion's light theme and the Dawn palette in `Mnemo.Core/Services/NotePdfDawnSwatches.cs`.
TEXT_COLORS: dict[str, str] = {
    # notion #787774 -> mnemo #57534E stone (toolbar: no)
    "gray": "swatch1",
    # notion #9F6B53 -> mnemo #CA8A04 goldenrod (toolbar: no)
    "brown": "swatch7",
    # notion #D9730D -> mnemo #EA580C orange (toolbar: yes)
    "orange": "swatch8",
    # notion #CB912F -> mnemo #CA8A04 goldenrod (toolbar: no)
    "yellow": "swatch7",
    # notion #448361 -> mnemo #16A34A green (toolbar: yes)
    "green": "swatch6",
    # notion #337EA9 -> mnemo #2563EB blue (toolbar: yes)
    "blue": "swatch3",
    # notion #9065B0 -> mnemo #7C3AED violet (toolbar: yes)
    "purple": "swatch2",
    # notion #C14C8A -> mnemo #DC2626 red (toolbar: yes)
    "pink": "swatch5",
    # notion #D44C47 -> mnemo #DC2626 red (toolbar: yes)
    "red": "swatch5",
}

#: Notion background colour (without ``_background``) -> Mnemo background swatch token.
BACKGROUND_COLORS: dict[str, str] = {
    # notion #F1F1EF -> mnemo #F5F5F5 grey (toolbar: yes)
    "gray": "swatch1",
    # notion #F4EEEE -> mnemo #FFE0B2 peach (toolbar: no)
    "brown": "swatch8",
    # notion #FAEBDD -> mnemo #FFE0B2 peach (toolbar: no)
    "orange": "swatch8",
    # notion #FBF3DB -> mnemo #FFF3CD butter (toolbar: yes)
    "yellow": "swatch7",
    # notion #EDF3EC -> mnemo #E8F5E9 mint (toolbar: yes)
    "green": "swatch6",
    # notion #E7F3F8 -> mnemo #DBEAFE powder blue (toolbar: yes)
    "blue": "swatch9",
    # notion #F6F3F9 -> mnemo #E6E6FA lavender (toolbar: no)
    "purple": "swatch2",
    # notion #FAF1F5 -> mnemo #FADBD8 blush (toolbar: yes)
    "pink": "swatch5",
    # notion #FDEBEC -> mnemo #FADBD8 blush (toolbar: yes)
    "red": "swatch5",
}

#: Notion block colour -> Mnemo table-cell tint id
#: (`mnemo-web/src/notes/editor/table/tints.ts`). ``""`` means no fill.
CELL_TINTS: dict[str, str] = {
    "gray": "grey",
    "brown": "amber",
    "orange": "amber",
    "yellow": "amber",
    "green": "green",
    "blue": "blue",
    "purple": "violet",
    "pink": "pink",
    "red": "red",
}

#: Callout colours that map to Mnemo's ``warn`` tone; every other colour is ``note``.
WARN_COLORS = frozenset({"red", "orange", "yellow"})

_BACKGROUND_SUFFIX = "_background"


class ColorMap:
    """The active Notion-to-Mnemo colour mapping, with user overrides applied."""

    def __init__(
        self,
        text: Mapping[str, str] | None = None,
        background: Mapping[str, str] | None = None,
        cell: Mapping[str, str] | None = None,
    ) -> None:
        self.text = dict(TEXT_COLORS)
        self.background = dict(BACKGROUND_COLORS)
        self.cell = dict(CELL_TINTS)
        # An override of "" or null drops that colour.
        self.text.update({k: v for k, v in (text or {}).items()})
        self.background.update({k: v for k, v in (background or {}).items()})
        self.cell.update({k: v for k, v in (cell or {}).items()})

    def resolve(self, color: str | None) -> tuple[str | None, str | None]:
        """
        Split a Notion colour into ``(foreground_token, background_token)``.

        A Notion colour is either text or background, so at most one is set.
        ``"default"`` and unknown colours give ``(None, None)``.
        """
        if not color or color == "default":
            return None, None
        if color.endswith(_BACKGROUND_SUFFIX):
            base = color[: -len(_BACKGROUND_SUFFIX)]
            return None, self.background.get(base) or None
        return self.text.get(color) or None, None

    def tint(self, color: str | None) -> str:
        """The table-cell tint id for a Notion colour, or ``""`` for no fill."""
        if not color or color == "default":
            return ""
        base = color[: -len(_BACKGROUND_SUFFIX)] if color.endswith(_BACKGROUND_SUFFIX) else color
        return self.cell.get(base, "")

    @staticmethod
    def is_warn(color: str | None) -> bool:
        """Whether a Notion callout colour should become Mnemo's ``warn`` tone."""
        if not color:
            return False
        base = color[: -len(_BACKGROUND_SUFFIX)] if color.endswith(_BACKGROUND_SUFFIX) else color
        return base in WARN_COLORS


def load_overrides(path: str | Path | None) -> ColorMap:
    """
    Reads a colour-map override file, or returns the built-in mapping.

    The file is JSON with up to three objects, each keyed by Notion colour name
    without the ``_background`` suffix::

        {
          "text":       {"brown": "swatch1", "gray": ""},
          "background": {"red": "swatch5", "pink": "swatch4"},
          "cell":       {"blue": "teal"}
        }

    An empty string drops that colour instead of mapping it.
    """
    if path is None:
        return ColorMap()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("colour map must be a JSON object")
    return ColorMap(
        text=data.get("text"),
        background=data.get("background"),
        cell=data.get("cell"),
    )
