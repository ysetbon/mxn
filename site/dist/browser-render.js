// Browser rendering shared by both pages: the vendored OpenStrandJS renderer
// (vendor/strand-renderer.js) draws the document, markers.js paints markers over it.
import {computeMarkerLayout, drawMarkers, preloadEmojiSet, strandBounds} from './markers.js';

/** Render an OSS history document like native_renderer.render; `frozen` pins marker assignments. */
export async function renderDocument(document, s, frozen = null) {
  const state = document.states?.find(x => x.step === document.current_step) || {data: document};
  const all = state.data.strands, strands = structuredClone(all);
  const bounds = strandBounds(strands), width = Math.ceil(bounds.width), height = Math.ceil(bounds.height);
  if (width * height * s.scale ** 2 > 36_000_000) throw Error('Image is too large at this resolution. Choose a lower scale.');
  const canvas = window.document.createElement('canvas');
  window.renderFixture(strands, {image_width: width * s.scale, image_height: height * s.scale, x_offset: -bounds.x * s.scale, y_offset: -bounds.y * s.scale,
    supersample: 2, zoom: s.scale, shadow_enabled: false, shadow_overrides: state.data.shadow_overrides, canvas_bg: s.transparent ? 'transparent' : 'white'}, canvas);
  if (s.animals || s.names) {
    const options = {strands: all, bounds, k: s.k, hand: s.hand, animals: s.animals, names: s.names, transparent: s.transparent, scale: s.scale, emojiSet: s.emojiSet, frozen};
    const layout = computeMarkerLayout(options);
    if (s.animals) await preloadEmojiSet(s.emojiSet, layout.items.map(x => x.txt));
    drawMarkers(canvas.getContext('2d'), options, layout);
  }
  return {png: canvas.toDataURL('image/png').split(',')[1], width: canvas.width, height: canvas.height, bounds,
    strands: all.filter(x => x.type !== 'MaskedStrand').length, crossings: all.filter(x => x.type === 'MaskedStrand').length};
}
