// Page entry point: shows whichever model version the server last built.
// The page has no modelling controls; Claude changes the model through the
// server's tools and this view follows.
import { $ } from './dom.js';
import { view, setParts, select, setEdges, fit } from './viewer.js';
import { describe, setSourceName } from './readout.js';
import { connect } from './host.js';

const msg = $('msg');
function say(text, bad) { msg.textContent = text; msg.classList.toggle('bad', !!bad); msg.hidden = false; }
describe();

let first = true;
connect({
  model({ model, version, parts }) {
    const selId = view.selected && view.selected.id;
    const changed = setParts(parts);
    setSourceName(model + ' · v' + version);
    select(view.parts.find((p) => p.id === selId) || null);   // also redraws the readout and dock label
    msg.hidden = true;                                         // once a model is up, the readout carries the numbers
    if (first || changed) fit();
    first = false;
  },
  status: say,
  theme(name) { document.documentElement.dataset.theme = name; },
});

$('fit').addEventListener('click', fit);
$('edges').addEventListener('click', () => {
  const on = $('edges').getAttribute('aria-pressed') !== 'true';
  $('edges').setAttribute('aria-pressed', String(on));
  setEdges(on);
});
