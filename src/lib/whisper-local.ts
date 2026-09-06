export type WhisperStatus = "idle" | "loading" | "ready" | "error" | "running";

export const WHISPER_MODEL = {
  id: "tiny",
  hf: "Xenova/whisper-tiny",
  label: "Whisper tiny",
  size: "~75 МБ",
  about: "q8 + Cache API, повторно не качается.",
} as const;

const FLAG = "stenograph-whisper-tiny";

let asr: unknown = null;
let status: WhisperStatus = "idle";
let progress = 0;
let lastError = "";
let fromCache = false;
let cacheBytes = 0;
let loadPromise: Promise<unknown> | null = null;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export function subscribeWhisper(fn: () => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function whisperStatus() {
  return {
    status,
    progress,
    error: lastError,
    model: WHISPER_MODEL.hf,
    fromCache,
    cacheBytes,
    flagged: typeof localStorage !== "undefined" && localStorage.getItem(FLAG) === "1",
  };
}

export function formatBytes(n: number) {
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} КБ`;
  return `${(n / (1024 * 1024)).toFixed(1)} МБ`;
}

function hit(url: string) {
  return /whisper|xenova|onnx|huggingface|transformers/i.test(url);
}

export async function measureWhisperCache() {
  cacheBytes = 0;
  if (typeof caches === "undefined") return 0;
  for (const name of await caches.keys()) {
    const cache = await caches.open(name);
    for (const req of await cache.keys()) {
      if (!hit(req.url) && !hit(name)) continue;
      cacheBytes += (await (await cache.match(req))?.blob())?.size ?? 0;
    }
  }
  emit();
  return cacheBytes;
}

export async function clearWhisperCache() {
  asr = null;
  status = "idle";
  fromCache = false;
  loadPromise = null;
  try { localStorage.removeItem(FLAG); } catch { /* private */ }
  if (typeof caches !== "undefined") {
    for (const name of await caches.keys()) {
      const cache = await caches.open(name);
      for (const req of await cache.keys()) {
        if (hit(req.url) || hit(name)) await cache.delete(req);
      }
    }
  }
  cacheBytes = 0;
  emit();
}

export async function loadWhisper() {
  if (asr && (status === "ready" || status === "running")) return asr;
  if (loadPromise) return loadPromise;
  status = "loading";
  fromCache = Boolean(localStorage.getItem(FLAG));
  emit();
  loadPromise = (async () => {
    const { pipeline, env } = await import("@huggingface/transformers");
    env.useBrowserCache = true;
    if (env.backends.onnx.wasm) {
      const cores = navigator.hardwareConcurrency || 2;
      env.backends.onnx.wasm.numThreads = Math.min(4, Math.max(1, cores - 2));
    }
    asr = await pipeline("automatic-speech-recognition", WHISPER_MODEL.hf, { dtype: "q8" });
    status = "ready";
    progress = 100;
    fromCache = true;
    localStorage.setItem(FLAG, "1");
    await measureWhisperCache();
    return asr;
  })();
  try { return await loadPromise; }
  catch (e) {
    status = "error";
    lastError = e instanceof Error ? e.message : "fail";
    emit();
    throw e;
  } finally { loadPromise = null; }
}
