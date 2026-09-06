const STOP = new Set(["и","в","на","с","к","по","о","от","для","это","как","что","не","да","нет","я","мы","вы","он","она","уже","или","а","но","ну","если","можно","нужно","надо"]);
function stem(word: string) {
  if (word.length < 5) return word;
  return word.replace(/(ami|ами|ями|ого|ему|ов|ев|ей|ах|ях|ам|ям|ом|ем|ой|ый|ий|ая|ое|ые|ие|ть|ла|ли|ло)$/i, "");
}
export function tokenize(text: string): string[] {
  return text.toLowerCase().replaceAll("ё", "е").replace(/[^a-zа-я0-9\s-]/gi, " ").split(/\s+/).map((w) => stem(w.trim())).filter((w) => w.length > 2 && !STOP.has(w));
}
export function bag(tokens: string[]) {
  const m: Record<string, number> = {};
  for (const t of tokens) m[t] = (m[t] ?? 0) + 1;
  return m;
}
function vecDot(a: Record<string, number>, b: Record<string, number>) {
  let s = 0; for (const [k, v] of Object.entries(a)) if (b[k]) s += v * b[k]; return s;
}
function vecNorm(a: Record<string, number>) {
  let s = 0; for (const v of Object.values(a)) s += v * v; return Math.sqrt(s) || 1;
}
export function cosine(a: Record<string, number>, b: Record<string, number>) {
  return vecDot(a, b) / (vecNorm(a) * vecNorm(b));
}
export type Rank = { taskId: string; score: number; overlap: string[] };
export function rankTasks(text: string, tasks: { id: string; title: string; notes?: string; positive: Record<string, number>; negative: Record<string, number>; links?: Record<string, number> }[]): Rank[] {
  const tokens = tokenize(text);
  const query = bag(tokens);
  return tasks.map((task) => {
    const titleVec = bag(tokenize(`${task.title} ${task.notes ?? ""}`));
    const pos = cosine(query, { ...task.positive, ...titleVec });
    const neg = cosine(query, task.negative);
    const overlap = tokens.filter((t) => task.positive[t] || titleVec[t]);
    return { taskId: task.id, score: Math.max(0, Math.min(1, pos - neg * 0.45 + Math.min(0.22, overlap.length * 0.05))), overlap };
  }).sort((a, b) => b.score - a.score);
}
export function linkedAmbiguous(ranks: Rank[], tasks: { id: string; links?: Record<string, number> }[]) {
  const a = ranks[0], b = ranks[1];
  if (!a || !b || a.overlap.length === 0 || b.overlap.length === 0) return false;
  if (a.score - b.score > 0.16) return false;
  const ta = tasks.find((t) => t.id === a.taskId);
  const tb = tasks.find((t) => t.id === b.taskId);
  return Boolean(ta?.links?.[b.taskId] || tb?.links?.[a.taskId]) || a.overlap.some((w) => b.overlap.includes(w));
}
export function applyFeedback(profile: { positive: Record<string, number>; negative: Record<string, number> }, text: string, belongs: boolean) {
  const tokens = tokenize(text);
  const target = belongs ? profile.positive : profile.negative;
  for (const t of tokens) target[t] = (target[t] ?? 0) + (belongs ? 1.25 : 1);
  return profile;
}
export function strengthenLink(links: Record<string, number>, otherId: string) {
  return { ...links, [otherId]: (links[otherId] ?? 0) + 1 };
}
export function levelOf(hits: number, misses: number) {
  const n = hits + misses;
  if (n < 3) return { pct: 0, label: "Новичок", n };
  const pct = Math.round((hits / n) * 100);
  return { pct, label: pct >= 85 ? "Эксперт" : pct >= 70 ? "Уверенный" : "Учится", n };
}
