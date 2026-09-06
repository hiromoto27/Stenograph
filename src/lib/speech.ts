export type SpeechHandlers = {
  onFinal: (text: string) => void;
  onPartial?: (text: string) => void;
  onError?: (msg: string) => void;
};

type RecCtor = new () => SpeechRecognitionLike;

interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((ev: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onerror: ((ev: { error: string }) => void) | null;
  onend: (() => void) | null;
  _alive?: boolean;
}

export function getSpeechCtor(): RecCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as Window & {
    SpeechRecognition?: RecCtor;
    webkitSpeechRecognition?: RecCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function createRecognizer(lang: string, continuous: boolean, h: SpeechHandlers) {
  const Ctor = getSpeechCtor();
  if (!Ctor) return null;
  const rec = new Ctor();
  rec.lang = lang;
  rec.continuous = continuous;
  rec.interimResults = true;
  rec._alive = true;
  rec.onresult = (ev) => {
    let partial = "";
    for (let i = ev.resultIndex; i < ev.results.length; i++) {
      const r = ev.results[i];
      const t = r[0]?.transcript ?? "";
      if (r.isFinal) h.onFinal(t);
      else partial += t;
    }
    if (partial) h.onPartial?.(partial);
  };
  rec.onerror = (ev) => {
    if (ev.error === "no-speech" || ev.error === "aborted") return;
    h.onError?.(ev.error);
  };
  rec.onend = () => {
    if (!continuous || !rec._alive) return;
    try { rec.start(); } catch { /* already started */ }
  };
  return rec;
}

export function stopRecognizer(rec: SpeechRecognitionLike | null) {
  if (!rec) return;
  rec._alive = false;
  try { rec.stop(); } catch { rec.abort(); }
}
