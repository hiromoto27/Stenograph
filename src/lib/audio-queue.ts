const DB = "stenograph-audio";
const STORE = "chunks";

export type AudioChunk = {
  id: string;
  createdAt: number;
  status: "pending" | "done" | "error";
  mime: string;
  blob: Blob;
  text?: string;
};

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "id" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function enqueueChunk(blob: Blob) {
  if (blob.size < 800) return;
  const db = await openDb();
  const row: AudioChunk = {
    id: crypto.randomUUID(),
    createdAt: Date.now(),
    status: "pending",
    mime: blob.type || "audio/webm",
    blob,
  };
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).put(row);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  db.close();
  return row.id;
}

export async function nextPending(): Promise<AudioChunk | null> {
  const db = await openDb();
  const rows = await new Promise<AudioChunk[]>((resolve, reject) => {
    const tx = db.transaction(STORE, "readonly");
    const req = tx.objectStore(STORE).getAll();
    req.onsuccess = () => resolve((req.result as AudioChunk[]) ?? []);
    req.onerror = () => reject(req.error);
  });
  db.close();
  return rows.filter((r) => r.status === "pending").sort((a, b) => a.createdAt - b.createdAt)[0] ?? null;
}

export async function markChunk(id: string, patch: Partial<AudioChunk>) {
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    const store = tx.objectStore(STORE);
    const get = store.get(id);
    get.onsuccess = () => {
      const cur = get.result as AudioChunk | undefined;
      if (cur) store.put({ ...cur, ...patch });
    };
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  db.close();
}

export async function drainQueue(onText: (text: string) => void) {
  const { transcribeBlob } = await import("./whisper-local");
  for (let i = 0; i < 10; i++) {
    const chunk = await nextPending();
    if (!chunk) break;
    try {
      const text = await transcribeBlob(chunk.blob);
      await markChunk(chunk.id, { status: "done", text });
      if (text) onText(text);
    } catch {
      await markChunk(chunk.id, { status: "error" });
    }
  }
}
