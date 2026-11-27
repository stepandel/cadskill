// Page entry point: follows whichever model version the server last built,
// and shows older versions picked from the history panel.
// The page has no modelling controls; Claude changes the model through the
// server's tools and this view follows.
import { $ } from './dom.js';
import { view, setParts, select, fit } from './viewer.js';
import { describe, setSourceName } from './readout.js';
import { connect } from './host.js';
import { setupHistory, refreshHistory, markHistory } from './history.js';

const msg = $('msg');
function say(text, bad) { msg.textContent = text; msg.classList.toggle('bad', !!bad); msg.hidden = false; }
describe();

const params = new URLSearchParams(window.location.search);
const selectedVersion = Number(params.get('version'));
let requestedVersion = Number.isInteger(selectedVersion) && selectedVersion > 0 ? selectedVersion : null;
const state = { model: null, latest: 0, shown: 0, mode: params.get('view') === 'steps' ? 'steps' : 'model' };
let first = true;
let ticket = 0;           // only the most recently asked-for version gets drawn
let stepsTicket = 0;
let stepsKey = '';

function mode(name) {
  state.mode = name;
  $('main').dataset.mode = name;
  $('steps-panel').hidden = name !== 'steps';
  $('show-model').setAttribute('aria-pressed', String(name === 'model'));
  $('build-steps').setAttribute('aria-pressed', String(name === 'steps'));
  msg.hidden = true;
}

function stepsMessage(text, bad = false) {
  const message = $('steps-message');
  message.textContent = text;
  message.classList.toggle('bad', bad);
  message.hidden = false;
  $('steps-frame').hidden = true;
}

async function showSteps() {
  if (!state.model || !state.shown) return;
  const api = await ready;
  // MCP hosts open the same CadSkill shell in their browser surface. Local
  // browser views embed Replay; the host's MCP sandbox need not frame localhost.
  if (!api.steps) {
    try { await api.openSteps(state.model, state.shown); }
    catch (e) { say(e.message || String(e), true); }
    return;
  }
  mode('steps');
  $('steps-source').textContent = state.model + ' · v' + state.shown;
  const theme = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const key = state.model + '@' + state.shown + ':' + theme;
  if (key === stepsKey) {
    $('steps-message').hidden = true;
    $('steps-frame').hidden = false;
    return;
  }
  const mine = ++stepsTicket;
  stepsMessage('Preparing build steps…');
  try {
    const data = await api.steps(state.model, state.shown);
    if (mine !== stepsTicket || state.mode !== 'steps') return;
    const url = new URL(data.url);
    url.searchParams.set('embedded', '1');
    url.searchParams.set('theme', theme);
    $('steps-frame').title = 'Build steps — ' + data.model + ' · v' + data.version;
    $('steps-frame').src = url.href;
    stepsKey = key;
    $('steps-message').hidden = true;
    $('steps-frame').hidden = false;
  } catch (e) {
    if (mine === stepsTicket && state.mode === 'steps') stepsMessage(e.message || String(e), true);
  }
}

function display({ model, version, parts }) {
  const selId = view.selected && view.selected.id;
  const changed = setParts(parts);
  state.shown = version;
  setSourceName(model + ' · v' + version);
  select(view.parts.find((p) => p.id === selId) || null);   // also redraws the readout and dock label
  msg.hidden = true;                                         // once a model is up, the readout carries the numbers
  if (first || changed) fit();
  first = false;
  const older = version !== state.latest;
  $('back').hidden = !older;
  $('back').textContent = 'Back to v' + state.latest;
  markHistory(state.latest, version);
  $('build-steps').disabled = false;
  if (state.mode === 'steps') showSteps();
}

async function show(version) {
  const mine = ++ticket;
  $('build-steps').disabled = true;
  ++stepsTicket;
  if (state.mode === 'steps') stepsMessage('Loading revision ' + version + '…');
  try {
    const data = await (await ready).mesh(state.model, version);
    if (mine === ticket) display(data);
  } catch (e) {
    if (mine === ticket) say('Could not load the model: ' + (e && e.message ? e.message : e), true);
    if (mine === ticket && state.mode === 'steps') stepsMessage('Could not load revision ' + version + '.', true);
  }
}

const ready = connect({
  latest(model, version) {      // keep an explicitly selected revision in view
    if (state.model && state.model !== model) requestedVersion = null;
    state.model = model; state.latest = version;
    show(requestedVersion || version);
    refreshHistory();
  },
  status: say,
  theme(name) { document.documentElement.dataset.theme = name; },
});

setupHistory({
  load: async () => (state.model ? (await ready).history(state.model) : { versions: [] }),
  pick: (version) => { requestedVersion = version; if (state.model) show(version); },
});
ready.then((api) => {
  if (!api.history) $('toggle-history').hidden = true;
  $('build-steps').hidden = !api.steps && !api.openSteps;
  $('show-model').hidden = !api.steps;
  if (!api.steps && !api.openSteps) mode('model');
});
$('back').addEventListener('click', () => { requestedVersion = null; show(state.latest); });
$('show-model').addEventListener('click', () => {
  ++stepsTicket;
  mode('model');
});
$('build-steps').addEventListener('click', showSteps);
