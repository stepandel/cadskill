// The History list: one block per step with its sliders, rollback and delete,
// plus the buttons that add a step. It only sends commands; the list is redrawn
// from the document the worker answers with.
import { OPS } from '../cad-doc.js';
import { $ } from './dom.js';

let send = () => {}, target = () => null;
let drawn = '', drag = 0;

// send(cmd) queues a document command; target() is the part a new step should apply to.
export function initHistory(opts) {
  send = opts.send; target = opts.target;
  for (const b of $('add').querySelectorAll('button')) {
    b.addEventListener('click', () => {
      const t = target();
      send({ type: 'add', op: b.dataset.op, params: OPS[b.dataset.op].target ? { body: t && t.id } : {} });
    });
  }
}

export function renderSteps(doc, errors) {
  const box = $('steps');
  // The list is rebuilt only when its structure changes, so a slider being dragged is never replaced under the pointer.
  const sig = JSON.stringify([doc.features.map((f) => [f.id, f.op, f.name]), doc.cursor, errors]);
  if (sig !== drawn) {
    drawn = sig; box.textContent = '';
    doc.features.forEach((f, i) => box.append(stepBlock(doc, errors, f, i)));
  }
  // Values can change without the list changing (undo). The slider being dragged is left alone.
  for (const inp of box.querySelectorAll('input[type=range]')) {
    const f = doc.features.find((x) => x.id === inp.dataset.step);
    const v = f.params[inp.dataset.key];
    if (inp !== document.activeElement) inp.value = v;
    inp.previousElementSibling.textContent = inp === document.activeElement ? inp.value : v;
  }
}

function stepBlock(doc, errors, f, i) {
  const def = OPS[f.op], n = doc.features.length;
  const step = document.createElement('div');
  step.className = 'step' + (i >= doc.cursor ? ' off' : '') + (errors[f.id] ? ' bad' : '');
  const head = document.createElement('div'); head.className = 'stephead';
  const pin = document.createElement('button'); pin.type = 'button'; pin.textContent = i + 1;
  const here = doc.cursor === i + 1 && doc.cursor < n;
  pin.setAttribute('aria-pressed', String(here));
  pin.setAttribute('aria-label', here ? 'Apply all steps again' : 'Roll back to step ' + (i + 1));
  pin.title = pin.getAttribute('aria-label');
  pin.addEventListener('click', () => send({ type: 'roll', cursor: here ? n : i + 1 }));
  const title = document.createElement('b'); title.textContent = f.op === 'import' ? 'Import ' + f.name : f.name || def.label;
  const del = document.createElement('button'); del.type = 'button'; del.className = 'del'; del.textContent = '×';
  del.setAttribute('aria-label', 'Delete step ' + (i + 1)); del.title = 'Delete this step';
  del.addEventListener('click', () => send({ type: 'remove', id: f.id }));
  head.append(pin, title, del); step.append(head);
  if (errors[f.id]) { const e = document.createElement('p'); e.className = 'steperr'; e.textContent = errors[f.id]; step.append(e); }
  for (const d of def.params) {
    const row = document.createElement('div'); row.className = 'param';
    const id = 'p-' + f.id + '-' + d.key;
    const label = document.createElement('label'); label.htmlFor = id; label.textContent = d.label;
    const out = document.createElement('output');
    const inp = document.createElement('input'); inp.type = 'range'; inp.id = id; inp.min = d.min; inp.max = d.max; inp.step = d.step;
    inp.dataset.step = f.id; inp.dataset.key = d.key;
    inp.addEventListener('input', () => { out.textContent = inp.value; send({ type: 'update', id: f.id, params: { [d.key]: Number(inp.value) }, merge: id + ':' + drag }); });
    inp.addEventListener('change', () => { drag++; });   // releasing the slider ends one undo entry
    row.append(label, out, inp); step.append(row);
  }
  return step;
}
