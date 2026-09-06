import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useApp } from "@/lib/store";
import { generateProtocol } from "@/lib/ai";
import { downloadText, formatTime } from "@/lib/utils";
import { FileText, Download } from "lucide-react";
import { toast } from "sonner";

export function Protocols() {
  const protocols = useApp((s) => s.protocols);
  const collectProtocol = useApp((s) => s.collectProtocol);
  const addProtocol = useApp((s) => s.addProtocol);
  const updateProtocol = useApp((s) => s.updateProtocol);
  const removeProtocol = useApp((s) => s.removeProtocol);
  const tasks = useApp((s) => s.tasks);
  const utterances = useApp((s) => s.utterances);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState(protocols[0]?.id ?? "");

  async function build(ai: boolean) {
    setBusy(true);
    try {
      if (!ai) {
        const p = collectProtocol("Протокол (локальный)");
        if (!p) toast.message("Нет реплик");
        else { setView(p.id); toast.success("Протокол собран без сети"); }
        return;
      }
      const out = await generateProtocol({
        data: {
          tasks: tasks.map((t) => ({ id: t.id, title: t.title })),
          utterances: utterances.slice(0, 80).map((u) => ({ text: u.text, taskId: u.taskId, createdAt: u.createdAt })),
        },
      });
      if (!out.ok) {
        const p = collectProtocol("Протокол (локальный)");
        if (p) setView(p.id);
        toast.message("Сети нет — собран локальный протокол");
        return;
      }
      addProtocol({ title: "Протокол", body: out.text, taskIds: tasks.map((t) => t.id) });
      toast.success("Протокол готов");
    } finally { setBusy(false); }
  }

  const current = protocols.find((p) => p.id === view) ?? protocols[0];
  const lines = current?.body.split("\n") ?? [];
  function dropLine(index: number) {
    if (!current) return;
    updateProtocol(current.id, { body: lines.filter((_, i) => i !== index).join("\n") });
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => void build(false)} disabled={busy || utterances.length === 0}><FileText /> Собрать протокол</Button>
        {current && <Button variant="muted" onClick={() => downloadText(`protocol-${current.createdAt.slice(0, 10)}.md`, current.body, "text/markdown")}><Download /> Markdown</Button>}
        {current && <Button variant="ghost" onClick={() => removeProtocol(current.id)}>Удалить протокол</Button>}
      </div>
      {current ? (
        <article className="rounded-[var(--radius-lg)] border border-border bg-surface p-3 text-sm">
          {lines.map((line, i) => (
            <div key={`${i}-${line.slice(0, 12)}`} className="flex items-start gap-2 py-0.5">
              <p className="min-w-0 flex-1 whitespace-pre-wrap">{line || " "}</p>
              {line.trim() && (line.startsWith("- ") || line.startsWith("## ")) && (
                <button className="text-[11px] text-muted hover:text-rec" onClick={() => dropLine(i)}>убрать</button>
              )}
            </div>
          ))}
        </article>
      ) : <p className="text-sm text-muted">Сначала запишите разговор.</p>}
    </div>
  );
}
