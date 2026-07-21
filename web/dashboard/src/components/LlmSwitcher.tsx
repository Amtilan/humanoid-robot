import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BrainCircuit, Cloud, Cpu, Loader2 } from "lucide-react";

import { api, type LlmBackendConfig } from "../api/client";
import { cn } from "../lib/cn";
import { useToast } from "../lib/toast";

const DEFAULT_CLOUD: Omit<LlmBackendConfig, "mode"> = {
  base_url: "https://api.openai.com",
  model: "gpt-4o-mini",
  api_key: "",
};

/**
 * «Модель ИИ» — switch the robot's brain between the local model and a cloud
 * OpenAI-compatible provider. The token is entered HERE and stored on the
 * robot; it never lives in an image or in git. rag reconfigures live.
 */
export function LlmSwitcher() {
  const { push } = useToast();
  const client = useQueryClient();
  const current = useQuery({ queryKey: ["llm", "config"], queryFn: api.llmConfigGet });

  const [mode, setMode] = useState<"local" | "cloud">("local");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(DEFAULT_CLOUD.model);
  const [baseUrl, setBaseUrl] = useState(DEFAULT_CLOUD.base_url);

  useEffect(() => {
    const cfg = current.data;
    if (!cfg) return;
    setMode(cfg.mode);
    setModel(cfg.model || DEFAULT_CLOUD.model);
    setBaseUrl(cfg.base_url || DEFAULT_CLOUD.base_url);
    // Never echo the stored key back into the input; show placeholder instead.
  }, [current.data]);

  const save = useMutation({
    mutationFn: () =>
      api.llmConfigSet({
        mode,
        base_url: baseUrl.trim() || DEFAULT_CLOUD.base_url,
        model: model.trim(),
        // Empty input + already-stored key = keep the stored one.
        api_key: apiKey.trim() || current.data?.api_key || "",
      }),
    onSuccess: (saved) => {
      client.setQueryData(["llm", "config"], saved);
      setApiKey("");
      push({
        kind: "success",
        title: saved.mode === "cloud" ? `Мозг: облако (${saved.model})` : "Мозг: локальная модель",
        description: "Переключение применяется мгновенно, без перезапуска.",
      });
    },
    onError: (err) =>
      push({ kind: "error", title: "Не удалось переключить", description: String(err) }),
  });

  const storedKeyHint = current.data?.api_key
    ? `сохранён: …${current.data.api_key.slice(-4)}`
    : "вставьте токен (sk-…)";

  return (
    <section className="rounded-xl border border-border bg-background/40 p-4">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
        <BrainCircuit className="h-4 w-4" />
        Модель ИИ
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={() => setMode("local")}
          className={cn(
            "flex min-h-12 items-center justify-center gap-2 rounded-lg border text-sm",
            mode === "local"
              ? "border-primary bg-primary/15 font-semibold"
              : "border-border text-muted-foreground",
          )}
        >
          <Cpu className="h-4 w-4" /> Локальная
        </button>
        <button
          type="button"
          onClick={() => setMode("cloud")}
          className={cn(
            "flex min-h-12 items-center justify-center gap-2 rounded-lg border text-sm",
            mode === "cloud"
              ? "border-primary bg-primary/15 font-semibold"
              : "border-border text-muted-foreground",
          )}
        >
          <Cloud className="h-4 w-4" /> ChatGPT / облако
        </button>
      </div>

      {mode === "cloud" && (
        <div className="mt-3 space-y-2">
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={storedKeyHint}
            autoComplete="off"
            className="w-full rounded-lg border border-border bg-background/60 px-3 py-2 text-sm outline-none focus:border-primary"
          />
          <div className="grid grid-cols-2 gap-2">
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="gpt-4o-mini"
              className="rounded-lg border border-border bg-background/60 px-3 py-2 text-sm outline-none focus:border-primary"
            />
            <input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.openai.com"
              className="rounded-lg border border-border bg-background/60 px-3 py-2 text-xs outline-none focus:border-primary"
            />
          </div>
          <p className="text-xs text-muted-foreground">
            Подходит любой OpenAI-совместимый сервис (OpenAI, DeepSeek,
            OpenRouter). Токен хранится только на роботе. Нужен интернет.
          </p>
        </div>
      )}

      <button
        type="button"
        disabled={save.isPending || (mode === "cloud" && !apiKey.trim() && !current.data?.api_key)}
        onClick={() => save.mutate()}
        className="mt-3 flex min-h-12 w-full items-center justify-center gap-2 rounded-lg bg-primary text-sm font-semibold text-primary-foreground disabled:opacity-40"
      >
        {save.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
        Применить
      </button>

      <p className="mt-2 text-xs text-muted-foreground">
        Сейчас:{" "}
        {current.data?.mode === "cloud"
          ? `облако — ${current.data.model}`
          : "локальная модель (Qwen 3B, офлайн)"}
      </p>
    </section>
  );
}
