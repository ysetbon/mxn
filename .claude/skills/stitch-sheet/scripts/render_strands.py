"""Render an mxn continuation JSON state into a standalone SVG (no Qt needed)."""
import json


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
    xs, ys = [], []
    for s in strands:
        if s['type'] == 'MaskedStrand':
            continue
        for p in (s['start'], s['end']):
            xs.append(p['x'])
            ys.append(p['y'])
    return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


def _line(s):
    return (s['start']['x'], s['start']['y'], s['end']['x'], s['end']['y'])


def render(path, label=None, show_names=True, size=520, view=None, idp='',
           label_suffixes=('_4', '_5'), label_at='end'):
    strands = load_strands(path)
    by_name = {s['layer_name']: s for s in strands}
    x0, y0, x1, y1 = view or bounds(strands)
    w, h = x1 - x0, y1 - y0

    out = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.1f} {y0:.1f} {w:.1f} {h:.1f}" '
        f'width="100%" style="max-width:{size}px;height:auto;display:block">'
    )

    # masks: white band along the "second" strand of each MaskedStrand
    out.append('<defs>')
    for s in strands:
        if s['type'] != 'MaskedStrand':
            continue
        second = by_name.get(s['second_selected_strand'])
        if second is None:
            continue
        ax, ay, bx, by = _line(second)
        bw = second['width'] + 2 * second['stroke_width']
        mid = s['layer_name']
        out.append(
            f'<mask id="{idp}m_{mid}" maskUnits="userSpaceOnUse" x="{x0:.1f}" y="{y0:.1f}" '
            f'width="{w:.1f}" height="{h:.1f}">'
            f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{h:.1f}" fill="black"/>'
            f'<line x1="{ax:.2f}" y1="{ay:.2f}" x2="{bx:.2f}" y2="{by:.2f}" '
            f'stroke="white" stroke-width="{bw}" stroke-linecap="butt"/></mask>'
        )
    out.append('</defs>')

    def draw_body(s, mask=None):
        ax, ay, bx, by = _line(s)
        col = _rgb(s['color'])
        sw = s['stroke_width']
        wid = s['width']
        attr = ' mask="url(#%sm_%s)"' % (idp, mask) if mask else ''
        g = '<g%s>' % attr
        parts = [g]
        # attachment circles
        for i, has in enumerate(s.get('has_circles', [False, False])):
            if not has:
                continue
            cx, cy = (ax, ay) if i == 0 else (bx, by)
            parts.append(
                f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{wid / 2 + sw:.2f}" fill="black"/>'
                f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{wid / 2:.2f}" fill="{col}"/>'
            )
        parts.append(
            f'<line x1="{ax:.2f}" y1="{ay:.2f}" x2="{bx:.2f}" y2="{by:.2f}" '
            f'stroke="black" stroke-width="{wid + 2 * sw}" stroke-linecap="butt"/>'
        )
        parts.append(
            f'<line x1="{ax:.2f}" y1="{ay:.2f}" x2="{bx:.2f}" y2="{by:.2f}" '
            f'stroke="{col}" stroke-width="{wid}" stroke-linecap="butt"/>'
        )
        parts.append('</g>')
        return ''.join(parts)

    def is_cont(s):
        """Continuation layer? For a mask, decided by its member strands - the
        mask's own name can't be split on '_' once set numbers reach 4 and 5
        (e.g. the base mask 5_3_4_2 is not a _4/_5 mask)."""
        if s['type'] == 'MaskedStrand':
            members = (s.get('first_selected_strand', ''), s.get('second_selected_strand', ''))
            return any(mm.endswith(('_4', '_5')) for mm in members)
        return s['layer_name'].endswith(('_4', '_5'))

    # Paint order: base strands -> base masks -> _4/_5 strands -> _4/_5 masks,
    # so the _2/_3 masks stay UNDER the continuation.
    def emit(want_cont, masked):
        for s in strands:
            name = s['layer_name']
            if (s['type'] == 'MaskedStrand') != masked or is_cont(s) != want_cont:
                continue
            if not masked:
                out.append(draw_body(s))
                continue
            first = by_name.get(s['first_selected_strand'])
            if first is not None:
                out.append(draw_body(first, mask=name))

    emit(want_cont=False, masked=False)   # 1. _1 / _2 / _3
    emit(want_cont=False, masked=True)    # 2. their masks
    emit(want_cont=True, masked=False)    # 3. _4 / _5
    emit(want_cont=True, masked=True)     # 4. _4/_5 masks

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
