// Talks to the kernel worker. The worker owns the document; this sends it one
// command at a time and hands each answer to the page, so the two never
// disagree about the model.
//
// handlers: boot(loaded, total)  kernel download progress
//           ready(ms)            kernel started; queued commands begin to run
//           progress(m)          { stage: 'reading' } or { stage: 'meshing', parts }
//           result(m)            the document after a command: { kind, doc, errors, parts, canUndo, canRedo, ms }
//           error(m)             { kind, message }: the command was refused and the document is unchanged
//           fatal(message)       the kernel could not start or has stopped
export function startKernel(handlers) {
  const queue = [];
  let worker = null, ready = false, busy = false, seq = 0;

  function pump() {
    if (!ready || busy || queue.length === 0) return;
    busy = true;
    worker.postMessage({ id: ++seq, cmd: queue.shift() });
  }
  function send(cmd) {
    const last = queue[queue.length - 1];
    // A slider drag sends many edits of one step; only the newest waiting one matters.
    if (cmd.type === 'update' && last && last.type === 'update' && last.id === cmd.id && last.merge === cmd.merge) Object.assign(last.params, cmd.params);
    else queue.push(cmd);
    pump();
  }

  try {
    worker = new Worker(new URL('../cad-worker.js', import.meta.url), { type: 'module' });
  } catch (e) {
    handlers.fatal('This browser could not start the geometry kernel: ' + e.message);
    return { send, isReady: () => false };
  }
  worker.onerror = (e) => handlers.fatal('The geometry kernel stopped: ' + (e.message || 'unknown error'));
  worker.onmessage = (ev) => {
    const m = ev.data;
    if (m.type === 'boot') handlers.boot(m.loaded, m.total);
    else if (m.type === 'ready') { ready = true; handlers.ready(m.ms); pump(); }
    else if (m.type === 'fatal') handlers.fatal(m.message);
    else if (m.type === 'progress') handlers.progress(m);
    else if (m.type === 'error') { busy = false; handlers.error(m); pump(); }
    else if (m.type === 'result') { busy = false; handlers.result(m); pump(); }
  };
  return { send, isReady: () => ready };
}
