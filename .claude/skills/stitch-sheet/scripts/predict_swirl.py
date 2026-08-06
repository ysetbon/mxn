#!/usr/bin/env python
"""Predict a k = -1 swirl outright, from m and n, with no generator and no search.

    predict_swirl.py --m 13 --n 4

Everything the aligner would have searched for - the shared angle of each group,
the gap, and every pair extension - comes out of closed-form arithmetic in the
size alone. No pattern is generated, no geometry is probed, nothing is scanned.

The three steps:

1. THE LAYOUT IS A FORMULA. A horizontal group's 2n continuation starts sit at
   four fixed x columns and a 112 px row pitch, all linear in m and n (checked
   against the generator on all 63 sizes of the 8 x 8 grid, 0.0 px deviation).
   Only the starts and the _2/_3 directions are needed - the gaps never involve
   the targets, because a gap is a difference of the perpendicular coordinate
   W = x sin t - y cos t taken at the extended starts.

2. THE EXTENSIONS FOLLOW FROM (t, g). Writing Q = 8 + 112m and R = 24 - 112m,
   the gap equations are

       both ends   g =  R s - 144 c - s e_1 - c e_0
       odd  gaps   g =  (Q + e_j + e_j+1) s +  56 c
       even gaps   g = -(Q + e_j + e_j+1) s - 168 c
       middle      the same, with (e_j + e_j+1) replaced by 2 e_p-1

   which invert by telescoping from the middle pair outwards. (For m = 1 that is
   Q = 120, R = -88 - the form first found for the 1 x n family.)

3. THE ANGLE IS PINNED BY ONE EQUATION. Among the family the aligner ranks best
   the least-extension member, which is the one sitting on the edge of the
   feasible cone - the angle where the shallowest arm empties to exactly zero.
   That arm is pair min(2, n-1), and its extension is an affine combination of

       U = (g -  56 c)/s - Q        V = -(g + 168 c)/s - Q

   so setting it to zero gives  K2 c + K3 s = K1, a single linear equation in
   sin and cos with an explicit solution. No bisection, no scan.

The vertical group is the horizontal group of the transposed size turned 90
degrees, so it is the same computation on (n, m):

    V_LH(m, n) = H_LH(n, m) - 90        extensions unchanged
    H_RH       = 180 - H_LH             V_RH = -V_LH

Two sizes fall outside step 3, and each has its own closed form:

CASE A, 1 x 1. It has no k = -1 in range at all - a square allows k from -(m-1)
to m - so what it gets is its single twist, k = +1. Being its own transpose its
two groups must be identical, which pins it to the 45 degree diagonal, and there
the gap is just the diagonal of the offset:

    g = sqrt(2) (32 + E)    ->    E = g/sqrt(2) - 32     (7.605050814.. at 56.01)

CASE C, n = 1 with m >= 2. A one-pair group has no middle equation to telescope
from, so step 3 has nothing to pin. Solve the transposed group f(1, m) first,
read its uncorrected corner margin straight off the layout, and turn whatever it
falls short by into the extension - which makes the corner an INPUT rather than
something checked afterwards:

    M0 = 88 sin p + (32 + p_0) cos p           before any correction
    E  = max(0, (M* - M0)/sin p)               M* is the corner floor wanted
    t  solves  (56 - 112m) sin t - (120 + 2E) cos t = g,  quadrant II

At M* = 16 every m = 2..8 lands on exactly +16.0000 px with both gaps on target.
"""
import argparse
import math
from fractions import Fraction

MIN_GAP = 56.0
DEFAULT_GAP = 56.01          # a hair off the floor, so float noise cannot fail it
DEFAULT_CORNER = 16.0        # the floor the n = 1 boundary is solved to (case C)


def layout(m, n):
    """Every horizontal-group start and _2/_3 direction, from the size alone."""
    P, y0 = 56 * m, 388 - 56 * n
    out = []
    for i in range(2 * n):
        if i == 0:
            out.append(((1204 + P, y0), (0, -1)))
        elif i == 2 * n - 1:
            out.append(((1260 - P, y0 + 112 * n + 8), (0, 1)))
        elif i % 2:
            j = (i + 1) // 2
            out.append(((1228 - P, y0 + 144 + 112 * (j - 1)), (-1, 0)))
        else:
            j = i // 2
            out.append(((1236 + P, y0 + 88 + 112 * (j - 1)), (1, 0)))
    return out


def _uv_coefficients(n, index):
    """(a, b) with e_index = a*U + b*V, as exact fractions.

    e_p-1 = X_p-1 / 2 and e_j = X_j - e_j+1 downwards, where X_j is U for odd j
    and V for even. Only pairs 1 .. p-1 are reachable this way; pair 0 comes from
    the end equation instead and is never the binding one.
    """
    p = n
    a, b = Fraction(0), Fraction(0)
    if (p - 1) % 2:
        a = Fraction(1, 2)
    else:
        b = Fraction(1, 2)
    for j in range(p - 2, index - 1, -1):
        a, b = (-a, -b)
        if j % 2:
            a += 1
        else:
            b += 1
    return a, b


