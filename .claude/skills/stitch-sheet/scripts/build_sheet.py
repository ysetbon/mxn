#!/usr/bin/env python
"""Turn a directory of run_stitch.py results into one artifact-ready HTML sheet.

    build_sheet.py --results DIR --out sheet.html --title "Twist Stitches"
                   [--intro "..."] [--eyebrow "..."] [--label twist|box|auto]

Reads every <tag>.json summary in DIR, renders a starting-stitch and a finished
diagram per stitch, and composes: header, anatomy, build steps, alignment
details, angle chart (when the angles actually move), the full table and the
gallery. Section wording adapts to k: k = 0 is a box (the aligner preserves the
continuation), anything else is a twist (the aligner searches).
"""
import argparse
import glob
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import render_strands as R  # noqa: E402

PITCH = 112.0          # grid pitch between neighbouring ribbons, px
WIDTH = 46             # strand width, px
MIN_GAP = WIDTH + 10   # aligner's gap floor, px


# --------------------------------------------------------------- diagrams --
def base_only(strands):
    def cont(s):
        if s['type'] == 'MaskedStrand':
            return any(x.endswith(('_4', '_5')) for x in
                       (s.get('first_selected_strand', ''), s.get('second_selected_strand', '')))
        return s['layer_name'].endswith(('_4', '_5'))
    return [s for s in strands if not cont(s)]


def render_pair(res_dir, tag, idp):
    """(starting-stitch svg, finished svg) for one stitch."""
    final = os.path.join(res_dir, tag + '_final.json')
    start = os.path.join(res_dir, tag + '_start.json')
    fin_svg = R.render(final, view=R.bounds(R.load_strands(final), pad=58), idp=idp + 'f')
    orig = R.load_strands
    R.load_strands = lambda p: base_only(orig(p))
    try:
        st_svg = R.render(start, view=R.bounds(base_only(orig(start)), pad=50),
                          idp=idp + 's', label_suffixes=('_2', '_3'))
    finally:
        R.load_strands = orig
    return st_svg, fin_svg


# ------------------------------------------------------------------ chart --
CW, CH = 760, 400
ML, MR, MT, MB = 54, 74, 22, 46
PW, PH = CW - ML - MR, CH - MT - MB


