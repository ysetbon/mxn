// Module Web Worker running the continuation alignment off the page's thread:
//   new Worker(new URL('./alignment-worker.js', import.meta.url), {type: 'module'})
// Requests (each with an `id` echoed back):
//   {type: 'align', strands, m, n, k, hand, hOptions, vOptions} -> alignLevel(...) result
//   {type: 'run', action, settings, document, options}          -> runAction(...) result
//   {type: 'dispose'} ends the helper workers.
// Replies: {id, type: 'progress', axis, pass, completed, total, valid}, then
// {id, type: 'result', result} or {id, type: 'error', message}.
// Large combo searches are split across nested copies of this worker (the way
// Python uses a process pool); they answer {type: 'chunk'} requests. Chunks are
// merged in combo order, so the result is the same as the serial search.
import {alignLevelSteps, runActionSteps, alignmentReports, evaluateCombos, mergeChunks} from './continuation-engine.js';

const PARALLEL_MIN_COMBOS = 2048;
let helpers = null;

function helperPool() {
  if (helpers) return helpers;
  const count = Math.min(8, Math.max(1, (self.navigator?.hardwareConcurrency || 2) - 1));
  helpers = [];
  if (typeof Worker === 'undefined' || count < 2) return helpers;
  try {
    for (let i = 0; i < count; i++) helpers.push(new Worker(new URL(import.meta.url), {type: 'module'}));
  } catch {
    helpers.forEach(w => w.terminate());
    helpers = [];
  }
  return helpers;
}

function searchParallel({task, total}, pool, report) {
  const size = Math.max(256, Math.ceil(total / (pool.length * 8)));
  const ranges = [];
  for (let start = 0; start < total; start += size) ranges.push([start, Math.min(start + size, total)]);
  const results = [];
  let next = 0, done = 0, completed = 0, valid = 0;
  return new Promise((resolve, reject) => {
    const feed = worker => {
      if (next >= ranges.length) return;
      const [start, end] = ranges[next++];
      worker.onmessage = ({data}) => {
        if (data.type === 'error') { reject(new Error(data.message)); return; }
        results.push(data.result);
        completed += data.result.combos_evaluated; valid += data.result.valid_results.length;
        report(completed, valid);
        if (++done === ranges.length) resolve(mergeChunks(results, task.pairs.length / 2));
        else feed(worker);
      };
      worker.onerror = event => reject(new Error(event.message || 'Alignment helper failed'));
      worker.postMessage({type: 'chunk', task, start, end});
    };
    if (!ranges.length) resolve(mergeChunks([], task.pairs.length / 2));
    pool.forEach(feed);
  });
}

async function drive(gen, id) {
  let step = gen.next();
  while (!step.done) {
    const request = step.value, {axis, pass, task, total} = request;
    const report = (completed, valid) => self.postMessage({id, type: 'progress', axis, pass, completed, total, valid});
    report(0, 0);
    const pool = total >= PARALLEL_MIN_COMBOS ? helperPool() : [];
    const merged = pool.length
      ? await searchParallel(request, pool, report)
      : mergeChunks([evaluateCombos(task, 0, total, null, null, report)], task.pairs.length / 2);
    report(total, merged.valid_results.length);
    step = gen.next(merged);
  }
  return step.value;
}

self.onmessage = async ({data}) => {
  const {id, type} = data;
  try {
    if (type === 'chunk') {
      self.postMessage({type: 'chunk', result: evaluateCombos(data.task, data.start, data.end)});
    } else if (type === 'align') {
      const {strands, m, n, k, hand, hOptions, vOptions} = data;
      const out = await drive(alignLevelSteps(strands, m, n, k, hand, hOptions, vOptions), id);
      self.postMessage({id, type: 'result', result: {...out, reports: alignmentReports(out)}});
    } else if (type === 'run') {
      const {action, settings, document, options} = data;
      self.postMessage({id, type: 'result', result: await drive(runActionSteps(action, settings, document, options), id)});
    } else if (type === 'dispose') {
      (helpers || []).forEach(w => w.terminate());
      helpers = null;
    }
  } catch (error) {
    self.postMessage({id, type: 'error', message: error.message});
  }
};
