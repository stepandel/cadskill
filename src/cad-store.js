// Keeps the document on this device between visits, in the browser's IndexedDB.
// Two stores: the step list (small, rewritten on every change) and the text of
// imported STEP files (large, written once each).
//
// openStore() resolves to null where the browser gives the page no storage
// (some private modes and embedded frames); the page then works unsaved.
const DB = 'cad-bench', DOCS = 'docs', BLOBS = 'blobs', CURRENT = 'current';

const done = (req) => new Promise((resolve, reject) => {
  req.onsuccess = () => resolve(req.result);
  req.onerror = () => reject(req.error);
});

export async function openStore() {
  let db;
  try {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => { req.result.createObjectStore(DOCS); req.result.createObjectStore(BLOBS); };
    db = await done(req);
  } catch (e) {
    return null;
  }
  const store = (name, mode) => db.transaction(name, mode).objectStore(name);
  return {
    loadDoc: () => done(store(DOCS, 'readonly').get(CURRENT)),
    saveDoc: (doc) => done(store(DOCS, 'readwrite').put(doc, CURRENT)),
    getBlob: (id) => done(store(BLOBS, 'readonly').get(id)),
    putBlob: (id, text) => done(store(BLOBS, 'readwrite').put(text, id)),
    // Drops imported files no saved step refers to any more.
    async pruneBlobs(keep) {
      const s = store(BLOBS, 'readwrite');
      for (const id of await done(s.getAllKeys())) if (!keep.includes(id)) s.delete(id);
    },
  };
}
