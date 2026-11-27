// Build steps use the same floating-panel pattern as Revisions. The geometry
// is drawn by app.js in the existing model canvas.
import { $ } from './dom.js';

let options = {}, context = null, data = null, chain = null, selected = null, serial = 0;
const panel = $('steps-panel'), list = $('steps-list'), shapes = $('steps-shape');

export function setupSteps(opts) { options = opts; }

export function setStepsOpen(open) {
  panel.hidden = !open;
  $('build-steps').setAttribute('aria-pressed', String(open));
  if (open) { options.opened?.(); refresh(); }
}

export function setStepsSource(model, version, parts) {
  const key = model + '@' + version;
  if (context?.key !== key) { data = null; chain = null; ++serial; $('step-count').textContent = ''; }
  context = { model, version, key, parts };
  selected = null;
  $('steps-source').textContent = model + ' · v' + version;
  if (!panel.hidden) refresh();
  else render();
}

export function markStep(shape, step) {
  chain = shape;
  selected = step == null ? null : { chain: shape, step };
  render();
}

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
  const overview = context.parts.length > 1 ? 'Assembly' : 'Final model';
  shapes.replaceChildren(new Option(overview, ''), ...data.chains.map((c) => new Option(c.name, String(c.id))));
  shapes.value = chain == null ? '' : String(chain);
  $('steps-shape-label').hidden = !data.chains.length;
  message(!data.chains.length ? 'No recorded operations in this script. The final model remains available.'
    : data.partial ? 'Partial history: these retained shapes omit later solid operations.' : '');
  const current = data.chains.find((c) => c.id === chain);
  $('step-count').textContent = current?.steps.length || '';
  const entries = [{ label: overview, active: chain == null, pick: () => options.final() }];
  if (current) {
    entries.push(...current.steps.map((step) => ({
      label: (step.index + 1) + '. ' + step.label,
      active: selected?.chain === chain && selected.step === step.index,
      pick: () => options.pick(current.id, step.index),
    })));
  } else {
    for (const part of context.parts) {
      const history = data.chains.find((c) => c.part_id === part.id);
      entries.push({ label: part.name, detail: history ? history.steps.length + ' steps' : 'No recorded steps',
        pick: history ? () => choose(history.id) : null });
    }
    // Partial histories may contain retained construction shapes that aren't
    // final assembly parts. Keep those chains accessible without guessing a match.
    entries.push(...data.chains.filter((c) => !c.part_id).map((c) => ({
      label: c.name, detail: c.steps.length + ' steps · retained shape', pick: () => choose(c.id),
    })));
  }
  list.replaceChildren(...entries.map((entry) => {
    const li = document.createElement('li'), button = document.createElement('button');
    button.type = 'button'; button.className = 'ver build-step';
    if (entry.active) button.setAttribute('aria-current', 'true');
    const label = document.createElement('span');
    label.textContent = entry.label;
    button.append(label);
    if (entry.detail) {
      const detail = document.createElement('span');
      detail.className = 'step-detail'; detail.textContent = entry.detail; button.append(detail);
    }
    button.disabled = !entry.pick;
    if (entry.pick) button.addEventListener('click', entry.pick);
    li.append(button);
    return li;
  }));
}

function choose(id) {
  const current = data.chains.find((c) => c.id === id);
  chain = id; selected = null; render();
  options.pick(id, current.steps.at(-1).index);
  list.scrollTop = 0;
}
shapes.addEventListener('change', () => shapes.value === '' ? options.final() : choose(Number(shapes.value)));
$('build-steps').addEventListener('click', () => setStepsOpen(panel.hidden));
$('close-steps').addEventListener('click', () => { setStepsOpen(false); $('build-steps').focus(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !panel.hidden) setStepsOpen(false); });
