import type { Protocol, Task, Utterance } from "./types";
import { uid } from "./utils";

export function buildLocalProtocol(tasks: Task[], utterances: Utterance[]): Protocol {
  const byTask = new Map<string, string[]>();
  const loose: string[] = [];
  for (const u of [...utterances].reverse()) {
    if (!u.taskId) { loose.push(`- ${u.text}`); continue; }
    const arr = byTask.get(u.taskId) ?? [];
    arr.push(`- ${u.text}`);
    byTask.set(u.taskId, arr);
  }
  const parts = ["# Протокол", "", `Дата: ${new Date().toLocaleString("ru-RU")}`, ""];
  for (const t of tasks) {
    const items = byTask.get(t.id);
    if (!items?.length) continue;
    parts.push(`## ${t.title}`, ...items, "");
  }
  if (loose.length) parts.push("## Неразнесённое", ...loose, "");
  return { id: uid(), title: "Протокол встречи", createdAt: new Date().toISOString(), body: parts.join("\n"), taskIds: tasks.filter((t) => byTask.has(t.id)).map((t) => t.id) };
}
