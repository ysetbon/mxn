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
    in_band = all(MIN_GAP <= v <= MAX_GAP for v in gaps)
    ext_ok = all(-1e-6 <= e <= EXT_MAX + 1e-6 for e in exts)
    mean = sum(gaps) / len(gaps)

    reason = ''
    if not dir_ok:
        reason = 'the strand order folds back on itself - the gaps change sign'
    elif not in_band:
        bad = [v for v in gaps if v < MIN_GAP or v > MAX_GAP]
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


# --- corners: the one clearance neither alignment pass measures -------------
#
# `_numpy_try_all_angles` scores gaps between CONSECUTIVE strands of ONE group.
# The horizontal and vertical groups are aligned in two independent passes, so
# where a free end of one comes to rest against a strand of the other is scored
# by neither. At the extreme ends of both groups - the corners - that is exactly
# what decides whether the stitch reads cleanly or has a cap buried in a ribbon.
#
# A crossing between the groups is intended; that is what the _4/_5 masks are
# for. What is not intended is a free END arriving hard against another strand,
# so this measures endpoint-to-segment, not segment-to-segment.

OUTER_HALF = 25.0        # strand half width 23 + stroke 2


def _point_segment_distance(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)), t


def corner_clearances(group_a, eval_a, group_b, eval_b, half=OUTER_HALF):
    """Every free end of one group against every strand of the other.

    A continuation's free end is its `end`; its `start` is attached to its own
    _2/_3 arm. Clearance is edge to edge: centre distance minus the two half
    widths, so 0 means the outlines touch and negative means they overlap.
    """
    rows = []
    for label, (ga, ea), (gb, eb) in (('h_end_vs_v', (group_a, eval_a), (group_b, eval_b)),
                                      ('v_end_vs_h', (group_b, eval_b), (group_a, eval_a))):
        if not ea.get('gaps') or not eb.get('gaps'):
            return []
        for i, sa in enumerate(ga):
            px, py = ea['ends'][i]
            for j, sb in enumerate(gb):
                ax, ay = eb['starts'][j]
                bx, by = eb['ends'][j]
                d, t = _point_segment_distance(px, py, ax, ay, bx, by)
                rows.append(dict(kind=label, end=sa['name'], against=sb['name'],
                                 centre=d, clearance=d - 2 * half, along=t))
    rows.sort(key=lambda r: r['clearance'])
    return rows


def worst_corner(group_a, eval_a, group_b, eval_b, half=OUTER_HALF):
    """The tightest corner, or None if either group has no valid geometry."""
    rows = corner_clearances(group_a, eval_a, group_b, eval_b, half)
    return rows[0] if rows else None


# The gap floor is 56 px centre to centre between 50 px-wide outlines, so the
# clearance the aligner already demands between neighbours is 6 px. Holding the
# corners to the same figure keeps one rule for the whole stitch.
MIN_CORNER = MIN_GAP - 2 * OUTER_HALF


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
