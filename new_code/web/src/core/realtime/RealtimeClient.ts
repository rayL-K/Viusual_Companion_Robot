import { connectionPhase } from "../state/session";
import { parseServerEvent, PROTOCOL_VERSION, type ServerEvent } from "./protocol";

type EventHandler = (event: ServerEvent) => void;

export class RealtimeClient {
  private socket: WebSocket | null = null;
  private handlers = new Set<EventHandler>();

  constructor(private readonly url: string) {}

  connect(): void {
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) return;
    connectionPhase.value = "connecting";
    const socket = new WebSocket(this.url);
    socket.binaryType = "arraybuffer";
    this.socket = socket;
    socket.addEventListener("open", () => {
      connectionPhase.value = "online";
      this.send("session.hello", { capabilities: ["pcm16", "jpeg", "reply-segments"] });
    });
    socket.addEventListener("message", (message) => {
      if (typeof message.data !== "string") return;
      try {
        const event = parseServerEvent(message.data);
        for (const handler of this.handlers) handler(event);
      } catch {
        connectionPhase.value = "error";
      }
    });
    socket.addEventListener("close", () => {
      if (this.socket === socket) this.socket = null;
      connectionPhase.value = "offline";
    });
    socket.addEventListener("error", () => {
      connectionPhase.value = "error";
    });
  }

  disconnect(): void {
    this.socket?.close(1000, "page lifecycle ended");
    this.socket = null;
  }

  onEvent(handler: EventHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  send(type: string, payload: Record<string, unknown>): boolean {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify({ v: PROTOCOL_VERSION, type, sentAtMs: Date.now(), payload }));
    return true;
  }
}

export function realtimeUrl(locationLike: Location = window.location): string {
  const protocol = locationLike.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${locationLike.host}/v2/realtime`;
}
