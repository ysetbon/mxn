// Print generateDocument() for every size and variant as one JSON object, keyed
// "hand/variant/m/n". Used by test_browser_generators.py.
import {generateDocument} from '../dist/generators.js';

const out = {};
for (const hand of ['lh', 'rh']) for (const stretch of [false, true])
  for (let m = 1; m <= 10; m++) for (let n = 1; n <= 10; n++)
    out[`${hand}/${stretch ? 'stretch' : 'standard'}/${m}/${n}`] = generateDocument(m, n, hand, stretch);
process.stdout.write(JSON.stringify(out));
