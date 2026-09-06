export type WhisperStatus = "idle" | "loading" | "ready" | "error" | "running";

export const WHISPER_MODEL = {
  id: "tiny",
  hf: "Xenova/whisper-tiny",
  label: "Whisper tiny",
  size: "~75 МБ",
  about: "Локальное распознавание русской речи. После скачивания работает без сети.",
} as const;

type Asr = (
  input: string | Float32Array,
  opts?: Record<string, unknown>,
) => Promise<{ text?: string } | { text?: string }[]>;

let asr: Asr | null = null;
let status: WhisperStatus = "idle";
let progress = 0;
let lastError = "";
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

export function subscribeWhisper(fn: () => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function whisperStatus() {
  return { status, progress, error: lastError, model: asr ? WHISPER_MODEL.hf : "" };
}

export async function loadWhisper() {
  if (asr && status === "ready") return asr;
  status = "loading";
  progress = 0;
  lastError = "";
  emit();
  try {
    const { pipeline } = await import("@huggingface/transformers");
    asr = (await pipeline("automatic-speech-recognition", WHISPER_MODEL.hf, {
      dtype: "q8",
    })) as unknown as Asr;
    status = "ready";
    progress = 100;
    emit();
    return asr;
  } catch (e) {
    status = "error";
    lastError = e instanceof Error ? e.message : "не скачалось";
    emit();
    throw e;
  }
}

export async function transcribeBlob(blob: Blob, language = "russian") {
  const model = await loadWhisper();
  status = "running";
  emit();
  const url = URL.createObjectURL(blob);
  try {
    const out = await model(url, { language, task: "transcribe" });
    const row = Array.isArray(out) ? out[0] : out;
    return (row?.text ?? "").trim();
  } finally {
    URL.revokeObjectURL(url);
    status = "ready";
    emit();
  }
}
