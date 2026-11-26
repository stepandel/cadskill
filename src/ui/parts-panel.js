// The Parts list (show/hide, select, isolate) and the Selection read-out.
import { $ } from './dom.js';
import { view, select, setVisible, onSelect, onVisible, fit } from './viewer.js';

const rows = new Map();   // part -> { row, check }
const mm = (v) => (v >= 100 ? v.toFixed(1) : v.toFixed(2));

// Rebuilds the list from view.parts. Call after the parts change.
export function renderParts() {
  const tree = $('tree'); tree.textContent = ''; rows.clear();
  $('count').textContent = view.parts.length;
  const groups = new Map();
  for (const p of view.parts) {
    const k = p.path.slice(1).join(' / ');
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(p);
  }
  let n = 0;
  for (const [k, list] of groups) {
    if (groups.size > 1) {
      const g = document.createElement('label'); g.className = 'group';
      const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = true; cb.id = 'grp-' + (n++);
      cb.addEventListener('change', () => { for (const p of list) setVisible(p, cb.checked); });
      g.append(cb, document.createTextNode(k || 'Top level')); tree.append(g);
    }
    for (const p of list) {
      const row = document.createElement('div'); row.className = 'row';
      const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = p.mesh.visible; cb.id = 'vis-' + (n++);
      cb.setAttribute('aria-label', 'Show ' + p.name);
      cb.addEventListener('change', () => setVisible(p, cb.checked));
      const chip = document.createElement('span'); chip.className = 'chip'; chip.style.background = '#' + p.base.getHexString();
      const b = document.createElement('button'); b.type = 'button'; b.textContent = p.name;
      b.addEventListener('click', () => select(view.selected === p ? null : p));
      row.append(cb, chip, b); tree.append(row);
      rows.set(p, { row, check: cb });
    }
  }
}

onVisible((p) => { const r = rows.get(p); if (r) r.check.checked = p.mesh.visible; });

onSelect((p, prev, picked) => {
  rows.get(prev)?.row.classList.remove('on');
  const r = rows.get(p);
  if (r) { r.row.classList.add('on'); if (picked) r.row.scrollIntoView({ block: 'nearest' }); }
  $('isolate').disabled = !p;
  $('d-name').textContent = p ? (p.path.length ? p.path.join(' / ') + ' / ' : '') + p.name : 'Nothing selected';
  $('d-size').textContent = p && p.size ? mm(p.size[0]) + ' × ' + mm(p.size[1]) + ' × ' + mm(p.size[2]) + ' mm' : 'Click a part in the view or the list';
  $('d-vol').textContent = p && p.volume ? (p.approx ? '≈ ' : '') + (p.volume / 1000).toFixed(p.volume < 10000 ? 3 : 2) + ' cm³' + (p.approx ? ' (from mesh)' : '') : ' ';
  $('d-tri').textContent = p ? p.triangles.toLocaleString() + ' triangles' : ' ';
});

$('isolate').addEventListener('click', () => { if (!view.selected) return; for (const p of view.parts) setVisible(p, p === view.selected); fit(); });
$('showall').addEventListener('click', () => { for (const p of view.parts) setVisible(p, true); document.querySelectorAll('.group input').forEach((c) => { c.checked = true; }); fit(); });
