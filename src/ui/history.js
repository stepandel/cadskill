// The history panel: every saved version of the model, newest first. Clicking
// one shows it in the view; the model itself stays at its latest version
// (going back for real is Claude's restore_version).
import { $ } from './dom.js';

const panel = $('history'), list = $('versions'), toggle = $('toggle-history');
let load = null;          // () => Promise<{ versions }>
let pick = () => {};      // (version) => void
let versions = [];
let failed = '';
let mark = { latest: 0, shown: 0 };

export function setupHistory(opts) { load = opts.load; pick = opts.pick; }

// Re-reads the version list, if the panel is open (it is read again on opening).
export async function refreshHistory() {
  if (panel.hidden || !load) return;
  try { versions = (await load()).versions || []; failed = ''; } catch (e) { failed = 'Could not read the history.'; }
  render();
}

export function markHistory(latest, shown) { mark = { latest, shown }; render(); }

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

// "2026-11-26 14:03:22" (the server's local time) -> "14:03" today, "Nov 25 14:03" before.
function when(stamp) {
  const [date, time = ''] = String(stamp || '').split(' ');
  const now = new Date();
  const today = [now.getFullYear(), String(now.getMonth() + 1).padStart(2, '0'), String(now.getDate()).padStart(2, '0')].join('-');
  const hm = time.slice(0, 5);
  if (date === today) return hm;
  const [y, m, d] = date.split('-').map(Number);
  if (!y) return stamp || '';
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' + hm;
}

function render() {
  $('count').textContent = versions.length ? String(versions.length) : '';
  if (failed || !versions.length) {
    list.replaceChildren(el('li', 'hint', failed || 'No versions yet.'));
    return;
  }
  list.replaceChildren(...versions.slice().reverse().map((v) => {
    const b = el('button', 'ver');
    b.type = 'button';
    if (v.version === mark.shown) b.setAttribute('aria-current', 'true');
    const head = el('span', 'vhead');
    head.append(el('b', null, 'v' + v.version));
    if (v.version === mark.latest) head.append(el('span', 'tag', 'latest'));
    head.append(el('time', null, when(v.time)));
    b.append(head);
    if (v.note) b.append(el('span', 'vnote', v.note));
    if (v.summary) { const s = el('span', 'vsum', v.summary); s.title = v.summary; b.append(s); }
    b.addEventListener('click', () => pick(v.version));
    const li = el('li');
    li.append(b);
    return li;
  }));
  const current = list.querySelector('[aria-current="true"]');
  if (current && !panel.hidden) current.scrollIntoView({ block: 'nearest' });
}

function setOpen(open) {
  panel.hidden = !open;
  toggle.setAttribute('aria-pressed', String(open));
  if (open) { render(); refreshHistory(); }
}
toggle.addEventListener('click', () => setOpen(panel.hidden));
$('close-history').addEventListener('click', () => { setOpen(false); toggle.focus(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !panel.hidden) setOpen(false); });
