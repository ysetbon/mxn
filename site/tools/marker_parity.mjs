// Marker placement from dist/markers.js for the cases on stdin, as JSON on stdout.
// Input: {cases, extents: {txt: {left,right,top,bottom}}, names: {name: [w, h]}, labels: {count, k, direction}}.
// The font measurements come from Qt so only the placement logic is compared.
// Used by test_browser_markers.py.
import {generateDocument} from '../dist/generators.js';
import {computeMarkerLayout, computeSlotsFromStrands, freezeAssignments, makeLabels, rotateLabels, strandBounds} from '../dist/markers.js';

const input = JSON.parse(await new Promise(resolve => { let s = ''; process.stdin.on('data', d => { s += d; }).on('end', () => resolve(s)); }));
const strandsOf = (m, n, hand, stretch) => { const d = generateDocument(m, n, hand, stretch); return d.states.find(x => x.step === d.current_step).data.strands; };
const measure = {extents: txt => input.extents[txt], nameSize: name => input.names[name]};
const results = input.cases.map(c => {
  const strands = strandsOf(c.m, c.n, c.hand, c.stretch), bounds = strandBounds(strands);
  let frozen = null;
  if (c.freeze) {
    const source = strandsOf(c.m, c.n, c.hand, c.freeze.stretch);
    frozen = freezeAssignments({strands: source, bounds: strandBounds(source), k: c.freeze.k, hand: c.hand});
  }
  const layout = computeMarkerLayout({strands, bounds, m: c.m, n: c.n, k: c.k, hand: c.hand, animals: c.animals, names: c.names, transparent: c.transparent, frozen, ...measure});
  return {bounds, frozen, layout, slots: computeSlotsFromStrands(strands, bounds, c.m, c.n)};
});
const {count, k, direction} = input.labels;
process.stdout.write(JSON.stringify({results, labels: makeLabels(count), rotated: rotateLabels(makeLabels(count), k, direction)}));
