import { parseReminder } from "./remind-parse";

export type SpeechIntent = {
  createTask: boolean;
  title: string;
  remindAt: Date | null;
};

const STRONG_CREATE =
  /(?:сделай|создай|поставь|заведи|добавь|запиши|открой)\s+(?:пожалуйста\s+)?(?:новую\s+)?задач[уие]/i;

const SOFT_CREATE =
  /(?:^|[.!?]\s+)(?:необходимо|нужно|надо)\s+(?:бы\s+)?/i;

function cleanTitle(raw: string) {
  let t = raw.replace(/\s+/g, " ").trim();
  t = t.replace(STRONG_CREATE, " ");
  t = t.replace(/^(?:пожалуйста[, ]+)?/i, "");
  t = t.replace(/^(?:необходимо|нужно|надо)(?:\s+бы)?\s+/i, "");
  t = t.replace(/^напомн\w*(?:\s+мне)?\s+/i, "");
  t = t.replace(/^(?:про|о|об)\s+/i, "");
  t = t.replace(/\s+/g, " ").trim();
  if (t.length < 3) return raw.slice(0, 80);
  return t.charAt(0).toUpperCase() + t.slice(1);
}

export function parseSpeechIntent(text: string, now = new Date()): SpeechIntent {
  return {
    createTask: STRONG_CREATE.test(text) || SOFT_CREATE.test(text),
    title: cleanTitle(text),
    remindAt: parseReminder(text, now),
  };
}
