// Build steps use the same floating-panel pattern as Revisions. The geometry
// is drawn by app.js in the existing model canvas.
import { $ } from './dom.js';

let options = {}, context = null, data = null, chain = 0, selected = null, serial = 0;
const panel = $('steps-panel'), list = $('steps-list'), shapes = $('steps-shape');

export function setupSteps(opts) { options = opts; }

export function setStepsOpen(open) {
  panel.hidden = !open;
  $('build-steps').setAttribute('aria-pressed', String(open));
  if (open) { options.opened?.(); refresh(); }
}

export function setStepsSource(model, version) {
  const key = model + '@' + version;
  if (context?.key !== key) { data = null; chain = 0; ++serial; $('step-count').textContent = ''; }
  context = { model, version, key };
  selected = null;
  $('steps-source').textContent = model + ' · v' + version;
  if (!panel.hidden) refresh();
  else render();
}

export function markStep(shape, step) { selected = step == null ? null : { chain: shape, step }; render(); }

function message(text, bad = false) {
  $('steps-message').textContent = text;
  $('steps-message').classList.toggle('bad', bad);
  $('steps-message').hidden = !text;
}

async function refresh() {
  if (!context) return;
  if (data) { render(); return; }
  const mine = ++serial, source = context;
  message('Reading build steps…');
  list.replaceChildren();
  $('steps-shape-label').hidden = true;
  try {
    const result = await options.load(source.model, source.version);
    if (mine !== serial || source.key !== context.key) return;
    data = result;
    render();
  } catch (e) {
    if (mine === serial) message(e.message || String(e), true);
  }
}

function render() {
  if (!data) return;
  shapes.replaceChildren(...data.chains.map((c) => new Option(c.name, String(c.id))));
  shapes.value = String(chain);
  $('steps-shape-label').hidden = data.chains.length < 2;
  message(!data.chains.length ? 'No recorded operations in this script. The final model remains available.'
    : data.partial ? 'Partial history: these retained shapes omit later solid operations.' : '');
  const current = data.chains.find((c) => c.id === chain);
  $('step-count').textContent = current?.steps.length || '';
  const entries = [{ index: null, label: 'Final model' }, ...(current?.steps || [])];
  list.replaceChildren(...entries.map((step) => {
    const li = document.createElement('li'), button = document.createElement('button');
    button.type = 'button'; button.className = 'ver build-step';
    const active = step.index == null ? !selected : selected?.chain === chain && selected.step === step.index;
    if (active) button.setAttribute('aria-current', 'true');
    const label = document.createElement('span');
    label.textContent = step.index == null ? step.label : (step.index + 1) + '. ' + step.label;
    button.append(label);
    button.addEventListener('click', () => step.index == null ? options.final() : options.pick(chain, step.index));
    li.append(button);
    return li;
  }));
}

shapes.addEventListener('change', () => { chain = Number(shapes.value); render(); });
$('build-steps').addEventListener('click', () => setStepsOpen(panel.hidden));
$('close-steps').addEventListener('click', () => { setStepsOpen(false); $('build-steps').focus(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !panel.hidden) setStepsOpen(false); });
