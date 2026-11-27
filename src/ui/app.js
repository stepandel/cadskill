// Both revision and operation selection feed the same model canvas.
import { $ } from './dom.js';
import { view, setParts, select, fit } from './viewer.js';
import { describe, setSourceName } from './readout.js';
import { connect } from './host.js';
import { setupHistory, refreshHistory, markHistory, setHistoryOpen } from './history.js';
import { setupSteps, setStepsSource, setStepsOpen, markStep } from './steps.js';

const msg = $('msg');
function say(text, bad) { msg.textContent = text; msg.classList.toggle('bad', !!bad); msg.hidden = false; }
describe();

const params = new URLSearchParams(window.location.search);
const initialVersion = Number(params.get('version'));
let requestedVersion = Number.isInteger(initialVersion) && initialVersion > 0 ? initialVersion : null;
let openStepsInitially = params.get('view') === 'steps';
const state = { model: null, latest: 0, shown: 0 };
let fullModel = null, first = true, ticket = 0;

function draw(data, refit = false) {
  const selected = view.selected?.id;
  const changed = setParts(data.parts);
  setSourceName(data.model + ' · v' + data.version);
  select(view.parts.find((p) => p.id === selected) || null);
  if (first || changed || refit) fit();
  first = false;
  msg.hidden = true;
}

function finalModel() {
  if (!fullModel) return;
  ++ticket;
  draw(fullModel, true);
  markStep(null, null);
  $('show-model').hidden = true;
}

async function show(version) {
  const mine = ++ticket;
  const model = state.model;
  $('build-steps').disabled = true;
  $('show-model').hidden = true;
  fullModel = null;
  try {
    const data = await (await ready).mesh(model, version);
    if (mine !== ticket) return;
    fullModel = data;
    state.shown = version;
    draw(data);
    $('back').hidden = version === state.latest;
    $('back').textContent = 'Back to v' + state.latest;
    markHistory(state.latest, version);
    setStepsSource(model, version);
    $('build-steps').disabled = false;
    if (openStepsInitially) { openStepsInitially = false; setStepsOpen(true); }
  } catch (e) {
    if (mine === ticket) say('Could not load the model: ' + (e.message || e), true);
  }
}

async function showStep(chain, step) {
  if (!fullModel) return;
  const mine = ++ticket;
  say('Loading build step ' + (step + 1) + '…');
  try {
    const data = await (await ready).stepMesh(state.model, state.shown, chain, step);
    if (mine !== ticket) return;
    draw(data, true);
    markStep(chain, step);
    $('show-model').hidden = false;
  } catch (e) {
    if (mine === ticket) say(e.message || String(e), true);
  }
}

const ready = connect({
  latest(model, version) {
    if (state.model && state.model !== model) requestedVersion = null;
    state.model = model; state.latest = version;
    show(requestedVersion || version);
    refreshHistory();
  },
  status: say,
  theme(name) { document.documentElement.dataset.theme = name; },
});

setupHistory({
  load: async () => state.model ? (await ready).history(state.model) : { versions: [] },
  pick: (version) => { requestedVersion = version; show(version); },
  opened: () => setStepsOpen(false),
});
setupSteps({
  load: async (model, version) => (await ready).steps(model, version),
  pick: showStep,
  final: finalModel,
  opened: () => setHistoryOpen(false),
});
ready.then((api) => {
  $('toggle-history').hidden = !api.history;
  $('build-steps').hidden = !api.steps;
  if (!api.steps) { openStepsInitially = false; setStepsOpen(false); }
});
$('back').addEventListener('click', () => { requestedVersion = null; show(state.latest); });
$('show-model').addEventListener('click', finalModel);
