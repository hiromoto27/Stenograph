import { useMemo, useState } from "react";
import { useApp } from "@/lib/store";
import { buildGraph } from "@/lib/graph";
import { taskEssence } from "@/lib/essence";
import { loadLocalNet, nnStatus } from "@/lib/local-nn";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Network } from "lucide-react";

export function MindMap() {
  const tasks = useApp((s) => s.tasks);
  const utterances = useApp((s) => s.utterances);
  const mapLinks = useApp((s) => s.mapLinks);
  const hiddenPairs = useApp((s) => s.hiddenPairs);
  const linkTasks = useApp((s) => s.linkTasks);
  const hidePair = useApp((s) => s.hidePair);
  const [selected, setSelected] = useState<string | null>(null);
  const [other, setOther] = useState("");
  const [label, setLabel] = useState("");
  const [nn, setNn] = useState(nnStatus());
  const graph = useMemo(
    () => buildGraph(tasks, utterances, mapLinks, hiddenPairs),
    [tasks, utterances, mapLinks, hiddenPairs],
  );
  const selectedTask = tasks.find((t) => t.id === selected);
  const essence = selectedTask ? taskEssence(selectedTask, utterances) : [];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-display text-2xl tracking-[-0.03em]">Карта связей</h2>
          <p className="text-sm text-muted">На карте только суть: ключевые фразы. Рёбра можно добавить или убрать.</p>
        </div>
      </div>
      <div className="overflow-x-auto rounded-[var(--radius-xl)] border border-border bg-surface">
        <svg viewBox="0 0 920 560" className="h-auto min-h-[320px] w-full" role="img">
          {graph.edges.map((e) => {
            const a = graph.nodes.find((n) => n.id === e.from);
            const b = graph.nodes.find((n) => n.id === e.to);
            if (!a || !b) return null;
            return (
              <g key={`${e.from}-${e.to}-${e.label}`} className={e.from === "hub" ? undefined : "cursor-pointer"} onClick={() => { if (e.from !== "hub") hidePair(e.from, e.to); }}>
                <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={e.manual ? "var(--color-ok)" : "var(--color-border)"} strokeWidth={e.manual ? 2.8 : 1.4} />
                {e.label ? <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 6} textAnchor="middle" fill="var(--color-muted)" fontSize="11">{e.label}</text> : null}
              </g>
            );
          })}
          {graph.nodes.map((n) => (
            <g key={n.id} className="cursor-pointer" onClick={() => setSelected(n.taskId ?? n.id)}>
              <circle cx={n.x} cy={n.y} r={n.kind === "hub" ? 28 : 22} fill={selected === n.taskId ? "var(--color-ok)" : "var(--color-surface-2)"} stroke="var(--color-border)" />
              <text x={n.x} y={n.y + 36} textAnchor="middle" fill="var(--color-fg)" fontSize="12">{n.label}</text>
              {n.essence ? <text x={n.x} y={n.y + 50} textAnchor="middle" fill="var(--color-muted)" fontSize="10">{n.essence}</text> : null}
            </g>
          ))}
        </svg>
      </div>
      {selectedTask && (
        <article className="rounded-[var(--radius-lg)] border border-border bg-surface p-4">
          <h3 className="font-medium">{selectedTask.title}</h3>
          <ul className="mt-3 space-y-1 text-sm">{essence.map((p) => <li key={p}>· {p}</li>)}</ul>
          <div className="mt-4 grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
            <select className="h-10 rounded-[var(--radius-md)] border border-border bg-bg px-3 text-sm" value={other} onChange={(e) => setOther(e.target.value)}>
              <option value="">Связать с задачей…</option>
              {tasks.filter((t) => t.id !== selectedTask.id).map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
            </select>
            <Input placeholder="подпись связи" value={label} onChange={(e) => setLabel(e.target.value)} />
            <Button disabled={!other} onClick={() => { linkTasks(selectedTask.id, other, label); setLabel(""); }}>Связать</Button>
          </div>
        </article>
      )}
    </div>
  );
}
