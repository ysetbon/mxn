"""Published twist stitches at k = 1.

The documents are in ``src/mxn_k1/<hand>/<m>x<n>/``:

    start.json           starting stitch
    continuation.json    aligned continuation
    alignment.json       angles, gaps, and extensions

Left and right hand, m and n from 1 to 4, keeping only m ≤ n
(2×1 is the same stitch as 1×2). Open any ``continuation.json`` in
OpenStrandStudio. From Python:

    import mxn_k1
    mxn_k1.load("lh", 1, 4)          # continuation document
    mxn_k1.load("lh", 1, 4, "start")
    mxn_k1.alignment("lh", 1, 4)

The left-hand 1×4 continuation is the re-aimed vertical arm (103.5°).
The earlier straight arm (90°) is ``continuation-before.json`` in that
same folder.
"""
import json
import os

_HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mxn_k1")

# (m, n) with 1 ≤ m ≤ n ≤ 4. The transpose is the same stitch.
SIZES = tuple((m, n) for m in range(1, 5) for n in range(m, 5))
HANDS = ("lh", "rh")
STAGES = ("start", "continuation", "alignment")


def catalog():
    """``(hand, m, n)`` for every stitch in this folder."""
    return tuple((hand, m, n) for hand in HANDS for m, n in SIZES)


def path(hand, m, n, stage="continuation"):
    """Absolute path of one document. ``stage`` is a file name without ``.json``."""
    hand = hand.lower()
    if hand not in HANDS:
        raise ValueError("hand must be lh or rh, got %r" % hand)
    if (int(m), int(n)) not in SIZES:
        raise ValueError("no k=1 stitch for %sx%s (kept sizes are m ≤ n, 1..4)" % (m, n))
    return os.path.join(_HERE, hand, "%sx%s" % (int(m), int(n)), stage + ".json")


def load(hand, m, n, stage="continuation"):
    """OpenStrandStudio history (``start`` or ``continuation``) as a dict."""
    if stage == "alignment":
        raise ValueError("use alignment() for the summary")
    with open(path(hand, m, n, stage), encoding="utf-8") as handle:
        return json.load(handle)


def alignment(hand, m, n, stage="alignment"):
    """Angles, gaps, and extensions for one stitch."""
    with open(path(hand, m, n, stage), encoding="utf-8") as handle:
        return json.load(handle)


def main():
    print("src/mxn_k1/")
    for hand, m, n in catalog():
        info = alignment(hand, m, n)
        horizontal = info.get("horizontal") or {}
        vertical = info.get("vertical") or {}
        print("  %s/%sx%s  H %s°  V %s°" % (
            hand, m, n,
            horizontal.get("angle"),
            vertical.get("angle")))


if __name__ == "__main__":
    main()
