import { tokenize } from "./classifier";
import type { Task, Utterance } from "./types";

const FILLER = new Set([
  "просто", "вообще", "типа", "как-бы", "какбы", "короче", "слушай",
  "смотри", "знаешь", "понял", "понятно", "ладно", "давай", "сейчас",
  "сегодня", "потом", "здесь", "там", "этот", "эта", "эти", "очень",
  "немного", "чуть", "вроде", "наверное", "может", "будет", "было",
]);

export function extractKeyPhrases(text: string, limit = 4): string[] {
  const raw = text
    .toLowerCase()
    .replaceAll("ё", "е")
    .split(/[,.;!?]| — | – /)
    .map((s) => s.trim())
    .filter((s) => s.length > 8);
  const scored = raw
    .map((clause) => {
      const tokens = tokenize(clause).filter((t) => !FILLER.has(t));
      return { clause: tokens.join(" "), score: tokens.length };
    })
    .filter((x) => x.score >= 2)
    .sort((a, b) => b.score - a.score);
  const out: string[] = [];
  for (const s of scored) {
    const short = s.clause.length > 42 ? `${s.clause.slice(0, 40)}…` : s.clause;
    if (!out.includes(short)) out.push(short);
    if (out.length >= limit) break;
  }
  if (out.length === 0) {
    const tokens = tokenize(text).filter((t) => !FILLER.has(t)).slice(0, 6);
    if (tokens.length) out.push(tokens.join(" "));
  }
  return out;
}

export function taskEssence(task: Task, utterances: Utterance[]): string[] {
  const fromNotes = extractKeyPhrases(`${task.title}. ${task.notes}`, 2);
  const fromSpeech = utterances
    .filter((u) => u.taskId === task.id)
    .flatMap((u) => extractKeyPhrases(u.text, 2));
  const fromWords = Object.entries(task.positive)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([w]) => w);
  const merged: string[] = [];
  for (const p of [...fromNotes, ...fromSpeech]) {
    if (!merged.some((m) => m.includes(p) || p.includes(m))) merged.push(p);
    if (merged.length >= 5) break;
  }
  if (merged.length === 0 && fromWords.length) merged.push(fromWords.join(" · "));
  return merged;
}

export function pairKey(a: string, b: string) {
  return a < b ? `${a}|${b}` : `${b}|${a}`;
}
