"""The _4/_5 alignment as one perpendicular coordinate — model, test and inverse.

The aligner puts every strand of a group on a line at one shared angle t, so the
only coordinate that separates those lines is the perpendicular one:

    W_i = x_i * sin(t) - y_i * cos(t)

Every gap the aligner measures is `W_{i+1} - W_i`, and extending a strand slides
its start along a fixed _2/_3 direction, so W is *linear* in that strand's pair
extension. Two things follow, and this module provides both:

  `evaluate`   scores a configuration exactly the way the repo's search does
               (mirrors `_numpy_try_all_angles` with allow_inner_extensions=False),
               without going through the combo search.

  `extensions_for_gap`
               inverts the system: given the angle and the gap you want, the
               extensions follow by telescoping from the middle of the group
               outwards. No search, no grid, no dependency beyond `math`.

Nothing here re-implements the generator or the aligner's *decisions* - it
re-implements only the arithmetic of the gap test, so a candidate can be scored
in microseconds instead of minutes.
"""
import math

MIN_GAP = 56.0          # strand_width + 10
MAX_GAP = 69.0          # strand_width * 1.5
EXT_MAX = 200.0         # the search's own pair-extension ceiling
BAND_TOL = 1e-3         # a gap sitting on the floor must not fail on float noise;
                        # 4 dp extensions land within ~3e-5 px, well under anything visible


