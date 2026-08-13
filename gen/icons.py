"""Line-art icons for the sight-word videos.

Hand-authored SVG, not generated raster art, for four reasons that all matter
here:

  themes     stroke="currentColor" means one icon serves night, paper and
             contrast. A raster asset needs three, and they drift apart.
  scale      the videos render at 1920x1080 from HTML in Chromium
             (app/frames.js). Vector arrives sharp at any size; a 512px PNG
             upscaled to fill a frame does not.
  consistency one 24-unit grid, one stroke width, round caps throughout. Forty
             generated images are forty different drawings; forty of these are
             one drawing repeated.
  weight     thick even strokes are the whole brief, and stroke-width is a
             number here rather than something to be prompted for and hoped
             at.

## How they are meant to be used

NOT as a permanent companion to the word. In sight-word teaching a picture
that is always present is the thing the child reads - pair "cat" with a cat
every time and they learn to say "cat" at the drawing, while the letters
never have to do any work. The word has to stand alone before it is learned.

So the icon fades across the four stages:

    introduce   icon + word
    match       two words, no icon
    select      icon supports the question ("where is cat?")
    name        word alone - no icon

FADE_STAGES below is that sequence, so a video generator asks rather than
assumes.
"""

from __future__ import annotations

VIEWBOX = 24
STROKE = 2.0
FADE_STAGES = {"introduce": True, "match": False, "select": True, "name": False}

# Inner markup only - stroke, fill, linecap and the viewBox are applied by
# svg() so every icon is guaranteed the same treatment.
ICONS = {
    # -- core vocabulary: symbolic, and deliberately not cute ---------------
    "stop": """
        <path d="M8.2 3.5h7.6L20.5 8.2v7.6L15.8 20.5H8.2L3.5 15.8V8.2z"/>
    """,
    # A plain plus, which is what most AAC boards use for "more" and what a
    # child meets on a communication device. The earlier block-plus-plus tried
    # to depict "a thing, and another" and read as neither.
    "more": """
        <rect x="3.5" y="3.5" width="17" height="17" rx="4"/>
        <path d="M12 8v8M8 12h8"/>
    """,
    "go": """
        <circle cx="12" cy="12" r="8.5"/>
        <path d="M9.5 12h6M13 9.5l2.5 2.5-2.5 2.5"/>
    """,
    "up": """
        <path d="M12 20V5M6.5 10.5L12 5l5.5 5.5"/>
    """,
    # A raised hand, not a heart. A heart is read as "love" or "like" by
    # everyone including children, and "help" is the request - the thing you
    # put your hand up for.
    "help": """
        <path d="M8 12.5V5.2a1.6 1.6 0 0 1 3.2 0v6"/>
        <path d="M11.2 11.2V4.2a1.6 1.6 0 0 1 3.2 0v7"/>
        <path d="M14.4 11.5V6a1.6 1.6 0 0 1 3.2 0v8.5a6 6 0 0 1-6 6 6 6 0 0 1-6-6v-3a1.6 1.6 0 0 1 3.2 0"/>
    """,
    "open": """
        <path d="M4 20V6l7-2.5V20"/>
        <path d="M11 8h9v12H4"/>
        <circle cx="8.5" cy="12.5" r="0.9"/>
    """,

    # -- concrete nouns ----------------------------------------------------
    # Eyes are FILLED dots, not one-unit strokes. At stroke-width 2 with round
    # caps a 1-unit line renders as a blob the same size as the nose, and the
    # face reads as a snout with two nostrils.
    #
    # Cat and dog also have to differ in SILHOUETTE, not just in detail - at a
    # glance a child sees the outline. So the cat gets pointed ears above the
    # head and the dog gets long ears hanging beside it, with a muzzle that
    # breaks the head outline at the bottom.
    "cat": """
        <path d="M6.6 8.2L5.4 3.2l4.8 2.6"/>
        <path d="M17.4 8.2l1.2-5-4.8 2.6"/>
        <circle cx="12" cy="13" r="6.4"/>
        <circle cx="9.7" cy="11.9" r="0.85" fill="currentColor" stroke="none"/>
        <circle cx="14.3" cy="11.9" r="0.85" fill="currentColor" stroke="none"/>
        <path d="M12 14.4l-1 1.1M12 14.4l1 1.1"/>
        <path d="M2.4 12.6h3.4M2.6 15.4l3.3-.9M21.6 12.6h-3.4M21.4 15.4l-3.3-.9"/>
    """,
    # Third attempt. The first two read as a monkey, and the reason was the
    # ears: round, level with the head, and no longer than it. An ape's ears
    # are exactly that. A dog's are long flaps that hang BELOW the jaw, so
    # they have to break the head's outline top and bottom - that silhouette
    # is the whole identification, and the face inside it barely matters.
    "dog": """
        <path d="M7.9 8.1c-2.6-.7-4.3.6-4.6 3.4-.3 3 .5 5.9 2 7.1 1.2.9 2.5.4 2.9-1"/>
        <path d="M16.1 8.1c2.6-.7 4.3.6 4.6 3.4.3 3-.5 5.9-2 7.1-1.2.9-2.5.4-2.9-1"/>
        <path d="M7.9 8.1a5.6 4.8 0 0 1 8.2 0c1 1.9 1.1 4.6.5 6.4a4.9 4.6 0 0 1-9.2 0c-.6-1.8-.5-4.5.5-6.4z"/>
        <circle cx="9.9" cy="11.4" r="0.85" fill="currentColor" stroke="none"/>
        <circle cx="14.1" cy="11.4" r="0.85" fill="currentColor" stroke="none"/>
        <circle cx="12" cy="14.6" r="1" fill="currentColor" stroke="none"/>
        <path d="M12 15.8v1.1M12 16.9c-.5.7-1.5.7-2 0M12 16.9c.5.7 1.5.7 2 0"/>
    """,
    "ball": """
        <circle cx="12" cy="12" r="8.5"/>
        <path d="M5 8.5c4.5 1.5 9.5 1.5 14 0"/>
        <path d="M5 15.5c4.5-1.5 9.5-1.5 14 0"/>
    """,
    "cup": """
        <path d="M5.5 7h11l-1.2 12.5H6.7z"/>
        <path d="M16.3 10h2.2a2.2 2.2 0 0 1 0 4.4h-1.8"/>
    """,
    # A sloped cabin over a low body. The flat-roofed box it replaced read as
    # a bus, which is a different word on the list.
    "car": """
        <path d="M3.2 16v-3.4l1.9-.6 2.4-3.6a2 2 0 0 1 1.6-.9h5.8a2 2 0 0 1 1.6.9l2.4 3.6 1.9.6V16"/>
        <path d="M5.1 12h13.8"/>
        <path d="M11.6 8.5V12"/>
        <circle cx="7.6" cy="16.4" r="1.9"/>
        <circle cx="16.4" cy="16.4" r="1.9"/>
        <path d="M3.2 16h2.5M9.5 16h5M18.3 16h2.5"/>
    """,
}


