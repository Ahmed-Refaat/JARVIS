"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import type { IntelSourceSessionStatus } from "./types";

export interface StepRecord {
  number: number;
  url: string | null;
  screenshotUrl: string | null;
  nextGoal: string | null;
}

export interface SessionPollResult {
  sessionStatus: IntelSourceSessionStatus;
  liveUrl?: string;
  shareUrl?: string;
  currentUrl?: string;
  steps: StepRecord[];
}

interface UseSessionPollerOptions {
  sessionId: string | undefined;
  enabled: boolean;
  intervalMs?: number;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function useSessionPoller({
  sessionId,
  enabled,
  intervalMs = 2000,
}: UseSessionPollerOptions) {
  const [data, setData] = useState<SessionPollResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const stopped = useRef(false);

  const poll = useCallback(async () => {
    if (!sessionId || stopped.current) return;
    try {
      const res = await fetch(`${API_BASE}/api/agents/sessions/${sessionId}`);
      if (!res.ok) {
        setError(`Poll failed: ${res.status}`);
        return;
      }
      const json = await res.json();
      const result: SessionPollResult = {
        sessionStatus: json.session_status ?? "pending",
        liveUrl: json.live_url ?? undefined,
        shareUrl: json.share_url ?? undefined,
        currentUrl: json.task?.steps?.at(-1)?.url ?? undefined,
        steps: (json.task?.steps ?? []).map((s: Record<string, unknown>) => ({
          number: s.number,
          url: s.url ?? null,
          screenshotUrl: s.screenshot_url ?? null,
          nextGoal: s.next_goal ?? null,
        })),
      };
      setData(result);
      if (result.sessionStatus === "completed" || result.sessionStatus === "failed") {
        stopped.current = true;
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Poll error");
    }
  }, [sessionId]);

  useEffect(() => {
    if (!enabled || !sessionId) return;
    stopped.current = false;
    poll(); // immediate first fetch
    const id = setInterval(poll, intervalMs);
    return () => clearInterval(id);
  }, [enabled, sessionId, intervalMs, poll]);

  return { data, error };
}
