// RESEARCH: VisionClaw (1.4k stars, Feb 2026) provides signaling server
// DECISION: Using VisionClaw's WebSocket signaling protocol directly
// No npm package needed — just WebSocket + RTCPeerConnection
"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type StreamStatus = "disconnected" | "connecting" | "live" | "error";

interface UseGlassesStreamReturn {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  status: StreamStatus;
  connect: (roomCode: string) => void;
  disconnect: () => void;
  error: string | null;
}

const SIGNAL_WS = "wss://visionclaw-signal.fly.dev";
const TURN_ENDPOINT = "https://visionclaw-signal.fly.dev/api/turn";

export function useGlassesStream(): UseGlassesStreamReturn {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<StreamStatus>("disconnected");
  const [error, setError] = useState<string | null>(null);

  const disconnect = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    pcRef.current?.close();
    pcRef.current = null;
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setStatus("disconnected");
    setError(null);
  }, []);

  const connect = useCallback((roomCode: string) => {
    if (!/^[a-zA-Z0-9]{6}$/.test(roomCode)) {
      setError("Room code must be 6 alphanumeric characters");
      setStatus("error");
      return;
    }

    disconnect();
    setStatus("connecting");
    setError(null);

    (async () => {
      try {
        // Step 1: Fetch TURN credentials for NAT traversal
        const turnRes = await fetch(TURN_ENDPOINT);
        const turnConfig = await turnRes.json();

        // Step 2: Create peer connection with TURN servers
        const pc = new RTCPeerConnection(turnConfig);
        pcRef.current = pc;

        // Step 3: Handle incoming video track from glasses
        pc.ontrack = (event) => {
          if (videoRef.current && event.streams[0]) {
            videoRef.current.srcObject = event.streams[0];
            setStatus("live");
          }
        };

        pc.oniceconnectionstatechange = () => {
          const state = pc.iceConnectionState;
          if (state === "failed" || state === "disconnected") {
            setError("Connection lost");
            setStatus("error");
          }
        };

        // Step 4: Connect to VisionClaw signaling server
        const ws = new WebSocket(SIGNAL_WS);
        wsRef.current = ws;

        const pendingCandidates: RTCIceCandidateInit[] = [];

        ws.onopen = () => {
          ws.send(JSON.stringify({ type: "join", room: roomCode }));
        };

        ws.onmessage = async (event) => {
          const msg = JSON.parse(event.data);

          if (msg.type === "error") {
            setError(msg.message || "Signaling error");
            setStatus("error");
            return;
          }

          if (msg.type === "peer_left") {
            setError("Glasses disconnected");
            setStatus("error");
            return;
          }

          if (msg.type === "offer") {
            await pc.setRemoteDescription({ type: "offer", sdp: msg.sdp });
            // Flush any candidates that arrived before the offer
            for (const c of pendingCandidates) {
              await pc.addIceCandidate(c);
            }
            pendingCandidates.length = 0;
            const answer = await pc.createAnswer();
            await pc.setLocalDescription(answer);
            ws.send(JSON.stringify({ type: "answer", sdp: answer.sdp }));
          }

          if (msg.type === "candidate") {
            const candidate: RTCIceCandidateInit = {
              candidate: msg.candidate,
              sdpMid: msg.sdpMid,
              sdpMLineIndex: msg.sdpMLineIndex,
            };
            if (pc.remoteDescription) {
              await pc.addIceCandidate(candidate);
            } else {
              pendingCandidates.push(candidate);
            }
          }
        };

        // Forward local ICE candidates to signaling server
        pc.onicecandidate = (event) => {
          if (event.candidate && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
              type: "candidate",
              candidate: event.candidate.candidate,
              sdpMid: event.candidate.sdpMid,
              sdpMLineIndex: event.candidate.sdpMLineIndex,
            }));
          }
        };

        ws.onerror = () => {
          setError("Signaling server connection failed");
          setStatus("error");
        };

        ws.onclose = () => {
          if (pcRef.current === pc) {
            setStatus("disconnected");
          }
        };
      } catch (err) {
        setError(err instanceof Error ? err.message : "Connection failed");
        setStatus("error");
      }
    })();
  }, [disconnect]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      wsRef.current?.close();
      pcRef.current?.close();
    };
  }, []);

  return { videoRef, status, connect, disconnect, error };
}
