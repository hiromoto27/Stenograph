import { cosine, tokenize } from "./classifier";
import { cosineVec, embedTextSync } from "./local-nn";
import { pairKey, taskEssence } from "./essence";
import type { MapLink, Task, Utterance } from "./types";

export type GraphNode = {
  id: string;
  kind: "hub" | "task";
  label: string;
  essence: string;
  taskId?: string;
  x: number;
  y: number;
};

export type GraphEdge = {
  from: string;
  to: string;
  weight: number;
  label: string;
  manual: boolean;
};

export type TaskGraph = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};

export function taskSimilarity(a: Task, b: Task, utterances: Utterance[]) {
  const ta = tokenize(`${a.title} ${a.notes} ${Object.keys(a.positive).join(" ")}`);
  const tb = tokenize(`${b.title} ${b.notes} ${Object.keys(b.positive).join(" ")}`);
  const bagA: Record<string, number> = {};
  const bagB: Record<string, number> = {};
  for (const t of ta) bagA[t] = (bagA[t] ?? 0) + 1;
  for (const t of tb) bagB[t] = (bagB[t] ?? 0) + 1;
  const lexical = cosine(bagA, bagB);
  const overlap = ta.filter((t) => bagB[t]);
  const va = embedTextSync(`${a.title} ${a.notes} ${Object.keys(a.positive).slice(0, 12).join(" ")}`);
  const vb = embedTextSync(`${b.title} ${b.notes} ${Object.keys(b.positive).slice(0, 12).join(" ")}`);
  const neural = cosineVec(va, vb);
  const sharedSpeak = utterances.filter(
    (u) =>
      (u.taskId === a.id || u.taskId === b.id) &&
      tokenize(u.text).some((tok) => bagA[tok] && bagB[tok]),
  ).length;
  const link = Math.min(0.25, ((a.links?.[b.id] ?? 0) + (b.links?.[a.id] ?? 0)) * 0.06);
  const score = Math.min(1, lexical * 0.4 + neural * 0.35 + Math.min(0.2, sharedSpeak * 0.05) + link);
  return { score, overlap, neural, lexical };
}

export function buildGraph(
  tasks: Task[],
  utterances: Utterance[],
  mapLinks: MapLink[] = [],
  hiddenPairs: string[] = [],
): TaskGraph {
  const W = 920;
  const H = 560;
  const cx = W / 2;
  const cy = H / 2;
  const nodes: GraphNode[] = [
    { id: "hub", kind: "hub", label: "Стенограф", essence: "", x: cx, y: cy },
  ];
  const edges: GraphEdge[] = [];
  const hidden = new Set(hiddenPairs);

  const n = Math.max(tasks.length, 1);
  tasks.forEach((task, i) => {
    const ang = (Math.PI * 2 * i) / n - Math.PI / 2;
    const r = Math.min(200, 140 + n * 8);
    const essence = taskEssence(task, utterances).slice(0, 2).join(" \u00b7 ");
    nodes.push({
      id: task.id,
      kind: "task",
      label: task.title,
      essence,
      taskId: task.id,
      x: cx + Math.cos(ang) * r,
      y: cy + Math.sin(ang) * r,
    });
    edges.push({ from: "hub", to: task.id, weight: 0.25, label: "", manual: false });
  });

  const seen = new Set<string>();
  for (const link of mapLinks) {
    const key = pairKey(link.a, link.b);
    if (hidden.has(key)) continue;
    seen.add(key);
    edges.push({
      from: link.a,
      to: link.b,
      weight: 0.9,
      label: link.label || "связь",
      manual: true,
    });
  }

  for (let i = 0; i < tasks.length; i++) {
    for (let j = i + 1; j < tasks.length; j++) {
      const a = tasks[i];
      const b = tasks[j];
      const key = pairKey(a.id, b.id);
      if (hidden.has(key) || seen.has(key)) continue;
      const sim = taskSimilarity(a, b, utterances);
      if (sim.score < 0.28) continue;
      const label = sim.overlap.slice(0, 3).join(" \u00b7 ");
      if (!label) continue;
      edges.push({
        from: a.id,
        to: b.id,
        weight: sim.score,
        label,
        manual: false,
      });
    }
  }

  return { nodes, edges };
}
