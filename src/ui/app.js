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

const state = { model: null, latest: 0, shown: 0 };
let first = true;
let ticket = 0;           // only the most recently asked-for version gets drawn

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
}

async function show(version) {
  const mine = ++ticket;
  try {
    const data = await (await ready).mesh(state.model, version);
    if (mine === ticket) display(data);
  } catch (e) {
    if (mine === ticket) say('Could not load the model: ' + (e && e.message ? e.message : e), true);
  }
}

const ready = connect({
  latest(model, version) {      // a new build always comes into view
    state.model = model; state.latest = version;
    show(version);
    refreshHistory();
  },
  status: say,
  theme(name) { document.documentElement.dataset.theme = name; },
});

setupHistory({
  load: async () => (state.model ? (await ready).history(state.model) : { versions: [] }),
  pick: (version) => { if (state.model) show(version); },
});
$('back').addEventListener('click', () => show(state.latest));