def pairs_of(count):
    """The aligner's outside-in pairing: (first, last), (second, second-last), ..."""
    got = [(i, count - 1 - i) for i in range(count // 2)]
    if count % 2:
        got.append((count // 2, None))
    return got


def pair_index(count):
    """Which pair each strand belongs to - a palindrome 0,1,..,p,p,..,1,0."""
    q = [0] * count
    for p, (left, right) in enumerate(pairs_of(count)):
        q[left] = p
        if right is not None:
            q[right] = p
    return q


def group_from_strands(all_strands, order):
    """Reduce a group to the (start, target, direction) triples the model needs.

    `order` is the k-based reading order from `_build_k_based_strand_sets`; each
    _4 takes its extension direction from the matching _2, each _5 from its _3.
    """
    by = {s['layer_name']: s for s in all_strands if s['type'] == 'AttachedStrand'}
    out = []
    for name in order:
        s45 = by[name]
        s23 = by[('%d_2' if name.endswith('_4') else '%d_3') % s45['set_number']]
        dx = s23['end']['x'] - s23['start']['x']
        dy = s23['end']['y'] - s23['start']['y']
        length = math.hypot(dx, dy)
        out.append(dict(name=name, set=s45['set_number'], partner=s23['layer_name'],
                        start=[s45['start']['x'], s45['start']['y']],
                        target=[s45['end']['x'], s45['end']['y']],
                        dir=[dx / length, dy / length]))
    return out


def evaluate(group, exts, angle_deg):
    """Score one configuration the way the aligner scores it.

    Returns a dict with `valid` plus the gaps, their variance, the first-last
    distance the aligner ranks on, and the line endpoints. `valid` requires all
    three of the aligner's conditions: every strand still reaches its target,
    the gaps all run the same way, and every gap sits inside [56, 69].
    """
    count = len(group)
    q = pair_index(count)
    sx, sy, dxt, dyt = [], [], [], []
    for i, s in enumerate(group):
        e = exts[q[i]]
        sx.append(s['start'][0] + e * s['dir'][0])
        sy.append(s['start'][1] + e * s['dir'][1])
        dxt.append(s['target'][0] - sx[i])
        dyt.append(s['target'][1] - sy[i])

    ref = math.atan2(dyt[0], dxt[0])
    goes_positive = [dxt[i] * math.cos(ref) + dyt[i] * math.sin(ref) >= 0
                     for i in range(count)]

    theta = math.radians(angle_deg)
    ex, ey = [], []
    for i in range(count):
        a = theta if goes_positive[i] else theta + math.pi
        c, s = math.cos(a), math.sin(a)
        proj = dxt[i] * c + dyt[i] * s
        if proj <= 10:
            return dict(valid=False, gaps=None,
                        reason='%s cannot reach its target at this angle' % group[i]['name'])
        ex.append(sx[i] + proj * c)
        ey.append(sy[i] + proj * s)

    def perp(i, px, py):
        ldx, ldy = ex[i] - sx[i], ey[i] - sy[i]
        lc = ex[i] * sy[i] - ey[i] * sx[i]
        return (ldy * px - ldx * py + lc) / math.hypot(ldx, ldy)

    signed = []
    for i in range(count - 1):
        v = perp(i, sx[i + 1], sy[i + 1])
        signed.append(-v if i % 2 else v)
    last = perp(0, sx[count - 1], sy[count - 1])

    gaps = [abs(v) for v in signed]
    want = 1.0 if last >= 0 else -1.0
    dir_ok = all((v > 0) if want > 0 else (v < 0) for v in signed)
    in_band = all(MIN_GAP - BAND_TOL <= v <= MAX_GAP + BAND_TOL for v in gaps)
    ext_ok = all(-1e-6 <= e <= EXT_MAX + 1e-6 for e in exts)
    mean = sum(gaps) / len(gaps)

    reason = ''
    if not dir_ok:
        reason = 'the strand order folds back on itself - the gaps change sign'
    elif not in_band:
        bad = [v for v in gaps if v < MIN_GAP - BAND_TOL or v > MAX_GAP + BAND_TOL]
        reason = '%d gap(s) outside %g-%g px' % (len(bad), MIN_GAP, MAX_GAP)
    elif not ext_ok:
        reason = 'an extension is outside 0-%g px' % EXT_MAX

    return dict(valid=dir_ok and in_band and ext_ok, directions_ok=dir_ok,
                in_band=in_band, ext_ok=ext_ok, reason=reason,
                gaps=gaps, signed=signed, average_gap=mean,
                gap_variance=sum((v - mean) ** 2 for v in gaps) / len(gaps),
                worst_gap=min(gaps), first_last_distance=abs(last),
                angle=angle_deg, extensions=list(exts),
                starts=list(zip(sx, sy)), ends=list(zip(ex, ey)))


def extensions_for_gap(group, angle_deg, gap):
    """The extensions that make every gap exactly `gap` at this angle, or None.

    W_i = B_i + A_i * e_pair(i), so gap_i = (B_i+1 - B_i) + A_i+1 e_pair(i+1) -
    A_i e_pair(i). Because pair(i) is a palindrome there is one index where a gap
    sits between two strands of the *same* pair - that gap involves a single
    unknown and pins it, and the rest telescope outwards from there. The upper
    half of the group repeats the lower half's equations, which is exactly why
    the system is solvable at every size.

    Both gap senses are tried; the one that validates (or, failing that, strays
    least outside 0-200 px) wins.
    """
    count = len(group)
    q = pair_index(count)
    num_pairs = len(pairs_of(count))
    theta = math.radians(angle_deg)
    s, c = math.sin(theta), math.cos(theta)

    B = [s * g['start'][0] - c * g['start'][1] for g in group]
    A = [s * g['dir'][0] - c * g['dir'][1] for g in group]

    mid = next((i for i in range(count - 1) if q[i] == q[i + 1]), None)
    if mid is None:
        return None

    best = None
    for sense in (1.0, -1.0):
        den = A[mid + 1] - A[mid]
        if abs(den) < 1e-9:
            continue
        e = [0.0] * num_pairs
        e[q[mid]] = (sense * gap - (B[mid + 1] - B[mid])) / den
        ok = True
        for i in range(mid - 1, -1, -1):
            if abs(A[i]) < 1e-9:
                ok = False
                break
            e[q[i]] = ((B[i + 1] - B[i]) + A[i + 1] * e[q[i + 1]] - sense * gap) / A[i]
        if not ok or any(not math.isfinite(v) for v in e):
            continue
        outside = sum(max(0.0, -v) + max(0.0, v - EXT_MAX) for v in e)
        score = (0 if evaluate(group, e, angle_deg)['valid'] else 1, outside)
        if best is None or score < best[0]:
            best = (score, e)
    return best[1] if best else None


# --- corners: does the outside pair clear the opposite group's start? -------
#
# Not a strand-to-strand clearance. Every crossing between the two groups is
# masked and intended, so measuring how deep one overlaps another says nothing.
#
# What matters at a corner is which SIDE of it the outside pair runs. Each group
# is a band of parallel lines; its outside pair - reading indices 0 and last -
# are the two edges of that band. The opposite group's continuations start from
# the corners of the woven block. The stitch reads correctly when the outside
# pair passes OUTSIDE those starting corners rather than cutting across inside
# them, so the measurement is the signed offset of each corner from the nearer
# outer line, positive when the corner is on the outside.

def _perp_coord(x, y, angle_deg):
    t = math.radians(angle_deg)
    return x * math.sin(t) - y * math.cos(t)


def corner_margins(group, group_eval, other_group, other_eval):
    """Signed offset of each of the opposite group's starting corners from
    `group`'s outside pair, in px. Positive means the corner is outside the
    band, which is what a corner-safe configuration wants; negative means the
    outside strand cuts across inside the corner.

    The corner is the opposite group's EXTENDED start - where its continuation
    actually begins once that group is aligned, not the fixed point on the woven
    block. Extending a strand slides its start outwards along its own arm, which
    carries the corner out with it, so the opposite group's extension is the
    main lever on this margin. Measuring against the block instead makes the
    lever invisible and ranks configurations backwards.
    """
    if not group_eval.get('gaps') or not other_eval.get('gaps'):
        return []
    angle = group_eval['angle']
    edges = [_perp_coord(group_eval['starts'][0][0], group_eval['starts'][0][1], angle),
             _perp_coord(group_eval['starts'][-1][0], group_eval['starts'][-1][1], angle)]
    lo, hi = min(edges), max(edges)
    rows = []
    for i, s in enumerate(other_group):
        px, py = other_eval['starts'][i]
        w = _perp_coord(px, py, angle)
        margin = (lo - w) if abs(w - lo) <= abs(w - hi) else (w - hi)
        rows.append(dict(corner=s['name'], margin=margin,
                         side='outside' if margin >= 0 else 'inside'))
    rows.sort(key=lambda r: r['margin'])
    return rows


def worst_corner(h_group, h_eval, v_group, v_eval):
    """The tightest corner, or None without valid geometry.

    Measured in one direction only: the HORIZONTAL group's outside pair against
    the VERTICAL group's starting corners. The reverse is not a corner - at
    m = 1 the vertical group is a single pair spanning one gap, so almost every
    horizontal start lies far outside its band and the number means nothing.
    """
    rows = corner_margins(h_group, h_eval, v_group, v_eval)
    return rows[0] if rows else None


# A corner is safe when the outside pair reaches it - margin 0 puts the outer
# line exactly through the starting corner, which is the intent.
MIN_CORNER = 0.0


def natural_angle(group):
    """The generated continuation's own direction - the centre of the aligner's window."""
    g = group[0]
    return math.degrees(math.atan2(g['target'][1] - g['start'][1],
                                   g['target'][0] - g['start'][0]))


def aligner_window(group, ext0, half=20.0):
    """The angle range the repo's search actually looks at, at this outermost extension.

    It is centred on the first strand's direction to its target *after* that
    strand has been extended - so the window moves as the outermost pair grows,
    which is what puts the larger sizes out of reach.
    """
    g = group[0]
    x = g['start'][0] + ext0 * g['dir'][0]
    y = g['start'][1] + ext0 * g['dir'][1]
    a = math.degrees(math.atan2(g['target'][1] - y, g['target'][0] - x))
    return a - half, a + half


def in_aligner_window(group, angle_deg, ext0, half=20.0):
    lo, hi = aligner_window(group, ext0, half)
    return any(lo <= angle_deg + shift <= hi for shift in (-360.0, 0.0, 360.0))
