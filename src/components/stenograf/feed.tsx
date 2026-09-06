import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useApp } from "@/lib/store";
import { formatTime } from "@/lib/utils";

export function Feed() {
  const utterances = useApp((s) => s.utterances);
  const tasks = useApp((s) => s.tasks);
  const removeUtterance = useApp((s) => s.removeUtterance);
  const update = (id: string, taskId: string | null) => {
    useApp.setState((s) => ({
      utterances: s.utterances.map((u) =>
        u.id === id ? { ...u, taskId, confirmed: true } : u,
      ),
    }));
  };

  if (utterances.length === 0) {
    return (
      <div className="rounded-[var(--radius-lg)] border border-dashed border-border px-4 py-10 text-center text-sm text-muted">
        Реплик пока нет. Нажмите «Записать» или «Демо-диалог».
      </div>
    );
  }

  return (
    <ol className="space-y-2">
      {utterances.map((u) => {
        const task = tasks.find((t) => t.id === u.taskId);
        return (
          <li key={u.id} className="rounded-[var(--radius-lg)] border border-border bg-surface p-3">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
              <span className="font-mono tabular-nums">{formatTime(u.createdAt)}</span>
              <div className="flex items-center gap-2">
                <Badge tone={u.confirmed ? "ok" : "warn"}>
                  {task ? task.title : "без задачи"} · {Math.round(u.confidence * 100)}%
                </Badge>
                <Button size="sm" variant="ghost" onClick={() => removeUtterance(u.id)}>
                  Удалить
                </Button>
              </div>
            </div>
            <p className="mt-2 text-sm leading-relaxed">{u.text}</p>
            <select
              className="mt-2 h-9 w-full rounded-[var(--radius-sm)] border border-border bg-surface-2 px-2 text-xs"
              value={u.taskId ?? ""}
              onChange={(e) => update(u.id, e.target.value || null)}
            >
              <option value="">Без задачи</option>
              {tasks.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.title}
                </option>
              ))}
            </select>
          </li>
        );
      })}
    </ol>
  );
}
