"""Render an mxn continuation JSON state into a standalone SVG (no Qt needed).

Strands, attached strands and masks are drawn by the repo's ``src/oss_svg.py``,
a line-for-line SVG port of OpenStrandStudio's drawing, so the sheet looks
exactly like the same JSON opened in OpenStrandStudio (only the colours are
swapped for the deterministic palette below).
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', 'src')))
import oss_svg  # noqa: E402


def _rgb(c):
    return f"rgb({c['r']},{c['g']},{c['b']})"


# deterministic palette: horizontal sets keep the generator's white/green then
# take fixed tints; vertical sets take an indigo family. Which sets are vertical
# is read off the geometry (their _2 arm runs vertically), so it works for any
# m x n, not just m = 1.
HORIZ_HEX = ['#FFFFFF', '#55AA00', '#7BA7D9', '#E8B04B', '#C98BC0', '#6FC3B8',
             '#E08A6A', '#A9B7C6']
VERT_HEX = ['#3D3A8C', '#7B71D6', '#B3ADEC', '#5B54A8', '#9A93E0', '#2A2766']


def _hex(h):
    return {'r': int(h[1:3], 16), 'g': int(h[3:5], 16), 'b': int(h[5:7], 16), 'a': 255}


def vertical_sets(strands):
    """Set numbers whose _2 arm runs vertically."""
    out = set()
    for s in strands:
        if s['type'] == 'MaskedStrand' or not s['layer_name'].endswith('_2'):
            continue
        dx = abs(s['end']['x'] - s['start']['x'])
        dy = abs(s['end']['y'] - s['start']['y'])
        if dy > dx:
            out.add(s['set_number'])
    return out


def load_strands(path):
    d = json.load(open(path))
    strands = d['states'][-1]['data']['strands']
    vert = sorted(vertical_sets(strands))
    horiz = sorted({s['set_number'] for s in strands
                    if s['type'] != 'MaskedStrand' and s['set_number'] not in vert})
    for s in strands:
        if s['type'] == 'MaskedStrand':
            continue
        num = s['set_number']
        if num in vert:
            s['color'] = _hex(VERT_HEX[vert.index(num) % len(VERT_HEX)])
        else:
            s['color'] = _hex(HORIZ_HEX[horiz.index(num) % len(HORIZ_HEX)])
    return strands


def bounds(strands, pad=70):
    x0, y0, x1, y1 = oss_svg.strand_bounds(strands)
    return (x0 - pad, y0 - pad, x1 + pad, y1 + pad)


def _line(s):
    return (s['start']['x'], s['start']['y'], s['end']['x'], s['end']['y'])


def render(path, label=None, show_names=True, size=520, view=None, idp='',
           label_suffixes=('_4', '_5'), label_at='end'):
    strands = load_strands(path)
    x0, y0, x1, y1 = view or bounds(strands)
    w, h = x1 - x0, y1 - y0

    out = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.1f} {y0:.1f} {w:.1f} {h:.1f}" '
        f'width="100%" style="max-width:{size}px;height:auto;display:block">'
    )
    # OpenStrandStudio's paint order is the loaded layer order (the JSON's
    # `index` slots), which already puts the base masks under `_4/_5`.
    defs, body = oss_svg.draw_strands(strands, idp=idp + 'm_')
    out.append(f'<defs>{defs}</defs>')
    out.append(body)

    # 3. labels on the free ends of the continuation strands
    if show_names:
        for s in strands:
            if s['type'] == 'MaskedStrand':
                continue
            name = s['layer_name']
            if not any(name.endswith(suf) for suf in label_suffixes):
                continue
            ax, ay, bx, by = _line(s)
            dx, dy = bx - ax, by - ay
            n = (dx * dx + dy * dy) ** 0.5 or 1.0
            fs = w / 24.0  # keep labels the same apparent size at any viewBox scale
            lx, ly = bx + dx / n * (fs * 1.5), by + dy / n * (fs * 1.5)
            out.append(
                f'<text x="{lx:.1f}" y="{ly:.1f}" font-family="ui-monospace,monospace" '
                f'font-size="{fs:.1f}" font-weight="700" text-anchor="middle" '
                f'dominant-baseline="central" fill="#111" '
                f'stroke="#fff" stroke-width="{fs * 0.28:.1f}" paint-order="stroke">{name}</text>'
            )

    if label:
        out.append(
            f'<text x="{x0 + 8:.1f}" y="{y0 + 26:.1f}" font-family="ui-monospace,monospace" '
            f'font-size="22" font-weight="700" fill="#111" stroke="#fff" stroke-width="5" '
            f'paint-order="stroke">{label}</text>'
        )
    out.append('</svg>')
    return ''.join(out)


if __name__ == '__main__':
    import sys
    print(render(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