def shared_angle(m, n, gap=DEFAULT_GAP):
    """The horizontal group's shared angle, in degrees, in closed form."""
    if n < 2:
        raise ValueError('n must be at least 2; use the transpose for n = 1')
    Q = 8 + 112 * m
    a, b = _uv_coefficients(n, min(2, n - 1))

    # e = a*U + b*V = [a(g - 56c) - b(g + 168c)]/s - (a + b)Q, set to zero:
    #     (a - b) g - (56a + 168b) c = s (a + b) Q
    k1 = float(a - b) * gap
    k2 = float(56 * a + 168 * b)
    k3 = float(a + b) * Q

    r = math.hypot(k2, k3)
    if r < 1e-12 or abs(k1) > r:
        raise ValueError('no angle satisfies the zero-extension condition')
    phi = math.atan2(k3, k2)
    # two roots; the swirl is the one in the second quadrant sense
    for sign in (1.0, -1.0):
        t = math.degrees(phi + sign * math.acos(k1 / r))
        t %= 360.0
        if 90.0 < t < 180.0:
            return t
    raise ValueError('both roots fell outside the swirl quadrant')


def extensions(m, n, angle_deg, gap=DEFAULT_GAP):
    """The pair extensions at this angle and gap - telescoped, not searched."""
    t = math.radians(angle_deg)
    s, c = math.sin(t), math.cos(t)
    Q, R = 8 + 112 * m, 24 - 112 * m
    U = (gap - 56 * c) / s - Q
    V = -(gap + 168 * c) / s - Q

    p = n
    e = [0.0] * p
    e[p - 1] = (U if (p - 1) % 2 else V) / 2.0
    for j in range(p - 2, 0, -1):
        e[j] = (U if j % 2 else V) - e[j + 1]
    e[0] = (R * s - 144 * c - s * e[1] - gap) / c if p > 1 else 0.0
    return e


def _fold(a):
    """An angle folded into (-180, 180] - the same direction, stated once."""
    a %= 360.0
    return a - 360.0 if a > 180.0 else a


def one_by_one(gap=DEFAULT_GAP):
    """Case A - the 45 degree diagonal, the only member with identical groups."""
    return -135.0, 135.0, gap / math.sqrt(2.0) - 32.0


def boundary(m, gap=DEFAULT_GAP, min_corner=DEFAULT_CORNER):
    """Case C - the n = 1 column solved directly, to a chosen corner floor.

    Returns (angle, extension) for the one-pair horizontal group of an m x 1.
    """
    if m < 2:
        raise ValueError('case C needs m >= 2; 1 x 1 is case A')
    phi = shared_angle(1, m, gap)
    p0 = extensions(1, m, phi, gap)[0]
    r = math.radians(phi)
    m0 = 88.0 * math.sin(r) + (32.0 + p0) * math.cos(r)
    e = max(0.0, (min_corner - m0) / math.sin(r))

    a, b = 56.0 - 112.0 * m, -(120.0 + 2.0 * e)    # a sin t + b cos t = g
    rho = math.hypot(a, b)
    if rho < 1e-12 or abs(gap) > rho:
        raise ValueError('no one-pair angle reaches this gap')
    delta = math.atan2(b, a)
    base = math.asin(gap / rho)
    for root in (base, math.pi - base):
        t = math.degrees(root - delta) % 360.0
        if 90.0 < t < 180.0:
            return t, e
    raise ValueError('both roots fell outside the swirl quadrant')


def predict(m, n, gap=DEFAULT_GAP, min_corner=DEFAULT_CORNER):
    """Both groups of an m x n swirl at k = -1, left hand, in one call."""
    out = dict(m=m, n=n, gap=gap)

    if m == 1 and n == 1:                        # case A
        ha, va, e = one_by_one(gap)
        out.update(case='A', h_angle=ha, h_ext=[e], v_angle=va, v_ext=[e])
    elif n == 1:                                 # case C - the one-pair boundary
        ha, e = boundary(m, gap, min_corner)
        va = shared_angle(1, m, gap)
        out.update(case='C', min_corner=min_corner,
                   h_angle=ha, h_ext=[e],
                   v_angle=va - 90.0, v_ext=extensions(1, m, va, gap))
    else:                                        # case B, both groups
        ha = shared_angle(m, n, gap)
        out.update(case='B', h_angle=ha, h_ext=extensions(m, n, ha, gap))
        if m == 1:                               # the vertical group is one pair
            va, e = boundary(n, gap, min_corner)
            out.update(v_angle=va - 90.0, v_ext=[e])
        else:
            va = shared_angle(n, m, gap)
            out.update(v_angle=va - 90.0, v_ext=extensions(n, m, va, gap))

    # a shared angle is a direction, defined mod 360; fold the mirrored values
    # back into (-180, 180] so a consumer with a bounded angle axis - a slider, a
    # scan - cannot clamp them into a different configuration.
    out['h_angle_rh'] = _fold(180.0 - out['h_angle'])
    out['v_angle_rh'] = _fold(-out['v_angle'])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--m', type=int, required=True)
    ap.add_argument('--n', type=int, required=True)
    ap.add_argument('--gap', type=float, default=DEFAULT_GAP)
    ap.add_argument('--min-corner', type=float, default=DEFAULT_CORNER,
                    help='corner floor the n = 1 boundary is solved to (case C)')
    a = ap.parse_args()

    p = predict(a.m, a.n, a.gap, a.min_corner)
    print('%d x %d  k = %s  LH   target gap %.3f px   case %s'
          % (a.m, a.n, '+1' if p['case'] == 'A' else '-1', a.gap, p['case']))
    if 'h_angle' in p:
        print('  horizontal  angle %10.4f deg   (RH %9.4f)' % (p['h_angle'], p['h_angle_rh']))
        if p.get('h_ext'):
            print('              extensions %s' % ', '.join('%.4f' % x for x in p['h_ext']))
    if 'v_angle' in p:
        print('  vertical    angle %10.4f deg   (RH %9.4f)' % (p['v_angle'], p['v_angle_rh']))
        print('              extensions %s' % ', '.join('%.4f' % x for x in p['v_ext']))


if __name__ == '__main__':
    main()
