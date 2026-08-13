"""Animals in profile, rigged and animated, rather than drawn as faces.

The face-on icons in gen/icons.py are adequate for a cup and inadequate for a
cat: at that level of abstraction a round head with ears is a guess, and the
first two attempts at a dog read as a monkey. More detail on the face does not
fix it, because the face is not what identifies the animal.

The silhouette and the gait are. A trotting dog with a swinging tail is
unmistakable from across a room at any size; a dog's face at 60px is a circle
with two dots. So these are profiles with joints:

    body      one closed outline - head, neck and torso in a single path, so
              a stroked drawing has no internal seams where shapes overlap
    legs      two segments on a hip pivot, four of them, phase-offset into a
              diagonal gait (front-left with back-right)
    tail      a curve whose control point swings
    head      a small counter-bob, opposite the body's

Everything is a function of phase in [0, 1), one full stride. The renderer and
encoder are unchanged - these are ordinary frames.
"""

from __future__ import annotations

import math

VIEWBOX = 24
GROUND = 20.8


def _pt(x, y):
    return f"{x:.2f} {y:.2f}"


def _leg(hx, hy, phase, reach=1.55, upper=3.5, lower=3.4, lift=1.5):
    """One leg: hip -> knee -> foot, as a two-segment stroked path.

    The knee bends only on the swing (when the foot is off the ground), which
    is what separates a walk from a pair of scissors opening and closing.
    """
    swing = math.sin(phase * 2 * math.pi)
    up = max(0.0, math.sin(phase * 2 * math.pi + math.pi / 2))
    a1 = swing * reach * 0.34
    bend = up * 0.85
    kx = hx + math.sin(a1) * upper
    ky = hy + math.cos(a1) * upper
    a2 = a1 - bend
    fx = kx + math.sin(a2) * lower
    fy = ky + math.cos(a2) * lower
    fy = min(fy, GROUND - up * lift)
    return f'<path d="M{_pt(hx, hy)}L{_pt(kx, ky)}L{_pt(fx, fy)}"/>'


def dog(phase: float) -> str:
    bob = math.sin(phase * 4 * math.pi) * 0.22
    hb = -bob * 0.7
    wag = math.sin(phase * 4 * math.pi) * 2.4
    ear = math.sin(phase * 4 * math.pi + 0.7) * 0.55

    body = (
        f"M{_pt(5.0, 10.6 + bob)}"
        f"C{_pt(5.0, 9.3 + bob)} {_pt(6.6, 8.9 + bob)} {_pt(8.6, 8.9 + bob)}"
        f"L{_pt(12.9, 9.0 + bob)}"
        f"C{_pt(14.4, 9.0 + bob)} {_pt(15.4, 8.4 + bob)} {_pt(16.2, 7.3 + hb)}"
        f"C{_pt(16.8, 6.4 + hb)} {_pt(17.7, 5.8 + hb)} {_pt(18.8, 5.8 + hb)}"
        f"C{_pt(20.3, 5.8 + hb)} {_pt(21.6, 6.6 + hb)} {_pt(22.0, 7.6 + hb)}"
        f"C{_pt(22.3, 8.3 + hb)} {_pt(21.9, 8.9 + hb)} {_pt(21.1, 9.0 + hb)}"
        f"L{_pt(19.0, 9.2 + hb)}"
        f"C{_pt(18.0, 9.3 + hb)} {_pt(17.3, 9.9 + hb)} {_pt(16.9, 10.8 + bob)}"
        f"C{_pt(16.4, 11.9 + bob)} {_pt(15.7, 12.6 + bob)} {_pt(14.7, 12.9 + bob)}"
        f"L{_pt(8.8, 13.4 + bob)}"
        f"C{_pt(6.7, 13.5 + bob)} {_pt(5.2, 12.9 + bob)} {_pt(5.0, 11.5 + bob)}Z"
    )
    tail = (f'<path d="M{_pt(5.1, 10.8 + bob)}'
            f'C{_pt(3.4, 10.0 + bob)} {_pt(2.6, 8.4 + bob + wag)} '
            f'{_pt(3.2, 6.6 + bob + wag * 1.4)}"/>')
    earp = (f'<path d="M{_pt(18.3, 6.2 + hb)}'
            f'C{_pt(17.2, 6.6 + hb)} {_pt(16.9, 8.0 + hb + ear)} '
            f'{_pt(17.5, 9.3 + hb + ear)}"/>')
    legs = (
        _leg(14.3, 12.7 + bob, phase)
        + _leg(13.3, 12.9 + bob, phase + 0.5)
        + _leg(7.6, 13.2 + bob, phase + 0.5)
        + _leg(6.7, 13.3 + bob, phase)
    )
    eye = f'<circle cx="19.5" cy="{7.4 + hb:.2f}" r="0.52" fill="currentColor" stroke="none"/>'
    nose = f'<circle cx="21.7" cy="{7.8 + hb:.2f}" r="0.55" fill="currentColor" stroke="none"/>'
    return f'{legs}<path d="{body}"/>{tail}{earp}{eye}{nose}'


