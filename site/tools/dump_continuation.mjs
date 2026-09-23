// Read {docs: [[m, n, k, hand], ...], flows: [{m, n, k, hand, action, options}, ...]}
// on stdin and print what continuation-engine.js computes for each, as JSON.
// Used by test_browser_continuation.py.
import {continuationDocument, pairs, alignmentPreview, getActiveStrands, runAction} from '../dist/continuation-engine.js';

let input = '';
for await (const chunk of process.stdin) input += chunk;
const {docs = [], flows = []} = JSON.parse(input);

// One copy of the strands: every history state holds the same list.
const compact = doc => ({...doc, strands: doc.states[0].data.strands,
  states: doc.states.map(({step, data: {strands, ...rest}}) => ({step, data: rest}))});

const out = {docs: [], flows: []};
for (const [m, n, k, hand] of docs) {
  const doc = continuationDocument(m, n, k, hand), strands = getActiveStrands(doc);
  out.docs.push({document: compact(doc), pairs: pairs(m, n, k, hand),
    previews: Object.fromEntries(['first_strand', 'avg_gaussian'].map(mode => [mode, alignmentPreview(strands, m, n, k, hand, mode)]))});
}
for (const {m, n, k, hand, action, options} of flows) {
  const settings = {m, n, k, hand}, base = runAction('continue', settings);
  const started = performance.now(), result = runAction(action, settings, base.document, options);
  out.flows.push({seconds: (performance.now() - started) / 1000, alignment: result.alignment, ranges: result.ranges,
    pairs: result.pairs, strands: getActiveStrands(result.document)});
}
process.stdout.write(JSON.stringify(out));
