// The top-right readout and the dock label. They describe the selected part,
// the only part, or the whole model.
import { $ } from './dom.js';
import { view, modelSize, onSelect } from './viewer.js';

const mm = (v) => (v >= 100 ? v.toFixed(1) : v.toFixed(2));
const dims = (v) => mm(v[0]) + ' × ' + mm(v[1]) + ' × ' + mm(v[2]) + ' mm';
const volume = (p) => (p.approx ? '≈ ' : '') + (p.volume / 1000).toFixed(p.volume < 10000 ? 3 : 2) + ' cm³';
let sourceName = 'Model';

// The name shown when no single part is being described: the model's name and version.
export function setSourceName(name) { sourceName = name; }

export function describe() {
  const p = view.selected || (view.parts.length === 1 ? view.parts[0] : null);
  const size = modelSize();
  if (p) {
    $('r-size').textContent = p.size ? dims(p.size) : ' ';
    $('r-meta').textContent = p.kind === 'curve' ? 'Sketch edges' : p.kind === 'point' ? 'Construction points'
      : (p.volume ? volume(p) + '  ·  ' : '') + p.triangles.toLocaleString() + ' triangles';
    $('name').textContent = p.name; $('name').title = (p.path.length ? p.path.join(' / ') + ' / ' : '') + p.name;
    $('chip').style.background = '#' + p.base.getHexString();
  } else {
    const tris = view.parts.reduce((a, q) => a + q.triangles, 0);
    $('r-size').textContent = size ? dims(size) : ' ';
    $('r-meta').textContent = size ? view.parts.length + ' parts  ·  ' + tris.toLocaleString() + ' triangles' : ' ';
    $('name').textContent = sourceName; $('name').title = sourceName;
    $('chip').style.background = '';
  }
}
onSelect(describe);
