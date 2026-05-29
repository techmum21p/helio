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
        setMessages((prev) => [...prev.slice(0, -1), { ...prev[prev.length - 1], content: bufferRef.current }]);
      }
    } finally {
      setStreaming(false);
    }
  }

  return (
    <div className="flex flex-col h-full bg-white">
      <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-0">
        {messages.length === 0 && (
          <p className="text-stone-400 text-sm text-center mt-8">{placeholder}</p>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
              msg.role === "user"
                ? "bg-amber-600 text-white"
                : "bg-stone-100 text-stone-700 border border-stone-200"
            }`}>
              {msg.role === "assistant" ? (
                <div className="prose prose-sm max-w-none prose-p:my-1">
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
      <div className="border-t border-stone-200 p-3 flex gap-2 shrink-0 bg-white">
        <input
          type="text"
          className="flex-1 bg-stone-50 border border-stone-200 text-stone-700 text-sm rounded-md px-3 py-2 focus:outline-none focus:border-amber-400"
          placeholder={placeholder}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendMessage()}
          disabled={streaming}
        />
        <button
          className="px-4 py-2 bg-amber-600 hover:bg-amber-700 disabled:opacity-40 text-white text-sm font-semibold rounded-md transition-colors"
          onClick={sendMessage}
          disabled={streaming || !input.trim()}
        >
          {streaming ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}