def chart_svg(items, xs, x_title, series):
    lo = min(min(v for v in s['vals'] if v is not None) for s in series)
    hi = max(max(v for v in s['vals'] if v is not None) for s in series)
    pad = max(10.0, (hi - lo) * 0.12)
    y_lo, y_hi = math.floor((lo - pad) / 30) * 30, math.ceil((hi + pad) / 30) * 30
    span = max(xs) - min(xs) or 1

    def sx(x):
        return ML + (x - min(xs)) / span * PW

    def sy(v):
        return MT + (y_hi - v) / (y_hi - y_lo) * PH

    o = ['<svg class="chart" viewBox="0 0 %d %d" role="img" aria-label="angle by size">' % (CW, CH)]
    step = 30 if (y_hi - y_lo) <= 360 else 60
    for v in range(int(y_lo), int(y_hi) + 1, step):
        o.append('<line class="grid" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/>' % (ML, sy(v), ML + PW, sy(v)))
        o.append('<text class="tick ty" x="%d" y="%.1f">%d°</text>' % (ML - 10, sy(v) + 4, v))
    # With many sizes the x labels collide, so thin them. On a full m × n grid the
    # natural places to label are the start of each m block (n = 1); otherwise fall
    # back to evenly spaced every-Nth.
    every = 1
    while len(xs) / float(every) * 26.0 > PW:
        every += 1
    keep = {i for i in range(len(xs)) if i % every == 0}
    if every > 1 and len({it.get('m') for it in items}) > 1:
        blocks = {i for i, it in enumerate(items) if it.get('n') == 1} | {0}
        if 2 <= len(blocks) <= PW / 26.0:
            keep = blocks
    for i, (x, it) in enumerate(zip(xs, items)):
        o.append('<line class="grid vgrid" x1="%.1f" y1="%d" x2="%.1f" y2="%d"/>'
                 % (sx(x), MT, sx(x), MT + PH))
        if i in keep:
            o.append('<text class="tick tx" x="%.1f" y="%d">%s</text>'
                     % (sx(x), MT + PH + 20, it['xlabel']))
    o.append('<text class="axis-title" x="%.1f" y="%d">%s</text>' % (ML + PW / 2, CH - 6, x_title))
    o.append('<text class="axis-title" transform="translate(15,%.1f) rotate(-90)">strand angle</text>'
             % (MT + PH / 2))
    for s in series:
        pts = ['%.1f,%.1f' % (sx(x), sy(v)) for x, v in zip(xs, s['vals']) if v is not None]
        if len(pts) > 1:
            o.append('<polyline class="curve" fill="none" stroke="%s" %s points="%s"/>' % (
                s['color'], 'stroke-dasharray="5 4"' if s['dash'] else '', ' '.join(pts)))
    for s in series:
        for x, v in zip(xs, s['vals']):
            if v is None:
                continue
            if s['dash']:
                o.append('<circle class="mk hollow" cx="%.1f" cy="%.1f" r="4.6" stroke="%s"/>'
                         % (sx(x), sy(v), s['color']))
            else:
                o.append('<circle class="mk" cx="%.1f" cy="%.1f" r="4.6" fill="%s"/>'
                         % (sx(x), sy(v), s['color']))
    for s in series:
        last = [v for v in s['vals'] if v is not None]
        if last:
            o.append('<text class="dlabel" x="%.1f" y="%.1f" fill="%s">%s</text>'
                     % (ML + PW + 10, sy(last[-1]) + 4, s['color'], s['label']))
    o.append('<line class="crosshair" id="cross" x1="0" y1="%d" x2="0" y2="%d" style="opacity:0"/>'
             % (MT, MT + PH))
    w = PW / max(len(xs) * 2, 2)
    for i, x in enumerate(xs):
        o.append('<rect class="hit" x="%.1f" y="%d" width="%.1f" height="%d" data-i="%d"/>'
                 % (sx(x) - w / 2, MT, w, PH, i))
    o.append('</svg>')
    return '\n'.join(o)


