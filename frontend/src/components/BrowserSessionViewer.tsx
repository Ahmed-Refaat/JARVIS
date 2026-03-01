"use client";

import { useState, useRef, useCallback } from "react";
import type { IntelSourceSessionStatus } from "@/lib/types";
import { useSessionPoller, type StepRecord } from "@/lib/useSessionPoller";

interface BrowserSessionViewerProps {
  sessionId: string;
  sessionStatus: IntelSourceSessionStatus;
  liveUrl?: string;
  shareUrl?: string;
  sourceNm: string;
  sourceTp: string;
}

/* ── status dot colors ─────────────────────────────────── */
const STATUS_COLORS: Record<IntelSourceSessionStatus, string> = {
  pending: "#f59e0b",
  running: "#4ade80",
  completed: "#6b7280",
  failed: "#ef4444",
};

const STATUS_LABELS: Record<IntelSourceSessionStatus, string> = {
  pending: "INITIALIZING",
  running: "LIVE",
  completed: "COMPLETE",
  failed: "FAILED",
};

export function BrowserSessionViewer({
  sessionId,
  sessionStatus: initialStatus,
  liveUrl: initialLiveUrl,
  shareUrl: initialShareUrl,
  sourceNm,
  sourceTp,
}: BrowserSessionViewerProps) {
  const [iframeBlocked, setIframeBlocked] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // Poll for live updates when session is active
  const isActive = initialStatus === "running" || initialStatus === "pending";
  const { data: pollData } = useSessionPoller({
    sessionId: isActive ? sessionId : undefined,
    enabled: isActive,
  });

  // Merge polled data with initial props
  const status = pollData?.sessionStatus ?? initialStatus;
  const liveUrl = pollData?.liveUrl ?? initialLiveUrl;
  const shareUrl = pollData?.shareUrl ?? initialShareUrl;
  const currentUrl = pollData?.currentUrl ?? "";
  const steps: StepRecord[] = pollData?.steps ?? [];

  const dotColor = STATUS_COLORS[status];
  const statusLabel = STATUS_LABELS[status];
  const isRunning = status === "running";
  const isCompleted = status === "completed";
  const isPending = status === "pending";
  const isFailed = status === "failed";

  // Which URL to show in the iframe
  const iframeSrc = isRunning ? liveUrl : isCompleted ? shareUrl : undefined;

  const handleIframeLoad = useCallback(() => {
    if (!iframeRef.current) return;
    try {
      // Cross-origin check — if this throws, iframe is blocked
      const _href = iframeRef.current.contentWindow?.location?.href;
      void _href;
    } catch {
      setIframeBlocked(true);
    }
  }, []);

  const prevStep = () => setCurrentStep(i => Math.max(0, i - 1));
  const nextStep = () => setCurrentStep(i => Math.min(steps.length - 1, i + 1));

  /* ── screenshot carousel (fallback) ──────────────────── */
  const renderScreenshotCarousel = () => {
    if (steps.length === 0) return renderPending("LOADING AGENT STEPS...");
    const step = steps[currentStep];
    return (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column" }}>
        <div style={{
          flex: 1, position: "relative", overflow: "hidden",
          background: "#0a0a0a", display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          {step?.screenshotUrl ? (
            <img
              src={step.screenshotUrl}
              alt={`Step ${step.number}`}
              style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }}
            />
          ) : (
            <div style={{ color: "rgba(120,180,80,.3)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
              NO SCREENSHOT AVAILABLE
            </div>
          )}
          {step?.nextGoal && (
            <div style={{
              position: "absolute", bottom: 0, left: 0, right: 0,
              padding: "8px 12px",
              background: "linear-gradient(transparent, rgba(0,0,0,.85))",
              color: "rgba(120,180,80,.7)", fontSize: 10, fontFamily: "var(--font-mono)",
            }}>
              {step.nextGoal}
            </div>
          )}
        </div>
        {/* Step navigator */}
        <div style={{
          height: 28, display: "flex", alignItems: "center", justifyContent: "center", gap: 12,
          background: "rgba(0,0,0,.6)", borderTop: "1px solid rgba(120,180,80,.1)",
        }}>
          <button onClick={prevStep} disabled={currentStep === 0} style={navBtnStyle}>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="15 18 9 12 15 6" />
            </svg>
          </button>
          <span style={{
            color: "rgba(120,180,80,.5)", fontSize: 9, fontFamily: "var(--font-mono)", letterSpacing: ".1em",
          }}>
            STEP {currentStep + 1} / {steps.length}
          </span>
          <button onClick={nextStep} disabled={currentStep >= steps.length - 1} style={navBtnStyle}>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </button>
        </div>
      </div>
    );
  };

  const renderPending = (msg: string) => (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      alignItems: "center", justifyContent: "center", gap: 16, background: "#080a06",
    }}>
      <div style={{
        width: 36, height: 36, borderRadius: "50%",
        border: "2px solid rgba(120,180,80,.15)",
        borderTopColor: "rgba(120,180,80,.5)",
        animation: "spin 1s linear infinite",
      }} />
      <div style={{
        color: "rgba(120,180,80,.4)", fontSize: 10, fontFamily: "var(--font-mono)",
        letterSpacing: ".15em", animation: "blink 1.5s ease-in-out infinite",
      }}>
        {msg}
      </div>
    </div>
  );

  const renderFailed = () => (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      alignItems: "center", justifyContent: "center", gap: 12, background: "#0a0606",
    }}>
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="1.5">
        <circle cx="12" cy="12" r="10" />
        <line x1="15" y1="9" x2="9" y2="15" />
        <line x1="9" y1="9" x2="15" y2="15" />
      </svg>
      <div style={{
        color: "rgba(239,68,68,.7)", fontSize: 10, fontFamily: "var(--font-mono)", letterSpacing: ".15em",
      }}>
        AGENT TERMINATED
      </div>
    </div>
  );

  /* ── content area ────────────────────────────────────── */
  const renderContent = () => {
    if (isPending) return renderPending("AGENT INITIALIZING...");
    if (isFailed) return renderFailed();

    // Try iframe first, fall back to screenshots
    if (iframeSrc && !iframeBlocked) {
      return (
        <iframe
          ref={iframeRef}
          src={iframeSrc}
          onLoad={handleIframeLoad}
          sandbox="allow-scripts allow-same-origin allow-popups"
          style={{ width: "100%", height: "100%", border: "none", background: "#0a0a0a" }}
        />
      );
    }

    // Fallback: screenshot carousel
    return renderScreenshotCarousel();
  };

  const displayUrl = currentUrl || iframeSrc || `browser-use.com/sessions/${sessionId}`;

  return (
    <div style={{
      width: "100%", borderRadius: 4, overflow: "hidden",
      border: "1px solid rgba(120,180,80,.12)",
      background: "#0c0e0a",
    }}>
      <style>{`
        @keyframes spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}
        @keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
        @keyframes statusPulse{0%,100%{opacity:1;box-shadow:0 0 4px currentColor}50%{opacity:.5;box-shadow:0 0 2px currentColor}}
      `}</style>

      {/* ── Tab bar ────────────────────────────────────── */}
      <div style={{
        height: 28, display: "flex", alignItems: "center", gap: 8,
        padding: "0 10px",
        background: "#111410",
        borderBottom: "1px solid rgba(120,180,80,.08)",
      }}>
        {/* Status dot */}
        <div style={{
          width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
          background: dotColor, color: dotColor,
          animation: isRunning ? "statusPulse 2s ease-in-out infinite" : "none",
        }} />
        {/* Tab pill */}
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          padding: "3px 10px", borderRadius: 3,
          background: "rgba(120,180,80,.06)",
          border: "1px solid rgba(120,180,80,.1)",
        }}>
          <span style={{
            color: "rgba(120,180,80,.5)", fontSize: 8, fontWeight: 700,
            letterSpacing: ".1em", fontFamily: "var(--font-mono)",
          }}>
            {sourceTp}
          </span>
          <span style={{ color: "rgba(120,180,80,.2)", fontSize: 8 }}>//</span>
          <span style={{
            color: "rgba(200,214,176,.6)", fontSize: 9, fontFamily: "var(--font-mono)",
          }}>
            {sourceNm}
          </span>
        </div>
        {/* Status label */}
        <span style={{
          marginLeft: "auto", fontSize: 8, fontWeight: 700, letterSpacing: ".12em",
          fontFamily: "var(--font-mono)", color: dotColor,
        }}>
          {statusLabel}
        </span>
      </div>

      {/* ── URL bar ────────────────────────────────────── */}
      <div style={{
        height: 32, display: "flex", alignItems: "center", gap: 8,
        padding: "0 10px",
        background: "rgba(0,0,0,.4)",
        borderBottom: "1px solid rgba(120,180,80,.06)",
      }}>
        {/* Navigation arrows */}
        <div style={{ display: "flex", gap: 4 }}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="rgba(120,180,80,.25)" strokeWidth="2">
            <polyline points="15 18 9 12 15 6" />
          </svg>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="rgba(120,180,80,.25)" strokeWidth="2">
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </div>
        {/* URL field */}
        <div style={{
          flex: 1, display: "flex", alignItems: "center", gap: 6,
          padding: "4px 10px", borderRadius: 3,
          background: "rgba(120,180,80,.04)",
          border: "1px solid rgba(120,180,80,.08)",
          overflow: "hidden",
        }}>
          {/* Lock icon */}
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="rgba(120,180,80,.3)" strokeWidth="2">
            <rect x="3" y="11" width="18" height="11" rx="2" />
            <path d="M7 11V7a5 5 0 0110 0v4" />
          </svg>
          <span style={{
            color: "rgba(120,180,80,.45)", fontSize: 10, fontFamily: "var(--font-mono)",
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>
            {displayUrl}
          </span>
        </div>
        {/* Reload icon */}
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="rgba(120,180,80,.2)" strokeWidth="2">
          <polyline points="23 4 23 10 17 10" />
          <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
        </svg>
        {/* Replay button */}
        {isCompleted && shareUrl && (
          <button
            onClick={() => window.open(shareUrl, "_blank")}
            style={{
              padding: "3px 8px", borderRadius: 3,
              background: "rgba(120,180,80,.12)", border: "1px solid rgba(120,180,80,.2)",
              color: "rgba(120,180,80,.7)", fontSize: 8, fontWeight: 700,
              letterSpacing: ".08em", fontFamily: "var(--font-mono)",
              cursor: "pointer", whiteSpace: "nowrap",
            }}
          >
            OPEN REPLAY
          </button>
        )}
      </div>

      {/* ── Content area ───────────────────────────────── */}
      <div style={{ height: 400, position: "relative" }}>
        {renderContent()}
      </div>
    </div>
  );
}

const navBtnStyle: React.CSSProperties = {
  background: "none", border: "none", cursor: "pointer",
  color: "rgba(120,180,80,.4)", padding: 4, display: "flex",
  alignItems: "center", justifyContent: "center",
};