# --------------------------------------------------------------- motion

# A static drawing cannot show an action. "turn", "open", "finished" and
# "more" are things that HAPPEN, and a line drawing of a happened thing is a
# riddle - which is why the static set was opaque even to a reader who knows
# what the words mean.
#
# This costs far less than it looks. The encoder runs at 15fps with a
# per-frame duration (gen/soundout.py), and plan_job() dedupes frames by
# visual signature - so a 12-state loop held for three seconds is 12 PNGs,
# not 45. Forty animated icons is a few hundred frames rendered once, against
# the few hundred a single 20-minute video already costs.
#
# Each entry is a function of t in [0, 1]. Nothing else in the pipeline
# changes: the states are ordinary icons, rendered by the same renderer.

def _ease(t: float) -> float:
    """Ease in-out. Linear motion reads as mechanical; a child tracking the
    movement is helped by it slowing at the ends."""
    return 3 * t * t - 2 * t * t * t


def _open(t: float) -> str:
    """A door swinging in. The panel narrows and lifts as it opens, which is
    the whole cue - a door that merely slides looks like a drawer."""
    e = _ease(t)
    x = 18.0 - 9.4 * e
    inset = 1.6 * e
    return f"""
        <path d="M4 20V4h14v16z" opacity="0.35"/>
        <path d="M4 20V4l{x - 4:.2f} {inset:.2f}v{16 - 2 * inset:.2f}z"/>
        <circle cx="{x - 1.6:.2f}" cy="12" r="0.85" fill="currentColor" stroke="none"/>
        <path d="M4 20h16"/>
    """


def _more(t: float) -> str:
    """Two, then three. "More" is the arrival of the extra one, so the third
    circle grows in rather than being simply present."""
    e = _ease(min(1.0, t * 1.35))
    r = 2.6 * e
    body = ('<circle cx="6" cy="14" r="2.6"/><circle cx="12" cy="14" r="2.6"/>')
    if r > 0.25:
        body += f'<circle cx="18" cy="14" r="{r:.2f}"/>'
        body += (f'<path d="M18 {6.6 - 1.4 * e:.2f}v2.4M16.8 '
                 f'{7.8 - 1.4 * e:.2f}l1.2 1.2 1.2-1.2" opacity="{e:.2f}"/>')
    return body


