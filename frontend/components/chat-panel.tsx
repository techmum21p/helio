"use client";
import { useState, useEffect, useRef } from "react";
import type { ChatMessage } from "@/lib/types";
import { getChatHistory, streamChat } from "@/lib/api";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Props {
  runId: string | null;
  placeholder?: string;
}

export default function ChatPanel({ runId, placeholder = "Ask anything about solar opportunities…" }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bufferRef = useRef("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMessages([]);
    if (!runId) return;
    getChatHistory(runId).then(setMessages).catch(() => {});
  }, [runId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendMessage() {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    setStreaming(true);
    bufferRef.current = "";

    const userMsg: ChatMessage = { role: "user", content: text, created_at: new Date().toISOString() };
    const assistantMsg: ChatMessage = { role: "assistant", content: "", created_at: new Date().toISOString() };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);

    try {
      for await (const chunk of streamChat(text, runId)) {
        bufferRef.current += chunk;
        setMessages((prev) => [
          ...prev.slice(0, -1),
          { ...prev[prev.length - 1], content: bufferRef.current },
        ]);
      }
    } finally {
      setStreaming(false);
    }
  }

  return (
    <div className="flex flex-col h-full bg-slate-950">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0">
        {messages.length === 0 && (
          <p className="text-slate-600 text-sm text-center mt-8">{placeholder}</p>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
              msg.role === "user"
                ? "bg-amber-500/20 text-amber-100 border border-amber-500/30"
                : "bg-slate-800 text-slate-200"
            }`}>
              {msg.role === "assistant" ? (
                <div className="prose prose-sm prose-invert max-w-none prose-p:my-1 prose-headings:text-amber-400">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {msg.content || (streaming && i === messages.length - 1 ? "▌" : "")}
                  </ReactMarkdown>
                </div>
              ) : (
                <p>{msg.content}</p>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="border-t border-slate-800 p-3 flex gap-2 shrink-0">
        <input
          type="text"
          className="flex-1 bg-slate-900 border border-slate-700 text-slate-200 text-sm rounded px-3 py-2 focus:outline-none focus:border-amber-500"
          placeholder={placeholder}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendMessage()}
          disabled={streaming}
        />
        <button
          className="px-4 py-2 bg-amber-500 hover:bg-amber-400 disabled:opacity-40 text-slate-950 text-sm font-semibold rounded transition-colors"
          onClick={sendMessage}
          disabled={streaming || !input.trim()}
        >
          {streaming ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}
