#!/usr/bin/env python
"""Solve + apply ONE stitch exactly, writing the same files run_stitch.py writes.

    solve_stitch.py --m 1 --n 4 --k -1 --hand lh --out DIR
    solve_stitch.py --m 1 --n 4 --k -1 --hand rh --out DIR --mirror-of DIR/lh_1x4_k-1.json

Same pipeline as run_stitch.py - generate, align, apply, summarise - with the
aligner's grid search over (angle x per-pair extension) replaced by the closed
form in alignment_model.py. For each angle the extensions that give uniform gaps
follow directly, so instead of sampling a combinatorial space this scans one
angle axis and solves the rest.

Why bother: at k = -1 the repo's own search returns no alignment for 1x4 and up,
and the reason is its search *domain*, not the geometry. Its angle window spans
+/-20 deg around the first strand's direction and moves down as that strand is
extended, so from 1x5 on there is no angle inside the window that any extension
vector can satisfy. Exact solutions exist at every one of those sizes; they just
sit outside where the search was allowed to look.

The applying is still done by the repo's own `_build_config_dict` and
`apply_parallel_alignment`, so the geometry written out is built by repo code.

Use `--mirror-of` for the RH hand. RH's geometry is the LH geometry reflected
about x = 1232 - exactly, to 0.0 px - so its answer is LH's with the angle taken
to 180 - t and the extensions unchanged, and the result is verified against RH's
own geometry before being applied. Re-searching each hand instead lets them
settle on different members of the same solution family, which is what makes the
aligner's hand mirror disagree at some sizes.
"""
import argparse
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', '..', '..', 'src')))
sys.path.insert(0, HERE)

from ui_utils import _get_active_strands, _set_active_strands            # noqa: E402
# The RH module re-exports the aligner but not its helpers; _build_config_dict is
# pure geometry, so take it from the LH module for both hands.
import mxn_lh_continuation as _geom                                      # noqa: E402
import alignment_model as M                                             # noqa: E402

GAP = 56.01     # a hair above the 56 px floor, so float noise cannot fail the test


def build_group(all_strands, order):
    """The aligner's own per-strand structure, as align_*_strands_parallel builds it."""
    by = {s['layer_name']: s for s in all_strands if s['type'] == 'AttachedStrand'}
    out = []
    for name in order:
        s45 = by[name]
        s23 = by[('%d_2' if name.endswith('_4') else '%d_3') % s45['set_number']]
        out.append(dict(strand_4_5=s45, strand_2_3=s23,
                        type='_4' if name.endswith('_4') else '_5',
                        set_number=s45['set_number'],
                        original_start={'x': s45['start']['x'], 'y': s45['start']['y']},
                        target_position={'x': s45['end']['x'], 'y': s45['end']['y']}))
    return out


def search(group, gap=GAP, coarse=0.05, fine=0.001):
    """Best (angle, extensions) over the angle axis, ranked the way the aligner ranks.

    Uniform gaps at the floor minimise both of the aligner's first two criteria
    (first-last distance, then gap variance) at once, so the live tie-break is
    its third: least total extension. A solution the aligner's own angle window
    contains is preferred over one outside it, and the remaining ties - a
    two-strand group leaves whole arcs at effectively zero extension - go to the
    angle nearest the generated continuation.
    """
    plain = group
    natural = M.natural_angle(plain)

    def score(angle, exts):
        if not M.evaluate(plain, exts, angle)['valid']:
            return None
        off = abs((angle - natural + 180.0) % 360.0 - 180.0)
        return (0 if M.in_aligner_window(plain, angle, exts[0]) else 1,
                round(sum(exts), 1), off)

    best = None
    for i in range(int(round(360.0 / coarse))):
        angle = round(-180.0 + i * coarse, 6)
        exts = M.extensions_for_gap(plain, angle, gap)
        if exts is None:
            continue
        sc = score(angle, exts)
        if sc is not None and (best is None or sc < best[0]):
            best = (sc, angle, exts)
    if best is None:
        return None

    span = int(round(coarse / fine))
    for i in range(-span, span + 1):
        angle = round(best[1] + i * fine, 6)
        exts = M.extensions_for_gap(plain, angle, gap)
        if exts is None:
            continue
        sc = score(angle, exts)
        if sc is not None and sc < best[0]:
            best = (sc, angle, exts)
    return best[1], best[2]


