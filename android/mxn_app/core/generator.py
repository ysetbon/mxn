"""Thin wrapper that selects the right generator module for a given variant."""

from mxn_app.core.generators import mxn_lh, mxn_rh, mxn_lh_strech, mxn_rh_stretch


_VARIANTS = {
    ("LH", False): mxn_lh.generate_json,
    ("RH", False): mxn_rh.generate_json,
    ("LH", True): mxn_lh_strech.generate_json,
    ("RH", True): mxn_rh_stretch.generate_json,
}


def generate(m: int, n: int, variant: str, stretch: bool) -> str:
    """Return the OpenStrandStudio JSON string for the requested pattern.

    variant: "LH" or "RH"
    stretch: True selects the stretched variant
    """
    key = (variant, stretch)
    if key not in _VARIANTS:
        raise ValueError(f"Unknown variant combination: {key}")
    return _VARIANTS[key](m, n)
