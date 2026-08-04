#!/usr/bin/env python
"""Generate + align ONE stitch and write everything a sheet needs.

    run_stitch.py --m 1 --n 3 --k -1 --hand lh --out DIR [--ext-max 200]
                  [--ext-step auto|10|20|...] [--angle-step 0.5] [--budget 400000]

Writes into DIR:
    <tag>_start.json      pattern before alignment (the starting stitch + raw continuation)
    <tag>_final.json      pattern after the align/apply passes (what the sheet draws)
    <tag>.json            summary: orders, masks, geometry, timings, search settings

<tag> is "<hand>_<m>x<n>_k<k>". Nothing here is specific to a size or to k: the
same call works for a box (k = 0, where the aligner is a documented no-op) and
for a twist (k != 0, where it searches).

The extension grid is the expensive axis — combos = (ext_max/step + 1) ** pairs —
so --ext-step auto picks the finest step whose combo count stays inside --budget
and records what it chose in the summary. Measured throughput of the repo's CPU
search is roughly 900 combos/s on 3 workers; the aligner itself refuses anything
over 10 M combos.
"""
import argparse
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_SRC = os.path.join(HERE, '..', '..', '..', '..', 'src')
sys.path.insert(0, os.path.abspath(REPO_SRC))

from ui_utils import _get_active_strands, _set_active_strands  # noqa: E402

EXT_STEPS = [10, 20, 25, 40, 50, 100]


def k_range(m, n):
    """Valid k values for this size (square and non-square differ)."""
    if m == n:
        return list(range(-(m - 1), m + 1))
    return list(range(-(m + n - 1), (m + n) + 1))