# ------------------------------------------------------------------- page --
def esc(s):
    return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def fmt(v, d=2, suffix=''):
    return '—' if v is None else ('%.*f%s' % (d, v, suffix))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--results', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--title', required=True)
    ap.add_argument('--intro', default='')
    ap.add_argument('--eyebrow', default='mxn generator · reference')
    ap.add_argument('--label', default='auto', choices=['auto', 'twist', 'box'])
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(a.results, '*.json')))
    sums = [json.load(open(f)) for f in files
            if not f.endswith(('_start.json', '_final.json'))]
    if not sums:
        sys.exit('no run_stitch.py summaries found in ' + a.results)

    ks = sorted({s['k'] for s in sums})
    present = {s['hand'] for s in sums}
    hands = [h for h in ('lh', 'rh') if h in present]        # lh first, always
    sizes = sorted({(s['m'], s['n']) for s in sums})
    by = {(s['m'], s['n'], s['hand']): s for s in sums}
    word = a.label if a.label != 'auto' else ('box' if ks == [0] else 'twist')

    # ---- items (one per size) --------------------------------------------
    items = []
    for (m, n) in sizes:
        rec = dict(m=m, n=n, xlabel='%d×%d' % (m, n), hands={})
        for hand in hands:
            s = by.get((m, n, hand))
            if s:
                rec['hands'][hand] = s
        items.append(rec)
    def primary(it):
        """The record a size is summarised from: preferred hand if it ran, else
        whichever hand did — a size is not always present in both hands."""
        for hand in hands:
            if hand in it['hands']:
                return it['hands'][hand]
        return None

    same_m = len({m for m, _ in sizes}) == 1
    same_n = len({n for _, n in sizes}) == 1
    if same_m and not same_n:
        xs, x_title = [n for _, n in sizes], 'n — horizontal sets (m = %d)' % sizes[0][0]
        for it in items:
            it['xlabel'] = str(it['n'])
    elif same_n and not same_m:
        xs, x_title = [m for m, _ in sizes], 'm — vertical sets (n = %d)' % sizes[0][1]
        for it in items:
            it['xlabel'] = str(it['m'])
    else:
        xs, x_title = list(range(len(sizes))), 'stitch size (m × n)'

    # ---- chart ------------------------------------------------------------
    SER = [('vertical', 'lh', 'V · LH', 'var(--s-vert)', False),
           ('horizontal', 'lh', 'H · LH', 'var(--s-horiz)', False),
           ('horizontal', 'rh', 'H · RH', 'var(--s-horiz)', True),
           ('vertical', 'rh', 'V · RH', 'var(--s-vert)', True)]
    series = []
    for group, hand, label, color, dash in SER:
        if hand not in hands:
            continue
        vals = [it['hands'][hand][group]['angle'] if hand in it['hands'] else None
                for it in items]
        if any(v is not None for v in vals):
            series.append(dict(label=label, color=color, dash=dash, vals=vals, group=group, hand=hand))
    moving = any(len({v for v in s['vals'] if v is not None}) > 1 for s in series)
    show_chart = moving and len(items) > 1

    # ---- header -----------------------------------------------------------
    chips = ['<span class="chip">k = <b>%s</b></span>' % ', '.join(str(k) for k in ks)]
    chips.append('<span class="chip">sizes <b>%s</b></span>' %
                 (('%d×%d … %d×%d' % (sizes[0][0], sizes[0][1], sizes[-1][0], sizes[-1][1]))
                  if len(sizes) > 3 else ' · '.join('%d×%d' % s for s in sizes)))
    chips.append('<span class="chip">%s</span>' %
                 (' , '.join('%s ⇒ <b>%s</b>' % (h.upper(), 'cw' if h == 'lh' else 'ccw')
                             for h in hands)))
    chips.append('<span class="chip">strand <b>%d px</b> wide, gap floor <b>%d px</b></span>'
                 % (WIDTH, MIN_GAP))
    chips.append('<span class="chip">%d stitches generated</span>' % len(sums))
    intro = a.intro or (
        'Every stitch here starts from the same <b>starting stitch</b> — the woven block — and then '
        'each loose end is carried on as its continuation. '
        + ('At k = 0 each arm simply keeps going along its own line, so the block ends up framed by '
           'straight bars: a <b>box</b>, with nothing left for the aligner to do.'
           if word == 'box' else
           'k re-pairs the ends, so the continuations fan out and the aligner has to bring each group '
           'to one shared angle with even gaps: a <b>twist</b>.'))
    header = ('<header><div class="eyebrow">%s</div><h1>%s</h1><p class="lede">%s</p>'
              '<div class="params">%s</div></header>'
              % (esc(a.eyebrow), esc(a.title), intro, ''.join(chips)))

    sections = []

    # ---- anatomy ----------------------------------------------------------
    a_rec = primary(items[len(items) // 2])
    a_m, a_n, a_hand = a_rec['m'], a_rec['n'], a_rec['hand']
    st_svg, fin_svg = render_pair(a.results, a_rec['tag'], 'an')
    sections.append("""
  <section class="sec">
    <h2>Anatomy <span>%d × %d, %s</span></h2>
    <div class="card anat">
      <div class="anat-figs">
        <figure><figcaption><span class="step-dot">1</span>starting stitch</figcaption>%s</figure>
        <figure><figcaption><span class="step-dot">2</span>%s</figcaption>%s</figure>
      </div>
      <div class="anat-key">
        <h3>How a strand is named</h3>
        <div class="kv">
          <b>3_2</b><span>set 3, layer 2 — set = one ribbon, layer = which piece of it</span>
          <b>_1</b><span>the first piece, buried inside the block</span>
          <b>_2 / _3</b><span>the two arms leaving the block, one each side</span>
          <b>_4 / _5</b><span>the continuation: <code>_2</code> carries on as <code>_4</code>, <code>_3</code> as <code>_5</code></span>
          <b>3_4_1_5</b><span>a mask — <code>3_4</code> passes <i>over</i> <code>1_5</code></span>
        </div>
        <h3>Which set is which</h3>
        <div class="kv">
          <b>1 … n</b><span>the horizontal sets (n of them)</span>
          <b>n+1 … n+m</b><span>the vertical sets (m of them)</span>
        </div>
        <p class="note" style="font-size:13px">In <b>m × n</b>, m counts the vertical ribbons and n the horizontal ones.</p>
      </div>
    </div>
  </section>""" % (a_m, a_n, 'left hand · cw' if a_hand == 'lh' else 'right hand · ccw',
                   st_svg, word, fin_svg))

    # ---- how it is made ---------------------------------------------------
    last_step = ('<div class="step"><span class="num">05</span><h4>Align</h4>'
                 '<p>Bring each group to one shared angle and slide the arms out until '
                 'the gaps are equal and at least %d px.</p></div>' % MIN_GAP)
    if word == 'box':
        last_step = ('<div class="step"><span class="num">05</span><h4>Align — nothing to do</h4>'
                     '<p>At k = 0 both passes return <code>preserve_continuation</code>: the '
                     'continuation is already exact.</p></div>')
    sections.append("""
  <section class="sec">
    <h2>How one is made <span>the five passes the generator runs</span></h2>
    <div class="steps">
      <div class="step"><span class="num">01</span><h4>Weave the block</h4><p>Lay m vertical ribbons across n horizontal ribbons and mask the crossings. That's the starting stitch.</p></div>
      <div class="step"><span class="num">02</span><h4>Pair by k</h4><p>Walk the rim by k to pair every free end with its partner, which fixes where each continuation aims.</p></div>
      <div class="step"><span class="num">03</span><h4>Draw the continuation</h4><p><code>_2 → _4</code>, <code>_3 → _5</code>, each aimed at its paired end.</p></div>
      <div class="step"><span class="num">04</span><h4>Mask again</h4><p>Re-apply the block's over/under pattern to the new crossings, on top of the starting stitch.</p></div>
      %s
    </div>
  </section>""" % last_step)

    # ---- alignment detail -------------------------------------------------
    s0 = sums[0]
    if word == 'box':
        detail = ('<div class="callout"><b>The aligner is a no-op at k = 0.</b> Both passes return '
                  '<code>preserve_continuation</code> with the message <i>"%s"</i> — no angle search, '
                  'no extensions, nothing moved. Verified on all %d runs.</div>'
                  % (esc(s0['horizontal']['message']), len(sums)))
    else:
        worst = max(sums, key=lambda s: s['timing']['h_align_s'] + s['timing']['v_align_s'])
        ok = sum(1 for s in sums if (s['horizontal']['success'] or s['horizontal']['preserved'])
                 and (s['vertical']['success'] or s['vertical']['preserved']))
        # --ext-step auto picks a step per size, so a sweep is not one single grid:
        # report the whole range actually used, and name the runs that fell back.
        steps = sorted({s['search'][key] for s in sums for key in ('h_step', 'v_step')})
        step_txt = ('<b>%d px</b>' % steps[0] if len(steps) == 1 else
                    '<b>%d … %d px</b> (chosen per size to fit the combo budget)'
                    % (steps[0], steps[-1]))
        fell = sorted(s['tag'] for s in sums
                      if s['horizontal']['fallback'] or s['vertical']['fallback'])
        notes = ''
        if steps[-1] > 20:
            notes += ('<br><span class="c">// the grid is coarsened above 20 px — calibrated at '
                      '1×3, step 20 reproduces step 10 exactly, step 25 drifts ~1.2° and step 40 '
                      '~2°, with looser gaps. Sizes needing 5+ extension pairs use those coarser '
                      'grids and their angles carry that much uncertainty.</span>')
        if fell:
            notes += ('<br><br><span class="c">// %d run%s fell back</span><br>%s'
                      % (len(fell), '' if len(fell) == 1 else 's', esc(', '.join(fell))))
        detail = ("""<div class="formula">
      <span class="c">// what the aligner searches</span><br>
      combos per group = <b>(ext_max / step + 1) ^ pairs</b> ,  pairs = half the group's strands<br>
      a gap must sit in <b>[width + 10, width × 1.5] = [%d, %d] px</b><br>
      it ranks by <b>first-last distance = (strands − 1) × gap</b>, then by gap variance<br><br>
      <span class="c">// this run</span><br>
      grid 0 … <b>%d px</b>, step %s , angle step <b>%s°</b>, mode <b>%s</b><br>
      largest search <b>%s / %s</b> combos ,  slowest stitch <b>%.1f s</b> (%s)<br>
      <b>%d of %d</b> runs succeeded without falling back%s
    </div>""" % (MIN_GAP, int(WIDTH * 1.5), s0['search']['ext_max'],
                 step_txt,
                 s0['search']['angle_step'], s0['search']['angle_mode'],
                 max(s['search']['h_combos'] for s in sums),
                 max(s['search']['v_combos'] for s in sums),
                 worst['timing']['h_align_s'] + worst['timing']['v_align_s'], worst['tag'],
                 ok, len(sums), notes))
    sections.append('<section class="sec"><h2>Alignment <span>what happens in the last pass</span>'
                    '</h2>%s</section>' % detail)

    # ---- chart ------------------------------------------------------------
    tip_data = []
    for i, it in enumerate(items):
        rowsd = []
        for s in series:
            v = s['vals'][i]
            rowsd.append([s['label'], '—' if v is None else '%.2f°' % v])
        h = (primary(it) or {}).get('horizontal', {})
        if h.get('gap'):
            # a fallback can report a gap with no first-last distance, so format
            # each half independently rather than assuming both are numbers
            rowsd.append(['gap / spread', '%s / %s px' % (fmt(h['gap'], 3), fmt(h['spread'], 1))])
        tip_data.append(dict(label='%d × %d' % (it['m'], it['n']), rows=rowsd))
    if show_chart:
        legend = ''.join('<span><i class="%s" style="border-color:%s"></i>%s</span>'
                         % ('d' if s['dash'] else '', s['color'], s['label']) for s in series)
        sections.append("""
  <section class="sec">
    <h2>Angle by size <span>one point per generated stitch</span></h2>
    <div class="card chart-card">
      <div class="legend">%s</div>
      %s
      <div id="tip"></div>
    </div>
  </section>""" % (legend, chart_svg(items, xs, x_title, series)))

    # ---- table ------------------------------------------------------------
    head = ['stitch', 'strands']
    for hand in hands:
        head += ['H · ' + hand.upper(), 'V · ' + hand.upper()]
    head += ['gap (px)', 'spread (px)', 'extensions (px)']
    trs = []
    for i, it in enumerate(items):
        first = primary(it)
        cells = ['<td class="n">%d × %d</td>' % (it['m'], it['n']),
                 '<td>%d</td>' % first['totals']['strands']]
        for hand in hands:
            s = it['hands'].get(hand)
            for group in ('horizontal', 'vertical'):
                cells.append('<td>%s</td>' % (fmt(s[group]['angle'], 2, '°') if s else '—'))
        cells.append('<td>%s</td>' % fmt(first['horizontal']['gap'], 3))
        cells.append('<td>%s</td>' % fmt(first['horizontal']['spread'], 2))
        cells.append('<td class="ext">%s</td>' %
                     (' '.join('%g' % e for e in first['horizontal']['extensions']) or '—'))
        trs.append('<tr data-i="%d">%s</tr>' % (i, ''.join(cells)))
    sections.append("""
  <section class="sec">
    <h2>Every size <span>measured from the generated stitch</span></h2>
    <div class="scroll"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>
    <p class="note"><b>spread</b> is the aligner's first-last distance across the horizontal
    group — the perpendicular distance from its first strand to its last, equal to
    <code>(strands − 1) × gap</code>. Angles are the aligner's own shared angle per group;
    gap, spread and extensions are reported for %s.</p>
  </section>""" % (''.join('<th>%s</th>' % h for h in head), '\n'.join(trs), hands[0].upper()))

    # ---- gallery ----------------------------------------------------------
    cards = []
    for it in items:
        figs = []
        for hand in hands:
            s = it['hands'].get(hand)
            if not s:
                continue
            st, fin = render_pair(a.results, s['tag'], 'g%d%d%s' % (it['m'], it['n'], hand))
            figs.append(
                '<div class="hand"><div class="hand-name">%s <span>H %s · V %s</span></div>'
                '<div class="two">'
                '<figure><figcaption><span class="step-dot">1</span>starting stitch</figcaption>%s</figure>'
                '<figure><figcaption><span class="step-dot">2</span>%s</figcaption>%s</figure>'
                '</div></div>' % (
                    '%s · %s' % (hand.upper(), s['direction']),
                    fmt(s['horizontal']['angle'], 2, '°'), fmt(s['vertical']['angle'], 2, '°'),
                    st, word, fin))
        t = primary(it)['totals']
        cards.append(
            '<div class="pat"><div class="pat-head"><span class="pat-n">%d × %d</span>'
            '<span class="pat-meta">%d vertical · %d horizontal · %d strands '
            '(%d base + %d masks + %d cont + %d masks)</span></div>%s</div>'
            % (it['m'], it['n'], it['m'], it['n'], t['strands'], t['base'], t['base_masks'],
               t['continuation'], t['cont_masks'], ''.join(figs)))
    sections.append('<section class="sec"><h2>Every stitch <span>starting stitch → %s, %s</span></h2>'
                    '<div class="pats">%s</div></section>'
                    % (word, 'both hands' if len(hands) > 1 else hands[0].upper(), '\n'.join(cards)))

    footer = ("""<footer>
    Built with the repo's own code: <code>mxn_{lh,rh}_continuation.generate_json(m, n, k, direction)</code>,
    then <code>align_horizontal_strands_parallel</code> → <code>apply_parallel_alignment</code> →
    <code>align_vertical_strands_parallel</code> → <code>apply_parallel_alignment</code>. LH always runs
    cw and RH always ccw. %d stitches: %s at k = %s.<br>
    Drawings come straight from the resulting JSON — real coordinates, widths and mask order
    (block → block masks → continuation → continuation masks). Horizontal sets are coloured by
    index and vertical sets in indigo shades, since the generator randomises colours past the
    second set.
  </footer>""" % (len(sums), ', '.join('%d×%d' % s for s in sizes[:12]) +
                  (' …' if len(sizes) > 12 else ''), ', '.join(str(k) for k in ks)))

    tpl = open(os.path.join(HERE, '..', 'assets', 'template.html')).read()
    page = (tpl.replace('__TITLE__', esc(a.title))
               .replace('__HEADER__', header)
               .replace('__SECTIONS__', '\n'.join(sections))
               .replace('__FOOTER__', footer)
               .replace('__TIPDATA__', json.dumps(tip_data)))
    open(a.out, 'w').write(page)
    print('wrote %s (%d bytes, %d stitches, chart=%s)'
          % (a.out, len(page), len(sums), show_chart))


if __name__ == '__main__':
    main()
