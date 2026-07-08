import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";

export function QaPage() {
  const [question, setQuestion] = useState("");
  const [language, setLanguage] = useState<"ru" | "en">("ru");

  const ask = useMutation({
    mutationFn: () => api.ragAsk({ question, language, timeout_s: 60 }),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">QA test</h1>
        <p className="text-sm text-muted-foreground">
          Send a canned <code>asr.final</code> onto the bus and watch for the
          resulting <code>llm.answer</code> or <code>llm.rejected</code>.
        </p>
      </div>

      <div className="space-y-3 rounded-lg border border-border bg-background/40 p-4">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Задайте вопрос роботу…"
          rows={4}
          className="w-full rounded-md border border-border bg-background/60 px-3 py-2 text-sm outline-none focus:border-primary"
        />
        <div className="flex items-center gap-3">
          <label className="text-xs uppercase text-muted-foreground">Language</label>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value as "ru" | "en")}
            className="rounded-md border border-border bg-background/60 px-2 py-1 text-sm"
          >
            <option value="ru">ru</option>
            <option value="en">en</option>
          </select>
          <button
            type="button"
            onClick={() => ask.mutate()}
            disabled={question.trim().length === 0 || ask.isPending}
            className="ml-auto rounded-md bg-primary px-3 py-1 text-sm text-primary-foreground disabled:opacity-50"
          >
            {ask.isPending ? "Waiting…" : "Ask"}
          </button>
        </div>
      </div>

      {ask.error && (
        <p className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {String(ask.error)}
        </p>
      )}

      {ask.data && (
        <div className="rounded-lg border border-border bg-background/40 p-4">
          <div className="flex items-baseline justify-between">
            <div className="text-xs uppercase text-muted-foreground">Outcome</div>
            <span
              className={
                ask.data.outcome === "answer"
                  ? "rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-400"
                  : "rounded-full bg-yellow-500/10 px-2 py-0.5 text-xs text-yellow-400"
              }
            >
              {ask.data.outcome}
            </span>
          </div>
          {ask.data.text && <p className="mt-3 text-sm">{ask.data.text}</p>}
          {ask.data.fallback_text && (
            <p className="mt-3 text-sm text-muted-foreground italic">
              {ask.data.fallback_text}
            </p>
          )}
          {ask.data.reason && (
            <p className="mt-2 text-xs text-muted-foreground">reason: {ask.data.reason}</p>
          )}
          {ask.data.citations.length > 0 && (
            <div className="mt-4">
              <div className="mb-1 text-xs uppercase text-muted-foreground">Citations</div>
              <ul className="space-y-1 text-xs">
                {ask.data.citations.map((c, i) => (
                  <li key={i} className="rounded bg-background/60 px-2 py-1">
                    <span className="font-mono text-[10px] text-muted-foreground">
                      {c.chunk_id}
                    </span>
                    <div className="mt-0.5">{c.quote}</div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