def pick_step(pairs, ext_max, budget):
    """Finest grid step whose combo count fits the budget."""
    for step in EXT_STEPS:
        combos = (ext_max // step + 1) ** max(pairs, 1)
        if combos <= budget:
            return step, combos
    step = EXT_STEPS[-1]
    return step, (ext_max // step + 1) ** max(pairs, 1)


def angle_of(s):
    dx = s['end']['x'] - s['start']['x']
    dy = s['end']['y'] - s['start']['y']
    return math.degrees(math.atan2(dy, dx)), math.hypot(dx, dy)


def is_cont_mask(s):
    return any(x.endswith(('_4', '_5')) for x in
               (s.get('first_selected_strand', ''), s.get('second_selected_strand', '')))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--m', type=int, required=True)
    ap.add_argument('--n', type=int, required=True)
    ap.add_argument('--k', type=int)
    ap.add_argument('--hand', choices=['lh', 'rh'])
    ap.add_argument('--out')
    ap.add_argument('--ext-max', type=int, default=200)
    ap.add_argument('--ext-step', default='auto')
    ap.add_argument('--angle-step', type=float, default=0.5)
    ap.add_argument('--angle-mode', default='first_strand',
                    choices=['first_strand', 'avg_gaussian', 'uniform'])
    ap.add_argument('--budget', type=int, default=400000,
                    help='max extension combos per group (~900 combos/s)')
    ap.add_argument('--check', action='store_true',
                    help='just print the valid k range for this size and exit')
    a = ap.parse_args()

    m, n, k, hand = a.m, a.n, a.k, a.hand
    if a.check:
        print('%dx%d valid k: %s' % (m, n, k_range(m, n)))
        return
    if k is None or hand is None or not a.out:
        sys.exit('--k, --hand and --out are required (or use --check)')
    if k not in k_range(m, n):
        # exit 3 = "this size has no such k" so a sweep can skip it and say so
        print('SKIP %dx%d k=%d out of range (valid: %s)'
              % (m, n, k, k_range(m, n)), file=sys.stderr)
        sys.exit(3)

    if hand == 'lh':
        import mxn_lh_continuation as mod
        direction = 'cw'                      # LH is always cw
    else:
        import mxn_rh_continuation as mod
        direction = 'ccw'                     # RH is always ccw

    os.makedirs(a.out, exist_ok=True)
    tag = '%s_%dx%d_k%d' % (hand, m, n, k)

    t0 = time.time()
    src = mod.generate_json(m=m, n=n, k=k, direction=direction)
    t_gen = time.time() - t0
    open(os.path.join(a.out, tag + '_start.json'), 'w').write(src)

    data = json.loads(src)
    strands = _get_active_strands(data)

    h_names, h_order, v_names, v_order = mod._build_k_based_strand_sets(m, n, k, direction)
    h_pairs = max((len(h_order) + 1) // 2, 1)
    v_pairs = max((len(v_order) + 1) // 2, 1)

    if a.ext_step == 'auto':
        h_step, h_combos = pick_step(h_pairs, a.ext_max, a.budget)
        v_step, v_combos = pick_step(v_pairs, a.ext_max, a.budget)
    else:
        h_step = v_step = int(a.ext_step)
        h_combos = (a.ext_max // h_step + 1) ** h_pairs
        v_combos = (a.ext_max // v_step + 1) ** v_pairs

    t0 = time.time()
    h_res = mod.align_horizontal_strands_parallel(
        strands, n, angle_step_degrees=a.angle_step, max_extension=100.0,
        max_pair_extension=a.ext_max, pair_extension_step=h_step,
        m=m, k=k, direction=direction, use_gpu=False, angle_mode=a.angle_mode)
    t_h = time.time() - t0
    if h_res.get('success') or h_res.get('is_fallback'):
        strands = mod.apply_parallel_alignment(strands, h_res)

    t0 = time.time()
    v_res = mod.align_vertical_strands_parallel(
        strands, n, m, angle_step_degrees=a.angle_step, max_extension=100.0,
        max_pair_extension=a.ext_max, pair_extension_step=v_step,
        k=k, direction=direction, use_gpu=False, angle_mode=a.angle_mode)
    t_v = time.time() - t0
    if v_res.get('success') or v_res.get('is_fallback'):
        strands = mod.apply_parallel_alignment(strands, v_res)

    _set_active_strands(data, strands)
    open(os.path.join(a.out, tag + '_final.json'), 'w').write(json.dumps(data, indent=1))

    by = {s['layer_name']: s for s in strands}
    real = [s for s in strands if s['type'] != 'MaskedStrand']
    cont = [s['layer_name'] for s in real if s['layer_name'].endswith(('_4', '_5'))]

    def geom(name):
        ang, ln = angle_of(by[name])
        return dict(name=name, angle=round(ang, 2), length=round(ln, 2),
                    group='vertical' if name in v_names else
                          ('horizontal' if name in h_names else 'other'))

    def summarize(res):
        return dict(success=bool(res.get('success')),
                    fallback=bool(res.get('is_fallback')),
                    preserved=bool(res.get('preserve_continuation')),
                    angle=res.get('angle_degrees'),
                    gap=res.get('average_gap'),
                    gap_variance=res.get('gap_variance'),
                    spread=res.get('first_last_distance'),
                    extensions=list(res.get('pair_extensions') or []),
                    message=res.get('message'))

    summary = dict(
        tag=tag, m=m, n=n, k=k, hand=hand, direction=direction,
        totals=dict(
            strands=len(strands),
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
        horizontal=summarize(h_res), vertical=summarize(v_res),
        search=dict(ext_max=a.ext_max, h_step=h_step, v_step=v_step,
                    h_pairs=h_pairs, v_pairs=v_pairs,
                    h_combos=h_combos, v_combos=v_combos,
                    angle_step=a.angle_step, angle_mode=a.angle_mode),
        timing=dict(generate_s=round(t_gen, 2), h_align_s=round(t_h, 2),
                    v_align_s=round(t_v, 2)))
    open(os.path.join(a.out, tag + '.json'), 'w').write(json.dumps(summary, indent=1))

    h, v = summary['horizontal'], summary['vertical']
    def state(x):
        return 'preserved' if x['preserved'] else ('ok' if x['success'] else
                                                   ('fallback' if x['fallback'] else 'FAIL'))
    print('%-16s strands %3d | H %-9s %8s gap %-7s | V %-9s %8s gap %-7s | %6.1fs (%s/%s combos)' % (
        tag, summary['totals']['strands'],
        state(h), '%.2f' % h['angle'] if h['angle'] is not None else '-',
        '%.2f' % h['gap'] if h['gap'] else '-',
        state(v), '%.2f' % v['angle'] if v['angle'] is not None else '-',
        '%.2f' % v['gap'] if v['gap'] else '-',
        t_gen + t_h + t_v, h_combos, v_combos))


if __name__ == '__main__':
    main()