def mirrored(plain, angle_lh, exts_lh):
    """LH's answer carried across the reflection, verified on RH's own geometry."""
    for cand in (180.0 - angle_lh, -angle_lh):
        if M.evaluate(plain, exts_lh, cand)['valid']:
            return cand, list(exts_lh)
    return None


def alignment_result(group, plain, exts, angle_deg):
    """Turn (angle, extensions) into the dict apply_parallel_alignment consumes."""
    count = len(group)
    q = M.pair_index(count)
    dxt = [g['target_position']['x'] - g['original_start']['x'] for g in group]
    dyt = [g['target_position']['y'] - g['original_start']['y'] for g in group]
    ref = math.atan2(dyt[0], dxt[0])
    goes_positive = [dxt[i] * math.cos(ref) + dyt[i] * math.sin(ref) >= 0
                     for i in range(count)]

    rad = math.radians(angle_deg)
    cfgs = [_geom._build_config_dict(group[i], exts[q[i]], rad, goes_positive[i])
            for i in range(count)]
    if any(c is None for c in cfgs):
        return None

    ev = M.evaluate(plain, exts, angle_deg)
    return dict(success=True, angle=rad, angle_degrees=angle_deg, configurations=cfgs,
                average_gap=ev['average_gap'], gap_variance=ev['gap_variance'],
                first_last_distance=ev['first_last_distance'],
                gaps=ev['gaps'], signed_gaps=ev['signed'],
                pair_extensions=tuple(exts), pair_extension=exts[0],
                min_gap=M.MIN_GAP, max_gap=M.MAX_GAP, valid=ev['valid'],
                message='closed-form solution at %.3f deg (pair exts: %s)'
                        % (angle_deg, tuple(round(x, 2) for x in exts)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--m', type=int, required=True)
    ap.add_argument('--n', type=int, required=True)
    ap.add_argument('--k', type=int, required=True)
    ap.add_argument('--hand', choices=['lh', 'rh'], required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--gap', type=float, default=GAP,
                    help='target gap; anything in [56, 69] is legal, the floor is optimal')
    ap.add_argument('--mirror-of',
                    help='an LH summary JSON to reflect instead of re-searching (RH only)')
    ap.add_argument('--h-angle', type=float, help='use this horizontal angle instead of solving')
    ap.add_argument('--h-ext', help='horizontal pair extensions, comma separated')
    ap.add_argument('--v-angle', type=float, help='use this vertical angle instead of solving')
    ap.add_argument('--v-ext', help='vertical pair extensions, comma separated')
    a = ap.parse_args()

    if a.hand == 'lh':
        import mxn_lh_continuation as mod
        direction = 'cw'
    else:
        import mxn_rh_continuation as mod
        direction = 'ccw'

    os.makedirs(a.out, exist_ok=True)
    tag = '%s_%dx%d_k%d' % (a.hand, a.m, a.n, a.k)
    started = time.time()

    src = mod.generate_json(m=a.m, n=a.n, k=a.k, direction=direction)
    open(os.path.join(a.out, tag + '_start.json'), 'w').write(src)
    data = json.loads(src)
    strands = _get_active_strands(data)
    h_names, h_order, v_names, v_order = mod._build_k_based_strand_sets(
        a.m, a.n, a.k, direction)

    mirror_src = json.load(open(a.mirror_of)) if a.mirror_of else None
    given = {'horizontal': (a.h_angle, a.h_ext), 'vertical': (a.v_angle, a.v_ext)}
    summaries = {}

    for label, order in (('horizontal', h_order), ('vertical', v_order)):
        group = build_group(strands, order)
        plain = M.group_from_strands(strands, order)
        forced = False

        angle_in, ext_in = given[label]
        if angle_in is not None and ext_in is not None:
            # Values handed in - typically steered by hand and copied out of the
            # bench. Applied as given, never quietly adjusted; the gap test still
            # runs and a failure is reported rather than repaired.
            exts = [float(x) for x in ext_in.replace(',', ' ').split()]
            want = len(M.pairs_of(len(plain)))
            if len(exts) != want:
                sys.exit('%s: expected %d extensions, got %d' % (label, want, len(exts)))
            ev = M.evaluate(plain, exts, angle_in)
            if not ev['valid']:
                print('  WARNING %s: the given values fail the gap test - %s'
                      % (label, ev['reason'] or 'invalid'))
            got = (angle_in, exts)
            forced = True
        elif mirror_src is not None:
            src_grp = mirror_src[label]
            got = mirrored(plain, src_grp['angle'], list(src_grp['extensions']))
        else:
            got = search(plain, a.gap)

        if got is None:
            summaries[label] = dict(success=False, fallback=False, preserved=False,
                                    angle=None, gap=None, gap_variance=None, spread=None,
                                    extensions=[], message='no solution found')
            continue

        angle, exts = got
        res = alignment_result(group, plain, exts, angle)
        strands = mod.apply_parallel_alignment(strands, res)
        summaries[label] = dict(
            success=True, fallback=False, preserved=False,
            angle=round(res['angle_degrees'], 4), gap=res['average_gap'],
            gap_variance=res['gap_variance'], spread=res['first_last_distance'],
            extensions=[round(x, 4) for x in exts],
            gaps=[round(g, 4) for g in res['gaps']],
            in_aligner_window=M.in_aligner_window(plain, angle, exts[0]),
            source='given' if forced else ('mirrored' if mirror_src else 'solved'),
            valid=res['valid'],
            message=res['message'])

    _set_active_strands(data, strands)
    open(os.path.join(a.out, tag + '_final.json'), 'w').write(json.dumps(data, indent=1))

    by = {s['layer_name']: s for s in strands}
    real = [s for s in strands if s['type'] != 'MaskedStrand']
    cont = [s['layer_name'] for s in real if s['layer_name'].endswith(('_4', '_5'))]

    def is_cont_mask(s):
        return any(x.endswith(('_4', '_5')) for x in
                   (s.get('first_selected_strand', ''), s.get('second_selected_strand', '')))

    def geom(name):
        s = by[name]
        dx, dy = s['end']['x'] - s['start']['x'], s['end']['y'] - s['start']['y']
        return dict(name=name, angle=round(math.degrees(math.atan2(dy, dx)), 2),
                    length=round(math.hypot(dx, dy), 2),
                    group='vertical' if name in v_names else
                          ('horizontal' if name in h_names else 'other'))

    summary = dict(
        tag=tag, m=a.m, n=a.n, k=a.k, hand=a.hand, direction=direction,
        totals=dict(strands=len(strands),
                    base=len([s for s in real if not s['layer_name'].endswith(('_4', '_5'))]),
                    continuation=len(cont),
                    base_masks=len([s for s in strands
                                    if s['type'] == 'MaskedStrand' and not is_cont_mask(s)]),
                    cont_masks=len([s for s in strands
                                    if s['type'] == 'MaskedStrand' and is_cont_mask(s)])),
        vertical_order=v_order, horizontal_order=h_order,
        base_masks=[s['layer_name'] for s in strands
                    if s['type'] == 'MaskedStrand' and not is_cont_mask(s)],
        cont_masks=[s['layer_name'] for s in strands
                    if s['type'] == 'MaskedStrand' and is_cont_mask(s)],
        geometry=[geom(x) for x in cont],
        horizontal=summaries['horizontal'], vertical=summaries['vertical'],
        search=dict(solver='closed-form', target_gap=a.gap, angle_step=0.001,
                    given_h=a.h_ext is not None, given_v=a.v_ext is not None,
                    ext_max=M.EXT_MAX, angle_mode='unrestricted',
                    h_pairs=max((len(h_order) + 1) // 2, 1),
                    v_pairs=max((len(v_order) + 1) // 2, 1),
                    mirrored_from=os.path.basename(a.mirror_of) if a.mirror_of else None),
        timing=dict(total_s=round(time.time() - started, 2)))
    open(os.path.join(a.out, tag + '.json'), 'w').write(json.dumps(summary, indent=1))

    h, v = summaries['horizontal'], summaries['vertical']
    print('%-16s H %-4s ang %8s gap %7s var %8s win %-5s | V %-4s ang %8s gap %7s | %5.1fs' % (
        tag,
        'ok' if h['success'] else 'FAIL',
        '%.3f' % h['angle'] if h['angle'] is not None else '-',
        '%.3f' % h['gap'] if h['gap'] else '-',
        '%.1e' % h['gap_variance'] if h['gap_variance'] is not None else '-',
        h.get('in_aligner_window'),
        'ok' if v['success'] else 'FAIL',
        '%.3f' % v['angle'] if v['angle'] is not None else '-',
        '%.3f' % v['gap'] if v['gap'] else '-',
        time.time() - started))


if __name__ == '__main__':
    main()
