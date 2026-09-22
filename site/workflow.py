"""Server-owned snapshots and original MxN continuation/alignment operations."""
import copy
import contextlib
import importlib
import io
import json
import math
import uuid
from collections import OrderedDict
from ui_utils import _get_active_strands, _set_active_strands


class Workflow:
    def __init__(self, renderer):
        self.renderer = renderer
        self.snapshots = OrderedDict()

    def save(self, result):
        key = uuid.uuid4().hex
        self.snapshots[key] = {'settings': copy.deepcopy(result['settings']),
                               'document': copy.deepcopy(result['document']),
                               'emojis': copy.deepcopy(self.renderer._emoji_renderer._frozen_endpoint_emojis)}
        while len(self.snapshots) > 64:
            self.snapshots.popitem(last=False)
        result['snapshot'] = key
        return result

    def start(self, request):
        self.renderer._emoji_renderer.clear_cache()
        return self.save(self.renderer.render(request))

    def run(self, request):
        if not isinstance(request, dict):
            raise ValueError('Expected a workflow request')
        key = request.get('snapshot')
        if not isinstance(key, str) or key not in self.snapshots:
            raise ValueError('This pattern has expired. Return to Starting stitch and generate again.')
        source = copy.deepcopy(self.snapshots[key])
        self.renderer._emoji_renderer.clear_cache()
        self.renderer._emoji_renderer._frozen_endpoint_emojis = source.get('emojis')
        p, data = source['settings'], source['document']
        action = request.get('action')
        if action not in ('continue', 'preview', 'extend', 'align', 'display'):
            raise ValueError('Unknown continuation action')
        module = importlib.import_module('mxn_' + p['hand'] + '_continuation')
        direction = 'cw' if p['hand'] == 'lh' else 'ccw'
        if action == 'continue':
            # Same generator and transfer of colors as desktop generate_continuation.
            # The desktop continuation uses the stretched form of the starting stitch.
            prepared_stretch = not p['stretch']
            p.update(stretch=True, continuation=True)
            result = self.renderer.render(p)
            result['preparedStretch'] = prepared_stretch
            with contextlib.redirect_stdout(io.StringIO()):
                self.renderer._emoji_renderer.freeze_emoji_assignments(
                    self.renderer._main_window.canvas, self.renderer._prepared_bounds,
                    p['m'], p['n'], {'show': True, 'k': p['k'], 'direction': direction})
            return self.describe(self.save(result), module, direction)
        if not p['continuation'] and action != 'display':
            raise ValueError('Generate continuation first')
        options = request.get('options', {})
        if not isinstance(options, dict):
            raise ValueError('Invalid alignment settings')
        mode = options.get('mode', 'first_strand')
        if mode not in ('first_strand', 'avg_gaussian', 'custom'):
            raise ValueError('Invalid angle mode')
        def number(name, default, low, high):
            value = options.get(name, default)
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'{name} must be between {low} and {high}')
            return value
        for axis in ('h', 'v'):
            lo = number(axis+'Min', 0 if axis == 'h' else -90, -360, 360)
            hi = number(axis+'Max', 40 if axis == 'h' else -50, -360, 360)
            if mode == 'custom' and lo > hi:
                raise ValueError('Minimum angle must not exceed maximum angle')
            options[axis+'Min'], options[axis+'Max'] = lo, hi
        maximum, step = number('maximum', 200, 0, 1000), number('step', 10, 1, 100)
        strands = _get_active_strands(data)
        if action in ('extend', 'align', 'preview'):
            pairs = self.pairs(p, module, direction)
            extensions = options.get('extensions', {})
            if not isinstance(extensions, dict) or set(extensions) - {pair['key'] for pair in pairs}:
                raise ValueError('Invalid opposite pair')
            lookup = {s['layer_name']: s for s in strands}
            for pair in pairs:
                value = extensions.get(pair['key'], 0)
                if type(value) not in (int, float) or not math.isfinite(value) or not -200 <= value <= 500:
                    raise ValueError('Manual extension must be between -200 and 500 px')
                for label in pair['labels']:
                    base = lookup.get(label)
                    tail = lookup.get(label[:-1] + ('4' if label.endswith('2') else '5'))
                    if not base or not tail or not value:
                        continue
                    dx, dy = base['end']['x']-base['start']['x'], base['end']['y']-base['start']['y']
                    length = math.hypot(dx, dy)
                    if length < .001:
                        continue
                    point = dict(x=tail['start']['x']+value*dx/length, y=tail['start']['y']+value*dy/length)
                    tail['start'], base['end'] = point.copy(), point.copy()
                    for strand, index in ((tail, 0), (base, 1)):
                        if len(strand.get('control_points', [])) > index:
                            strand['control_points'][index] = point.copy()
                        strand['control_point_center'] = {a: (strand['start'][a]+strand['end'][a])/2 for a in ('x', 'y')}
        reports = []
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            if action == 'align':
                def group_options(axis):
                    return dict(angle_step_degrees=.5, max_extension=100.,
                                custom_angle_min=options.get(axis+'Min') if mode == 'custom' else None,
                                custom_angle_max=options.get(axis+'Max') if mode == 'custom' else None,
                                max_pair_extension=maximum, pair_extension_step=step, use_gpu=False,
                                angle_mode='first_strand' if mode == 'custom' else mode)
                strands, h_result, v_result, level = module.align_level_parallel(
                    strands, p['n'], p['m'], k=p['k'], direction=direction,
                    h_options=group_options('h'), v_options=group_options('v'))
                for axis, result in (('h', h_result), ('v', v_result)):
                    reports.append(dict(axis=axis, success=bool(result.get('success')),
                                        fallback=bool(result.get('is_fallback')),
                                        message=result.get('message', result.get('reason', '')),
                                        angle=result.get('angle_degrees'), gap=result.get('average_gap'),
                                        passes=level['passes']))
            _set_active_strands(data, strands)
            if action == 'display':
                for name in ('animals', 'names', 'transparent', 'scale'):
                    if name in options:
                        p[name] = options[name]
            result = self.renderer.render(p, data)
            result['alignment'] = reports
            if action == 'display':
                return self.save(result)
            return self.describe(self.save(result), module, direction, mode, options)

    @staticmethod
    def pairs(p, module, direction):
        result = []
        for axis, fn in [('H', module.get_horizontal_order_k), ('V', module.get_vertical_order_k)]:
            order = fn(p['m'], p['n'], p['k'], direction) or []
            for i in range(len(order)//2):
                labels = [order[i], order[-1-i]]
                result.append(dict(axis=axis, labels=labels, key='|'.join(labels)))
        return result

    def describe(self, result, module, direction, mode='first_strand', options=None):
        p = result['settings']
        with contextlib.redirect_stdout(io.StringIO()):
            preview = module.get_parallel_alignment_preview(_get_active_strands(result['document']), p['n'], p['m'],
                        k=p['k'], direction=direction, angle_mode='first_strand' if mode == 'custom' else mode)
        if mode == 'custom':
            for name, axis in [('horizontal', 'h'), ('vertical', 'v')]:
                if preview[name]:
                    preview[name]['angle_min'] = options[axis+'Min']
                    preview[name]['angle_max'] = options[axis+'Max']
        result['ranges'] = preview
        result['pairs'] = self.pairs(p, module, direction)
        return result