def cat(phase: float) -> str:
    """Same rig, different silhouette. A cat is a higher, rounder back, a
    shorter muzzle, pointed ears, and a tail that stands UP - the tail alone
    separates it from the dog at any size."""
    bob = math.sin(phase * 4 * math.pi) * 0.2
    hb = -bob * 0.7
    sway = math.sin(phase * 2 * math.pi) * 1.6

    body = (
        f"M{_pt(5.2, 11.2 + bob)}"
        f"C{_pt(5.0, 9.4 + bob)} {_pt(6.6, 8.4 + bob)} {_pt(9.2, 8.3 + bob)}"
        f"C{_pt(11.4, 8.2 + bob)} {_pt(13.6, 8.5 + bob)} {_pt(15.6, 8.4 + hb)}"
        f"C{_pt(16.8, 8.3 + hb)} {_pt(17.5, 7.6 + hb)} {_pt(18.0, 6.9 + hb)}"
        f"C{_pt(18.6, 6.1 + hb)} {_pt(19.6, 5.9 + hb)} {_pt(20.4, 6.4 + hb)}"
        f"C{_pt(21.3, 7.0 + hb)} {_pt(21.5, 8.2 + hb)} {_pt(20.9, 9.0 + hb)}"
        f"C{_pt(20.3, 9.7 + hb)} {_pt(19.2, 9.9 + hb)} {_pt(18.2, 9.7 + hb)}"
        f"C{_pt(17.3, 10.3 + bob)} {_pt(16.8, 11.4 + bob)} {_pt(15.9, 12.2 + bob)}"
        f"C{_pt(14.8, 13.0 + bob)} {_pt(12.0, 13.3 + bob)} {_pt(9.0, 13.2 + bob)}"
        f"C{_pt(6.6, 13.1 + bob)} {_pt(5.4, 12.6 + bob)} {_pt(5.2, 11.2 + bob)}Z"
    )
    tail = (f'<path d="M{_pt(5.3, 11.0 + bob)}'
            f'C{_pt(3.6, 10.6 + bob)} {_pt(2.6, 8.6 + bob)} '
            f'{_pt(3.0 + sway * 0.5, 6.0 + bob)}'
            f'C{_pt(3.2 + sway * 0.8, 4.8 + bob)} {_pt(4.2 + sway, 4.3 + bob)} '
            f'{_pt(5.0 + sway, 4.6 + bob)}"/>')
    ears = (f'<path d="M{_pt(18.1, 6.7 + hb)}L{_pt(17.9, 4.5 + hb)}'
            f'L{_pt(19.6, 5.9 + hb)}"/>'
            f'<path d="M{_pt(20.4, 6.4 + hb)}L{_pt(21.4, 4.6 + hb)}'
            f'L{_pt(21.9, 6.9 + hb)}"/>')
    legs = (
        _leg(15.2, 12.2 + bob, phase, reach=1.4, upper=3.2, lower=3.2)
        + _leg(14.2, 12.5 + bob, phase + 0.5, reach=1.4, upper=3.2, lower=3.2)
        + _leg(7.8, 13.0 + bob, phase + 0.5, reach=1.4, upper=3.2, lower=3.2)
        + _leg(6.9, 13.1 + bob, phase, reach=1.4, upper=3.2, lower=3.2)
    )
    eye = f'<circle cx="19.9" cy="{7.6 + hb:.2f}" r="0.5" fill="currentColor" stroke="none"/>'
    nose = f'<circle cx="21.3" cy="{8.3 + hb:.2f}" r="0.45" fill="currentColor" stroke="none"/>'
    whisk = (f'<path d="M{_pt(21.0, 9.0 + hb)}L{_pt(23.2, 9.4 + hb)}'
             f'M{_pt(21.0, 8.8 + hb)}L{_pt(23.3, 8.3 + hb)}"/>')
    return f'{legs}<path d="{body}"/>{tail}{ears}{eye}{nose}{whisk}'


CREATURES = {"dog": dog, "cat": cat}


def frames(name: str, n: int = 12, size: int = 240, stroke: float = 1.8) -> list:
    fn = CREATURES[name]
    out = []
    for i in range(n):
        out.append(
            f'<svg width="{size}" height="{size}" viewBox="0 0 {VIEWBOX} {VIEWBOX}" '
            f'fill="none" stroke="currentColor" stroke-width="{stroke}" '
            f'stroke-linecap="round" stroke-linejoin="round">{fn(i / n)}</svg>')
    return out
