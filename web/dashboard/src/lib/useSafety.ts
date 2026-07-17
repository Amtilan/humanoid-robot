import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type SafetyStatus } from "../api/client";
import { useEventSubscription } from "./eventStream";
import { useToast } from "./toast";

const isEstopSubject = (subject: string) =>
  subject === "safety.estop.engaged" || subject === "safety.estop.released";

export interface Safety {
  /** undefined while loading; defaults to "engaged" (fail-safe) when unknown. */
  engaged: boolean;
  loaded: boolean;
  pending: boolean;
  engage: (reason?: string) => void;
  release: () => void;
}

/**
 * Shared soft e-stop state. Same query key as the dev SafetyPage so the cache
 * is shared; estop bus events flip the cached flag instantly, which keeps
 * every open tab/device in sync.
 */
export function useSafety(): Safety {
  const client = useQueryClient();
  const { push } = useToast();

  const status = useQuery({
    queryKey: ["safety", "status"],
    queryFn: api.safetyStatus,
    refetchInterval: 10_000,
  });

  useEventSubscription(isEstopSubject, (envelope) => {
    const engaged = envelope.subject === "safety.estop.engaged";
    client.setQueryData<SafetyStatus | undefined>(["safety", "status"], (prev) =>
      prev ? { ...prev, estop_engaged: engaged } : prev,
    );
  });

  const engage = useMutation({
    mutationFn: (reason?: string) => api.safetyEngage({ actor: "operator", reason }),
    onSuccess: () => push({ kind: "warning", title: "Движения запрещены" }),
    onError: (err) =>
      push({ kind: "error", title: "Не получилось запретить", description: String(err) }),
  });

  const release = useMutation({
    mutationFn: () => api.safetyRelease({ actor: "operator" }),
    onSuccess: () => push({ kind: "success", title: "Движения разрешены" }),
    onError: (err) =>
      push({ kind: "error", title: "Не получилось разрешить", description: String(err) }),
  });

  return {
    engaged: status.data?.estop_engaged ?? true,
    loaded: status.data !== undefined,
    pending: engage.isPending || release.isPending,
    engage: (reason?: string) => engage.mutate(reason),
    release: () => release.mutate(),
  };
}