def _up(t: float) -> str:
    """The thing goes up, and the arrow goes with it."""
    e = _ease(t)
    y = 16.5 - 8.0 * e
    return f"""
        <rect x="8.5" y="{y:.2f}" width="7" height="5.2" rx="1.2"/>
        <path d="M12 {y - 1.6:.2f}V{y - 5.4:.2f}M9.6 {y - 3.0:.2f}L12 {y - 5.4:.2f}l2.4 2.4"
              opacity="{min(1.0, e * 2):.2f}"/>
        <path d="M4 21.4h16" opacity="0.35"/>
    """


def _turn(t: float) -> str:
    """A circular arrow that actually goes round - the arrowhead travels."""
    import math

    a = -90 + 300 * _ease(t)
    r = 7.2
    cx = 12 + r * math.cos(math.radians(a))
    cy = 12 + r * math.sin(math.radians(a))
    large = 1 if 300 * _ease(t) > 180 else 0
    sx, sy = 12 + r * math.cos(math.radians(-90)), 12 + r * math.sin(math.radians(-90))
    tan = a + 90
    h1x = cx - 2.6 * math.cos(math.radians(tan - 32))
    h1y = cy - 2.6 * math.sin(math.radians(tan - 32))
    h2x = cx - 2.6 * math.cos(math.radians(tan + 32))
    h2y = cy - 2.6 * math.sin(math.radians(tan + 32))
    arc = ("" if t < 0.04 else
           f'<path d="M{sx:.2f} {sy:.2f}A{r} {r} 0 {large} 1 {cx:.2f} {cy:.2f}"/>')
    return f"""
        <circle cx="12" cy="12" r="{r}" opacity="0.25"/>
        {arc}
        <path d="M{h1x:.2f} {h1y:.2f}L{cx:.2f} {cy:.2f}L{h2x:.2f} {h2y:.2f}"/>
    """


def _stop(t: float) -> str:
    """Something moving, then halted against the sign. The octagon alone is a
    road sign; the stopping is what makes it the word."""
    e = _ease(min(1.0, t * 1.6))
    x = 2.5 + 5.0 * e
    return f"""
        <path d="M13.2 6.2h5.1L21.5 9.4v5.2L18.3 17.8h-5.1L10 14.6V9.4z"/>
        <circle cx="{x:.2f}" cy="12" r="2.1"/>
        <path d="M1 12h1.2" opacity="{1 - e:.2f}"/>
    """


ANIMATED = {"open": _open, "more": _more, "up": _up, "turn": _turn,
            "stop": _stop}

# Words that cannot be drawn OR animated, and should carry no picture at all.
#
# Pronouns and question words have no concrete referent. AAC boards give them
# arbitrary symbols that must themselves be taught, which for a reading video
# means adding a second thing to learn in order to teach the first. The word
# form is the lesson here, so these get the screen to themselves.
NO_ICON = {"I", "you", "he", "she", "it", "that", "what", "when", "where",
           "who", "why", "can", "not", "some", "all", "good", "here", "same",
           "different", "like", "do"}


def steps(name: str, n: int = 12, size: int = 240,
          stroke: float = STROKE) -> list:
    """`n` SVG states of an animated icon, first to last."""
    fn = ANIMATED[name]
    out = []
    for i in range(n):
        t = i / (n - 1) if n > 1 else 1.0
        out.append(
            f'<svg width="{size}" height="{size}" viewBox="0 0 {VIEWBOX} {VIEWBOX}" '
            f'fill="none" stroke="currentColor" stroke-width="{stroke}" '
            f'stroke-linecap="round" stroke-linejoin="round" '
            f'aria-hidden="true">{fn(t).strip()}</svg>')
    return out


def animated(name: str) -> bool:
    return name in ANIMATED


def svg(name: str, size: int = 240, stroke: float = STROKE) -> str:
    """One icon as standalone SVG markup, inheriting the surrounding color.

    `stroke` is in grid units and does NOT scale with `size` - that is the
    point of a fixed grid. An icon at 480px and the same icon at 120px are
    the same drawing at two sizes, not two different weights.
    """
    body = ICONS[name].strip()
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {VIEWBOX} {VIEWBOX}" '
        f'fill="none" stroke="currentColor" stroke-width="{stroke}" '
        f'stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true">{body}</svg>'
    )


def has(name: str) -> bool:
    return name in ICONS


def names() -> list:
    return sorted(ICONS)
