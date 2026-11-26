// Page entry point: starts the kernel, redraws from each document the worker
// answers with, saves it on this device, and wires the toolbar.
import { openStore } from '../cad-store.js';
import { $ } from './dom.js';
import { view, setParts, select, setEdges, fit } from './viewer.js';
import { describe, setSourceName } from './readout.js';
import { initHistory, renderSteps } from './history-panel.js';
import { startKernel } from './kernel-client.js';

const msg = $('msg'), meter = $('meter');
function say(text, bad) { msg.textContent = text; msg.classList.toggle('bad', !!bad); msg.hidden = false; }
function quiet() { msg.hidden = true; }   // once a model is up, the readout carries the numbers
let doc = null, stepName = '', keepMessage = false;
describe();

const kernel = startKernel({
  boot(loaded, total) {
    meter.firstElementChild.style.width = Math.round((loaded / total) * 100) + '%';
    say('Loading the geometry kernel  ' + (loaded / 1048576).toFixed(1) + ' / ' + (total / 1048576).toFixed(1) + ' MB');
  },
  ready() { meter.hidden = true; reopen(); },
  fatal(message) { say(message, true); meter.hidden = true; },
  progress(m) { say(m.stage === 'reading' ? 'Reading ' + (stepName || 'your saved model') + ' (large files take a few seconds)' : 'Reading part ' + m.parts); },
  error(m) {
    if (m.kind === 'load') { keepMessage = true; send({ type: 'sample' }); say('Your saved model could not be reopened (' + m.message + '). Showing the sample part.', true); }
    else say(m.message, true);
  },
  result: apply,
});
const send = kernel.send;
initHistory({ send, target: () => view.selected || view.parts[view.parts.length - 1] });

/* ---------- redraw from the document ---------- */
function apply(m) {
  const selId = view.selected && view.selected.id;
  const partsChanged = setParts(m.parts);
  doc = m.doc;
  renderSteps(doc, m.errors);
  const imported = doc.features.find((f) => f.op === 'import');
  setSourceName(imported ? imported.name : 'Model');
  select(view.parts.find((p) => p.id === selId) || null);   // also redraws the readout and dock label
  $('undo').disabled = !m.canUndo; $('redo').disabled = !m.canRedo;
  if (keepMessage) keepMessage = false; else quiet();
  if (['open', 'sample', 'load'].includes(m.kind) || (partsChanged && ['undo', 'redo'].includes(m.kind))) fit();
  if (m.kind !== 'load') save();
}

/* ---------- saving on this device ---------- */
// The step list is saved after every change; imported files are saved once, when opened.
const storeReady = openStore();
let store = null, saveTimer = 0, lostFile = false;
function saved(ok) { $('saved').textContent = ok ? 'saved on this device' : 'not saved'; }
function save() {
  if (!store) { saved(false); return; }
  clearTimeout(saveTimer);
  const snapshot = doc;
  saveTimer = setTimeout(() => store.saveDoc(snapshot).then(() => saved(!lostFile), () => saved(false)), 300);
}
async function reopen() {
  store = await storeReady;
  let last = null; const blobs = {};
  try {
    last = store && await store.loadDoc();
    if (last) {
      for (const f of last.features) if (f.op === 'import') blobs[f.params.blob] = await store.getBlob(f.params.blob);
      store.pruneBlobs(Object.keys(blobs)).catch(() => {});
    }
  } catch (e) { last = null; }
  saved(!!store);
  send(last ? { type: 'load', doc: last, blobs } : { type: 'sample' });
}

/* ---------- opening STEP files ---------- */
async function openFile(file) {
  if (!file) return;
  if (!/\.(step|stp)$/i.test(file.name)) { say('"' + file.name + '" is not a STEP file. Choose a .step or .stp file.', true); return; }
  if (!kernel.isReady()) { say('The kernel is still loading. Try again in a moment.', true); return; }
  stepName = file.name;
  say('Reading ' + file.name);
  let text;
  try { text = await file.text(); } catch (e) { say('Could not read ' + file.name + ': ' + e.message, true); return; }
  const blob = crypto.randomUUID();
  lostFile = false;
  if (store) store.putBlob(blob, text).catch(() => { lostFile = true; saved(false); });   // too large for this browser's storage
  send({ type: 'open', blob, text, name: file.name });
}
$('file').addEventListener('change', (e) => { openFile(e.target.files[0]); e.target.value = ''; });
const main = $('main');
let dragDepth = 0;
main.addEventListener('dragenter', (e) => { e.preventDefault(); dragDepth++; main.classList.add('dragging'); });
main.addEventListener('dragover', (e) => e.preventDefault());
main.addEventListener('dragleave', () => { if (--dragDepth <= 0) { dragDepth = 0; main.classList.remove('dragging'); } });
main.addEventListener('drop', (e) => { e.preventDefault(); dragDepth = 0; main.classList.remove('dragging'); openFile(e.dataTransfer.files[0]); });

/* ---------- toolbar ---------- */
$('sample').addEventListener('click', () => send({ type: 'sample' }));
$('undo').addEventListener('click', () => send({ type: 'undo' }));
$('redo').addEventListener('click', () => send({ type: 'redo' }));
addEventListener('keydown', (e) => {
  if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== 'z') return;
  e.preventDefault();
  if (e.shiftKey ? !$('redo').disabled : !$('undo').disabled) send({ type: e.shiftKey ? 'redo' : 'undo' });
});
$('toggle-history').addEventListener('click', () => {
  const open = $('history').hidden;
  $('history').hidden = !open;
  $('toggle-history').setAttribute('aria-pressed', String(open));
});
$('fit').addEventListener('click', fit);
$('edges').addEventListener('click', () => {
  const on = $('edges').getAttribute('aria-pressed') !== 'true';
  $('edges').setAttribute('aria-pressed', String(on));
  setEdges(on);
});
