# Helio v2 Next.js Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Next.js 14 App Router frontend for Helio v2, plus two backend enhancements (SSE step events and streaming chat) required to support it.

**Architecture:** FastAPI backend at `localhost:8000` (already complete). Next.js app at `localhost:3000` in `frontend/`. Backend changes are minimal — add an in-memory event store for SSE step tracking and add streaming output to the chat endpoint. Frontend uses SWR for data fetching, native `EventSource` for SSE, and native `fetch` + `ReadableStream` for streaming chat.

**Tech Stack:** Next.js 14 App Router, TypeScript, Tailwind CSS, shadcn/ui, SWR, react-leaflet, react-markdown, remark-gfm; Python: LangGraph `stream()`, Anthropic SDK streaming

---

## File Map

### Backend (modified)
- `api/events.py` — NEW: in-memory step-event store keyed by run_id
- `graph/pipeline.py` — add `run_id` param, switch `invoke()` → `stream()`, emit step events
- `api/routers/runs.py` — pass run_id to pipeline, update `/runs/{id}/stream` to yield step events
- `agents/chatbot.py` — add `chat_stream()` generator
- `api/routers/chat.py` — replace `POST /chat` with `StreamingResponse`
- `tests/api/test_events.py` — NEW: unit tests for event store
- `tests/api/test_chat.py` — update existing tests for streaming endpoint
- `tests/api/test_runs.py` — update stream test for step events

### Frontend (all new under `frontend/`)
- `package.json`, `tsconfig.json`, `tailwind.config.ts`, `next.config.ts`, `.env.local`
- `app/layout.tsx` — root layout: dark bg, Nav
- `app/page.tsx` — redirect to `/explore`
- `app/explore/page.tsx`
- `app/analyze/page.tsx`
- `app/analyze/[runId]/page.tsx`
- `app/reports/page.tsx` — redirect to latest run
- `app/reports/[runId]/page.tsx`
- `app/chat/page.tsx`
- `app/admin/page.tsx`
- `components/nav.tsx`
- `components/score-bar.tsx`
- `components/tier-badge.tsx`
- `components/municipality-table.tsx`
- `components/map-view.tsx` — react-leaflet, dynamic import
- `components/run-progress.tsx`
- `components/chat-panel.tsx`
- `components/run-list.tsx`
- `components/stat-card.tsx`
- `lib/types.ts`
- `lib/api.ts`

---

## Task 1: In-Memory Event Store

**Files:**
- Create: `api/events.py`
- Create: `tests/api/test_events.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_events.py
from api.events import push_event, get_events, clear_events

def test_push_and_get():
    push_event("run1", "geo_scoring", "running", 0)
    push_event("run1", "geo_scoring", "done", 4200)
    events = get_events("run1")
    assert len(events) == 2
    assert events[0] == {"step": "geo_scoring", "status": "running", "elapsed_ms": 0}
    assert events[1] == {"step": "geo_scoring", "status": "done", "elapsed_ms": 4200}

def test_get_unknown_run_returns_empty():
    assert get_events("nonexistent") == []

def test_clear_removes_events():
    push_event("run2", "web_intel", "done", 1000)
    clear_events("run2")
    assert get_events("run2") == []

def test_clear_unknown_run_is_safe():
    clear_events("never_existed")  # must not raise
```

- [ ] **Step 2: Run test to confirm failure**

```bash
cd /Users/aireesm4/Python_Projects/helio
source .venv_helios/bin/activate
pytest tests/api/test_events.py -v
```

Expected: `ModuleNotFoundError: No module named 'api.events'`

- [ ] **Step 3: Create `api/events.py`**

```python
from __future__ import annotations
import threading

_lock = threading.Lock()
_run_events: dict[str, list[dict]] = {}


def push_event(run_id: str, step: str, status: str, elapsed_ms: int) -> None:
    with _lock:
        _run_events.setdefault(run_id, []).append(
            {"step": step, "status": status, "elapsed_ms": elapsed_ms}
        )


def get_events(run_id: str) -> list[dict]:
    with _lock:
        return list(_run_events.get(run_id, []))


def clear_events(run_id: str) -> None:
    with _lock:
        _run_events.pop(run_id, None)
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
pytest tests/api/test_events.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add api/events.py tests/api/test_events.py
git commit -m "feat: in-memory step-event store for SSE pipeline progress"
```

---

## Task 2: SSE Step Events — Pipeline + Stream Endpoint

**Files:**
- Modify: `graph/pipeline.py`
- Modify: `api/routers/runs.py`
- Modify: `tests/api/test_runs.py` (update stream test)

- [ ] **Step 1: Update `graph/pipeline.py`**

Replace the full file:

```python
import time
import uuid
from langgraph.graph import StateGraph, START, END

from graph.state import SolarLeadState
from agents.geo_scoring import geo_scoring_agent
from agents.web_intel import web_intel_agent
from agents.synthesis import synthesis_agent
from agents.report_gen import report_gen_agent
from agents.chatbot import update_kb_node

_STEPS = ["geo_scoring", "web_intel", "synthesis", "report_gen", "update_kb"]


def build_pipeline() -> StateGraph:
    graph = StateGraph(SolarLeadState)
    graph.add_node("geo_scoring", geo_scoring_agent)
    graph.add_node("web_intel", web_intel_agent)
    graph.add_node("synthesis", synthesis_agent)
    graph.add_node("report_gen", report_gen_agent)
    graph.add_node("update_kb", update_kb_node)
    graph.add_edge(START, "geo_scoring")
    graph.add_edge("geo_scoring", "web_intel")
    graph.add_edge("web_intel", "synthesis")
    graph.add_edge("synthesis", "report_gen")
    graph.add_edge("report_gen", "update_kb")
    graph.add_edge("update_kb", END)
    return graph.compile()


def run_pipeline(location: str, run_id: str | None = None) -> SolarLeadState:
    from api.events import push_event  # imported lazily to avoid circular import

    pipeline = build_pipeline()
    pipeline_run_id = run_id or str(uuid.uuid4())[:8]

    initial_state: SolarLeadState = {
        "location": location,
        "run_id": pipeline_run_id,
        "geo_scores": None,
        "geo_geojson": None,
        "web_intel": None,
        "final_scores": None,
        "top_targets": None,
        "report_markdown": None,
        "report_path": None,
        "chat_history": [],
        "kb_updated": False,
        "errors": [],
        "status": "running",
    }

    t0 = time.monotonic()
    if run_id:
        push_event(run_id, _STEPS[0], "running", 0)

    state = initial_state
    for step_output in pipeline.stream(initial_state, stream_mode="updates"):
        node_name = next(iter(step_output))
        state = {**state, **step_output[node_name]}
        elapsed = int((time.monotonic() - t0) * 1000)

        if run_id:
            push_event(run_id, node_name, "done", elapsed)
            idx = _STEPS.index(node_name) if node_name in _STEPS else -1
            if idx >= 0 and idx + 1 < len(_STEPS):
                push_event(run_id, _STEPS[idx + 1], "running", elapsed)

    return state


if __name__ == "__main__":
    result = run_pipeline("Laguna")
    print("Status:", result["status"])
    print("Top targets:", result.get("top_targets", [])[:3])
```

- [ ] **Step 2: Update `_run_pipeline_bg` and `/runs/{id}/stream` in `api/routers/runs.py`**

Replace just the `_run_pipeline_bg` function and the `stream_run` endpoint (keep the rest unchanged):

```python
# Replace _run_pipeline_bg:
def _run_pipeline_bg(run_id: str, location: str) -> None:
    try:
        with get_db() as conn:
            conn.execute("UPDATE runs SET status='running' WHERE id=?", (run_id,))
        from graph.pipeline import run_pipeline
        result = run_pipeline(location, run_id=run_id)
        _persist_run_results(run_id, result)
    except Exception as exc:
        with get_db() as conn:
            conn.execute(
                "UPDATE runs SET status='failed', error=?, completed_at=? WHERE id=?",
                (str(exc), datetime.now(timezone.utc).isoformat(), run_id),
            )


# Replace stream_run endpoint:
@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str) -> StreamingResponse:
    from api.events import get_events, clear_events

    async def _events():
        emitted = 0
        while True:
            # Flush any new events
            events = get_events(run_id)
            while emitted < len(events):
                yield f"data: {json.dumps(events[emitted])}\n\n"
                emitted += 1

            with get_db() as conn:
                row = conn.execute(
                    "SELECT status, error FROM runs WHERE id=?", (run_id,)
                ).fetchone()

            if not row:
                yield 'data: {"error": "run not found"}\n\n'
                return

            if row["status"] in ("done", "failed"):
                # Flush remaining events before terminal
                events = get_events(run_id)
                while emitted < len(events):
                    yield f"data: {json.dumps(events[emitted])}\n\n"
                    emitted += 1
                step = "complete" if row["status"] == "done" else "failed"
                payload = json.dumps({"step": step, "run_id": run_id, "error": row["error"]})
                yield f"data: {payload}\n\n"
                clear_events(run_id)
                return

            await asyncio.sleep(0.5)

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 3: Update the stream test in `tests/api/test_runs.py`**

Find the existing stream test (if any) and replace/add:

```python
from unittest.mock import patch
from api.events import push_event, clear_events

def test_stream_emits_step_events(app_client):
    with patch("api.routers.runs._run_pipeline_bg"):
        run_id = app_client.post("/runs", json={"location": "Laguna"}).json()["run_id"]

    # Simulate events that the pipeline would have pushed
    push_event(run_id, "geo_scoring", "running", 0)
    push_event(run_id, "geo_scoring", "done", 4200)

    # Mark run as done in DB
    import api.db as db_module
    with db_module.get_db() as conn:
        conn.execute("UPDATE runs SET status='done' WHERE id=?", (run_id,))

    with app_client.stream("GET", f"/runs/{run_id}/stream") as response:
        chunks = b"".join(response.iter_bytes()).decode()

    assert '"step": "geo_scoring"' in chunks
    assert '"status": "done"' in chunks
    assert '"step": "complete"' in chunks
    clear_events(run_id)
```

- [ ] **Step 4: Run all run tests**

```bash
pytest tests/api/test_runs.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add graph/pipeline.py api/routers/runs.py tests/api/test_runs.py
git commit -m "feat: SSE step events — pipeline emits per-node progress via event store"
```

---

## Task 3: Streaming Chat

**Files:**
- Modify: `agents/chatbot.py`
- Modify: `api/routers/chat.py`
- Modify: `tests/api/test_chat.py`

- [ ] **Step 1: Add `chat_stream()` to `agents/chatbot.py`**

Add this function after the existing `chat()` function (do not remove `chat()`):

```python
def chat_stream(user_message: str, chat_history: list):
    """Generator yielding text chunks for streaming. Caller accumulates the full reply."""
    index_documents_from_kb()
    context = retrieve_context(user_message)

    messages = chat_history.copy()
    messages.append({
        "role": "user",
        "content": f"Context from knowledge base:\n{context}\n\nQuestion: {user_message}",
    })

    try:
        with client.messages.stream(
            model=config.CHATBOT_MODEL,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                yield text
    except Exception as e:
        yield f"Sorry, I couldn't generate a response: {e}"
```

- [ ] **Step 2: Replace `POST /chat` in `api/routers/chat.py`**

Replace the full file:

```python
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from api.db import get_db
from api.models import ChatMessageOut

router = APIRouter(tags=["chat"])


def _stream_chatbot(message: str, history: list[dict]):
    """Thin wrapper so tests can patch streaming without touching the chatbot module."""
    from agents.chatbot import chat_stream
    return chat_stream(message, history)


@router.post("/chat")
def send_message_stream(
    body: dict,  # {"message": str, "run_id": str | None}
) -> StreamingResponse:
    message: str = body.get("message", "")
    run_id: str | None = body.get("run_id")

    history: list[dict] = []
    if run_id:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT role, content FROM chat_messages WHERE run_id=? ORDER BY created_at",
                (run_id,),
            ).fetchall()
        history = [{"role": r["role"], "content": r["content"]} for r in rows]

    def _generate():
        chunks: list[str] = []
        for chunk in _stream_chatbot(message, history):
            chunks.append(chunk)
            yield f"data: {chunk}\n\n"
        full_reply = "".join(chunks)
        if run_id:
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO chat_messages (run_id, role, content) VALUES (?,?,?)",
                    (run_id, "user", message),
                )
                conn.execute(
                    "INSERT INTO chat_messages (run_id, role, content) VALUES (?,?,?)",
                    (run_id, "assistant", full_reply),
                )
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/chat/{run_id}/history")
def get_history(run_id: str) -> list[ChatMessageOut]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT role, content, created_at FROM chat_messages "
            "WHERE run_id=? ORDER BY created_at",
            (run_id,),
        ).fetchall()
    return [ChatMessageOut(**dict(r)) for r in rows]
```

- [ ] **Step 3: Update `tests/api/test_chat.py` for streaming endpoint**

Replace the full file:

```python
from unittest.mock import patch


def _make_run(app_client):
    with patch("api.routers.runs._run_pipeline_bg"):
        return app_client.post("/runs", json={"location": "Laguna"}).json()["run_id"]


def _read_sse(response) -> str:
    """Collect all SSE data lines from a streaming response into one string."""
    return b"".join(response.iter_bytes()).decode()


def test_chat_returns_stream(app_client):
    run_id = _make_run(app_client)
    with patch("api.routers.chat._stream_chatbot", return_value=iter(["Hello", " world"])):
        with app_client.stream("POST", "/chat", json={"run_id": run_id, "message": "Hi"}
        ) as r:
            body = _read_sse(r)
    assert "data: Hello\n\n" in body
    assert "data:  world\n\n" in body
    assert "data: [DONE]\n\n" in body


def test_chat_global_no_run_id(app_client):
    with patch("api.routers.chat._stream_chatbot", return_value=iter(["Global reply"])):
        with app_client.stream("POST", "/chat", json={"message": "Best solar towns?"}) as r:
            body = _read_sse(r)
    assert "data: Global reply\n\n" in body
    assert "data: [DONE]\n\n" in body


def test_chat_persists_messages(app_client):
    run_id = _make_run(app_client)
    with patch("api.routers.chat._stream_chatbot", return_value=iter(["Stored", " reply"])):
        with app_client.stream(
            "POST", "/chat", json={"run_id": run_id, "message": "What's the score?"}
        ) as r:
            _read_sse(r)  # exhaust the stream so persistence runs
    r2 = app_client.get(f"/chat/{run_id}/history")
    msgs = r2.json()
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "What's the score?"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"] == "Stored reply"


def test_chat_no_persist_without_run_id(app_client):
    run_id = _make_run(app_client)
    with patch("api.routers.chat._stream_chatbot", return_value=iter(["No-persist"])):
        with app_client.stream("POST", "/chat", json={"message": "Anything"}) as r:
            _read_sse(r)
    assert app_client.get(f"/chat/{run_id}/history").json() == []


def test_chat_history_empty_for_new_run(app_client):
    run_id = _make_run(app_client)
    assert app_client.get(f"/chat/{run_id}/history").json() == []
```

- [ ] **Step 4: Run chat tests**

```bash
pytest tests/api/test_chat.py -v
```

Expected: 5 passed

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
pytest tests/ -v
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add agents/chatbot.py api/routers/chat.py tests/api/test_chat.py
git commit -m "feat: streaming chat — POST /chat returns SSE token stream"
```

---

## Task 4: Next.js Scaffold

**Files:**
- Create: `frontend/` (full Next.js project)

- [ ] **Step 1: Scaffold the Next.js app**

```bash
cd /Users/aireesm4/Python_Projects/helio
npx create-next-app@14 frontend \
  --typescript \
  --tailwind \
  --eslint \
  --app \
  --no-src-dir \
  --import-alias "@/*" \
  --no-git
```

- [ ] **Step 2: Install additional dependencies**

```bash
cd frontend
npm install swr react-markdown remark-gfm react-leaflet leaflet
npm install -D @types/leaflet
```

- [ ] **Step 3: Initialize shadcn/ui**

```bash
cd /Users/aireesm4/Python_Projects/helio/frontend
npx shadcn@latest init --yes --base-color slate
npx shadcn@latest add button badge select separator skeleton scroll-area input
```

- [ ] **Step 4: Create `.env.local`**

```bash
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > frontend/.env.local
```

- [ ] **Step 5: Update `frontend/next.config.ts`** to allow the API URL

Replace contents with:

```typescript
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [];
  },
};

export default nextConfig;
```

- [ ] **Step 6: Update `tailwind.config.ts`** to add the slate-900 dark theme base

Open `frontend/tailwind.config.ts` and confirm `content` includes `./app/**` and `./components/**` — the default create-next-app output already does this, no change needed.

- [ ] **Step 7: Verify the scaffold builds**

```bash
cd /Users/aireesm4/Python_Projects/helio/frontend
npm run build
```

Expected: Build succeeds with no errors

- [ ] **Step 8: Commit**

```bash
cd /Users/aireesm4/Python_Projects/helio
git add frontend/
git commit -m "feat: scaffold Next.js 14 frontend with shadcn/ui and react-leaflet"
```

---

## Task 5: Shared Types + API Client

**Files:**
- Create: `frontend/lib/types.ts`
- Create: `frontend/lib/api.ts`

- [ ] **Step 1: Create `frontend/lib/types.ts`**

```typescript
export interface Province {
  name: string;
}

export interface Municipality {
  id: number;
  name: string;
  province: string;
  region: string;
  lat: number | null;
  lon: number | null;
  geo_score: number | null;
  solar_norm: number | null;
  income_score: number | null;
  pop_density_norm: number | null;
}

export type RunStatus = "pending" | "running" | "done" | "failed";

export interface Run {
  id: string;
  location: string;
  province: string | null;
  status: RunStatus;
  created_at: string;
  completed_at: string | null;
  error: string | null;
}

export interface RunResult {
  municipality_id: number;
  municipality_name: string;
  province: string;
  geo_score: number;
  web_score: number;
  final_score: number;
  tier: string;
  assessment: string;
  opportunities: string[];
  risks: string[];
}

export interface Report {
  slug: string;
  markdown: string;
  file_path: string;
  created_at: string;
}

export interface RunDetail extends Run {
  results: RunResult[];
  report: Report | null;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface AdminStats {
  municipalities: number;
  geo_scores: number;
  runs: number;
  run_results: number;
  chat_messages: number;
  reports: number;
  web_intel_cache: number;
  last_precompute: string | null;
}

export interface StepEvent {
  step: string;
  status: "running" | "done" | "failed" | "complete";
  elapsed_ms: number;
  run_id?: string;
  error?: string | null;
}

export type Tier = "A" | "B" | "C" | "D";

export function getTier(score: number | null): Tier | null {
  if (score === null) return null;
  if (score >= 0.8) return "A";
  if (score >= 0.65) return "B";
  if (score >= 0.5) return "C";
  return "D";
}
```

- [ ] **Step 2: Create `frontend/lib/api.ts`**

```typescript
import type {
  Province, Municipality, Run, RunDetail,
  ChatMessage, AdminStats,
} from "./types";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── REST helpers ───────────────────────────────────────────────────────────────

export async function getProvinces(): Promise<Province[]> {
  const res = await fetch(`${API_URL}/provinces`);
  if (!res.ok) throw new Error("Failed to fetch provinces");
  return res.json();
}

export async function getMunicipalities(opts?: {
  province?: string;
  search?: string;
  limit?: number;
}): Promise<Municipality[]> {
  const params = new URLSearchParams();
  if (opts?.province) params.set("province", opts.province);
  if (opts?.search) params.set("search", opts.search);
  params.set("limit", String(opts?.limit ?? 2000));
  const res = await fetch(`${API_URL}/municipalities?${params}`);
  if (!res.ok) throw new Error("Failed to fetch municipalities");
  return res.json();
}

export async function createRun(location: string): Promise<{ run_id: string }> {
  const res = await fetch(`${API_URL}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ location }),
  });
  if (!res.ok) throw new Error("Failed to create run");
  return res.json();
}

export async function getRuns(limit = 50): Promise<Run[]> {
  const res = await fetch(`${API_URL}/runs?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch runs");
  return res.json();
}

export async function getRun(runId: string): Promise<RunDetail> {
  const res = await fetch(`${API_URL}/runs/${runId}`);
  if (!res.ok) throw new Error("Failed to fetch run");
  return res.json();
}

export async function getChatHistory(runId: string): Promise<ChatMessage[]> {
  const res = await fetch(`${API_URL}/chat/${runId}/history`);
  if (!res.ok) throw new Error("Failed to fetch chat history");
  return res.json();
}

export async function getAdminStats(): Promise<AdminStats> {
  const res = await fetch(`${API_URL}/admin/stats`);
  if (!res.ok) throw new Error("Failed to fetch admin stats");
  return res.json();
}

export async function postAdminReindexKB(): Promise<void> {
  const res = await fetch(`${API_URL}/admin/reindex-kb`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to trigger reindex");
}

export async function postAdminRefreshScores(): Promise<void> {
  const res = await fetch(`${API_URL}/admin/refresh-scores`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to trigger refresh");
}

// ── EventSource helpers ────────────────────────────────────────────────────────

export function openRunStream(runId: string): EventSource {
  return new EventSource(`${API_URL}/runs/${runId}/stream`);
}

export function openRefreshStream(): EventSource {
  return new EventSource(`${API_URL}/admin/refresh-scores/stream`);
}

// ── Streaming chat ─────────────────────────────────────────────────────────────

export async function* streamChat(
  message: string,
  runId: string | null
): AsyncGenerator<string> {
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, run_id: runId }),
  });
  if (!res.ok) throw new Error("Chat request failed");

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const text = decoder.decode(value, { stream: true });
    for (const line of text.split("\n")) {
      if (!line.startsWith("data: ")) continue;
      const data = line.slice(6);
      if (data === "[DONE]") return;
      if (data) yield data;
    }
  }
}
```

- [ ] **Step 3: Verify TypeScript compilation**

```bash
cd /Users/aireesm4/Python_Projects/helio/frontend
npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
cd /Users/aireesm4/Python_Projects/helio
git add frontend/lib/
git commit -m "feat: shared TypeScript types and typed API client"
```

---

## Task 6: Root Layout + Nav

**Files:**
- Modify: `frontend/app/layout.tsx`
- Create: `frontend/app/page.tsx`
- Create: `frontend/components/nav.tsx`

- [ ] **Step 1: Create `frontend/components/nav.tsx`**

```typescript
"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_LINKS = [
  { href: "/explore", label: "Explore" },
  { href: "/analyze", label: "Analyze" },
  { href: "/reports", label: "Reports" },
  { href: "/chat", label: "Chat" },
  { href: "/admin", label: "Admin" },
];

export default function Nav() {
  const pathname = usePathname();
  return (
    <nav className="h-14 border-b border-slate-800 bg-slate-950 flex items-center px-6 gap-8 shrink-0">
      <Link href="/explore" className="flex items-center gap-2 mr-4">
        <span className="text-amber-400 text-lg">☀</span>
        <span className="text-slate-100 font-semibold tracking-wide text-sm">HELIO</span>
      </Link>
      {NAV_LINKS.map(({ href, label }) => {
        const active = pathname === href || pathname.startsWith(href + "/");
        return (
          <Link
            key={href}
            href={href}
            className={`text-sm transition-colors ${
              active
                ? "text-amber-400 font-medium"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
```

- [ ] **Step 2: Replace `frontend/app/layout.tsx`**

```typescript
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import Nav from "@/components/nav";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Helio — Solar Opportunity Intelligence",
  description: "Identify solar installation targets in the Philippines",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.className} bg-slate-950 text-slate-100 min-h-screen flex flex-col`}>
        <Nav />
        <main className="flex-1 flex flex-col">{children}</main>
      </body>
    </html>
  );
}
```

- [ ] **Step 3: Create `frontend/app/page.tsx`**

```typescript
import { redirect } from "next/navigation";

export default function Home() {
  redirect("/explore");
}
```

- [ ] **Step 4: Update `frontend/app/globals.css`** to set dark base colors

Open `frontend/app/globals.css` and add after the existing Tailwind directives:

```css
@layer base {
  :root {
    --background: 222 47% 6%;
    --foreground: 213 31% 91%;
  }
  body {
    @apply bg-slate-950 text-slate-100;
  }
}
```

- [ ] **Step 5: Start dev server and verify nav renders**

```bash
cd /Users/aireesm4/Python_Projects/helio/frontend
npm run dev
```

Open http://localhost:3000 — should redirect to `/explore` (404 is fine for now) and show the dark nav with "☀ HELIO" and the five links.

- [ ] **Step 6: Commit**

```bash
cd /Users/aireesm4/Python_Projects/helio
git add frontend/app/layout.tsx frontend/app/page.tsx frontend/app/globals.css frontend/components/nav.tsx
git commit -m "feat: root layout and nav — dark theme, amber accents"
```

---

## Task 7: ScoreBar + TierBadge

**Files:**
- Create: `frontend/components/score-bar.tsx`
- Create: `frontend/components/tier-badge.tsx`

- [ ] **Step 1: Create `frontend/components/score-bar.tsx`**

```typescript
interface ScoreBarProps {
  solar: number | null;
  income: number | null;
  popDensity: number | null;
  showLabels?: boolean;
}

export default function ScoreBar({ solar, income, popDensity, showLabels = false }: ScoreBarProps) {
  const s = solar ?? 0;
  const i = income ?? 0;
  const p = popDensity ?? 0;

  return (
    <div className="w-full space-y-1">
      <div className="flex items-center gap-2">
        {showLabels && <span className="text-xs text-slate-500 w-12 shrink-0">Solar</span>}
        <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
          <div className="h-full bg-blue-400 rounded-full" style={{ width: `${s * 100}%` }} />
        </div>
        {showLabels && <span className="text-xs text-blue-400 w-8 text-right">{s.toFixed(2)}</span>}
      </div>
      <div className="flex items-center gap-2">
        {showLabels && <span className="text-xs text-slate-500 w-12 shrink-0">Income</span>}
        <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
          <div className="h-full bg-emerald-400 rounded-full" style={{ width: `${i * 100}%` }} />
        </div>
        {showLabels && <span className="text-xs text-emerald-400 w-8 text-right">{i.toFixed(2)}</span>}
      </div>
      <div className="flex items-center gap-2">
        {showLabels && <span className="text-xs text-slate-500 w-12 shrink-0">Pop</span>}
        <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
          <div className="h-full bg-violet-400 rounded-full" style={{ width: `${p * 100}%` }} />
        </div>
        {showLabels && <span className="text-xs text-violet-400 w-8 text-right">{p.toFixed(2)}</span>}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create `frontend/components/tier-badge.tsx`**

```typescript
import type { Tier } from "@/lib/types";

const TIER_STYLES: Record<Tier, string> = {
  A: "bg-amber-500/20 text-amber-400 border border-amber-500/40",
  B: "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40",
  C: "bg-blue-500/20 text-blue-400 border border-blue-500/40",
  D: "bg-slate-700/50 text-slate-400 border border-slate-600",
};

export default function TierBadge({ tier }: { tier: Tier | null }) {
  if (!tier) return <span className="text-slate-600 text-xs">—</span>;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${TIER_STYLES[tier]}`}>
      {tier}
    </span>
  );
}
```

- [ ] **Step 3: Commit**

```bash
cd /Users/aireesm4/Python_Projects/helio
git add frontend/components/score-bar.tsx frontend/components/tier-badge.tsx
git commit -m "feat: ScoreBar and TierBadge components"
```

---

## Task 8: MunicipalityTable

**Files:**
- Create: `frontend/components/municipality-table.tsx`

- [ ] **Step 1: Create `frontend/components/municipality-table.tsx`**

```typescript
"use client";
import { useState, useMemo } from "react";
import type { Municipality } from "@/lib/types";
import { getTier } from "@/lib/types";
import ScoreBar from "./score-bar";
import TierBadge from "./tier-badge";

const PAGE_SIZE = 50;

type SortKey = "geo_score" | "solar_norm" | "income_score" | "pop_density_norm" | "name";

interface Props {
  municipalities: Municipality[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

export default function MunicipalityTable({ municipalities, selectedId, onSelect }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("geo_score");
  const [sortAsc, setSortAsc] = useState(false);
  const [page, setPage] = useState(0);

  const sorted = useMemo(() => {
    return [...municipalities].sort((a, b) => {
      const av = a[sortKey] ?? -1;
      const bv = b[sortKey] ?? -1;
      if (typeof av === "string") return sortAsc ? av.localeCompare(bv as string) : (bv as string).localeCompare(av);
      return sortAsc ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
  }, [municipalities, sortKey, sortAsc]);

  const totalPages = Math.ceil(sorted.length / PAGE_SIZE);
  const page_items = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortAsc((a) => !a);
    else { setSortKey(key); setSortAsc(false); }
    setPage(0);
  }

  function ColHead({ k, label }: { k: SortKey; label: string }) {
    const active = sortKey === k;
    return (
      <th
        className="px-3 py-2 text-left text-xs text-slate-500 font-medium uppercase tracking-wider cursor-pointer select-none hover:text-slate-300"
        onClick={() => toggleSort(k)}
      >
        {label} {active ? (sortAsc ? "↑" : "↓") : ""}
      </th>
    );
  }

  return (
    <div className="flex flex-col gap-0">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="border-b border-slate-800 sticky top-0 bg-slate-950">
            <tr>
              <th className="px-3 py-2 text-left text-xs text-slate-500 font-medium uppercase tracking-wider w-10">#</th>
              <ColHead k="name" label="Municipality" />
              <th className="px-3 py-2 text-left text-xs text-slate-500 font-medium uppercase tracking-wider">Province</th>
              <ColHead k="solar_norm" label="Solar" />
              <ColHead k="income_score" label="Income" />
              <ColHead k="pop_density_norm" label="Pop" />
              <ColHead k="geo_score" label="Geo Score" />
              <th className="px-3 py-2 text-left text-xs text-slate-500 font-medium uppercase tracking-wider">Tier</th>
            </tr>
          </thead>
          <tbody>
            {page_items.map((m, idx) => {
              const rank = page * PAGE_SIZE + idx + 1;
              const expanded = selectedId === m.id;
              return (
                <>
                  <tr
                    key={m.id}
                    className={`border-b border-slate-800/50 cursor-pointer transition-colors ${
                      expanded ? "bg-amber-500/5 border-amber-500/20" : "hover:bg-slate-900"
                    }`}
                    onClick={() => onSelect(expanded ? -1 : m.id)}
                  >
                    <td className="px-3 py-2.5 text-slate-600 tabular-nums">{rank}</td>
                    <td className="px-3 py-2.5 text-slate-200 font-medium">{m.name}</td>
                    <td className="px-3 py-2.5 text-slate-400">{m.province}</td>
                    <td className="px-3 py-2.5 text-blue-400 tabular-nums">{m.solar_norm?.toFixed(2) ?? "—"}</td>
                    <td className="px-3 py-2.5 text-emerald-400 tabular-nums">{m.income_score?.toFixed(2) ?? "—"}</td>
                    <td className="px-3 py-2.5 text-violet-400 tabular-nums">{m.pop_density_norm?.toFixed(2) ?? "—"}</td>
                    <td className="px-3 py-2.5 text-amber-400 font-semibold tabular-nums">
                      {m.geo_score?.toFixed(3) ?? "—"}
                    </td>
                    <td className="px-3 py-2.5">
                      <TierBadge tier={getTier(m.geo_score)} />
                    </td>
                  </tr>
                  {expanded && (
                    <tr key={`${m.id}-expanded`} className="bg-amber-500/5 border-b border-amber-500/20">
                      <td colSpan={8} className="px-6 py-3">
                        <div className="max-w-sm">
                          <p className="text-xs text-slate-400 mb-2">Score breakdown — {m.name}, {m.province}</p>
                          <ScoreBar
                            solar={m.solar_norm}
                            income={m.income_score}
                            popDensity={m.pop_density_norm}
                            showLabels
                          />
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between px-4 py-3 border-t border-slate-800 text-xs text-slate-500">
        <span>{sorted.length.toLocaleString()} municipalities</span>
        <div className="flex items-center gap-2">
          <button
            className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-30 disabled:cursor-not-allowed"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
          >
            ←
          </button>
          <span>Page {page + 1} / {totalPages}</span>
          <button
            className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-30 disabled:cursor-not-allowed"
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
          >
            →
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/aireesm4/Python_Projects/helio
git add frontend/components/municipality-table.tsx
git commit -m "feat: MunicipalityTable — sortable, paginated, expandable score rows"
```

---

## Task 9: MapView

**Files:**
- Create: `frontend/components/map-view.tsx`

- [ ] **Step 1: Create `frontend/components/map-view.tsx`**

```typescript
"use client";
import { useEffect } from "react";
import { MapContainer, TileLayer, CircleMarker, Tooltip } from "react-leaflet";
import type { Municipality } from "@/lib/types";
import "leaflet/dist/leaflet.css";

interface Props {
  municipalities: Municipality[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

function scoreColor(score: number | null): string {
  if (score === null) return "#475569";
  if (score >= 0.8) return "#f59e0b";
  if (score >= 0.65) return "#10b981";
  if (score >= 0.5) return "#3b82f6";
  return "#64748b";
}

export default function MapView({ municipalities, selectedId, onSelect }: Props) {
  // Fix leaflet default marker icon missing in Next.js
  useEffect(() => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const L = require("leaflet");
    delete (L.Icon.Default.prototype as { _getIconUrl?: unknown })._getIconUrl;
    L.Icon.Default.mergeOptions({
      iconRetinaUrl: "/leaflet/marker-icon-2x.png",
      iconUrl: "/leaflet/marker-icon.png",
      shadowUrl: "/leaflet/marker-shadow.png",
    });
  }, []);

  const withCoords = municipalities.filter((m) => m.lat !== null && m.lon !== null);

  return (
    <MapContainer
      center={[12.8797, 121.774]}
      zoom={6}
      className="w-full h-full"
      style={{ background: "#0f172a" }}
    >
      <TileLayer
        url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        attribution='&copy; <a href="https://carto.com/">CARTO</a>'
      />
      {withCoords.map((m) => (
        <CircleMarker
          key={m.id}
          center={[m.lat!, m.lon!]}
          radius={selectedId === m.id ? 8 : 5}
          pathOptions={{
            color: selectedId === m.id ? "#f59e0b" : scoreColor(m.geo_score),
            fillColor: selectedId === m.id ? "#f59e0b" : scoreColor(m.geo_score),
            fillOpacity: 0.8,
            weight: selectedId === m.id ? 2 : 1,
          }}
          eventHandlers={{ click: () => onSelect(m.id) }}
        >
          <Tooltip>
            <div className="text-xs">
              <strong>{m.name}</strong>, {m.province}
              <br />
              Geo Score: {m.geo_score?.toFixed(3) ?? "—"}
            </div>
          </Tooltip>
        </CircleMarker>
      ))}
    </MapContainer>
  );
}
```

- [ ] **Step 2: Copy leaflet marker assets to `frontend/public/leaflet/`**

```bash
mkdir -p /Users/aireesm4/Python_Projects/helio/frontend/public/leaflet
cp /Users/aireesm4/Python_Projects/helio/frontend/node_modules/leaflet/dist/images/marker-icon.png \
   /Users/aireesm4/Python_Projects/helio/frontend/public/leaflet/
cp /Users/aireesm4/Python_Projects/helio/frontend/node_modules/leaflet/dist/images/marker-icon-2x.png \
   /Users/aireesm4/Python_Projects/helio/frontend/public/leaflet/
cp /Users/aireesm4/Python_Projects/helio/frontend/node_modules/leaflet/dist/images/marker-shadow.png \
   /Users/aireesm4/Python_Projects/helio/frontend/public/leaflet/
```

- [ ] **Step 3: Commit**

```bash
cd /Users/aireesm4/Python_Projects/helio
git add frontend/components/map-view.tsx frontend/public/leaflet/
git commit -m "feat: MapView — react-leaflet dark tiles, score-colored markers"
```

---

## Task 10: Explore Page

**Files:**
- Create: `frontend/app/explore/page.tsx`

- [ ] **Step 1: Create `frontend/app/explore/page.tsx`**

```typescript
"use client";
import { useState, useMemo } from "react";
import useSWR from "swr";
import dynamic from "next/dynamic";
import type { Municipality, Province } from "@/lib/types";
import { getMunicipalities, getProvinces } from "@/lib/api";
import MunicipalityTable from "@/components/municipality-table";

const MapView = dynamic(() => import("@/components/map-view"), { ssr: false });

const fetcher = (fn: () => Promise<unknown>) => fn();

export default function ExplorePage() {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [showMap, setShowMap] = useState(false);
  const [provinceFilter, setProvinceFilter] = useState("");
  const [searchFilter, setSearchFilter] = useState("");
  const [minScore, setMinScore] = useState(0);

  const { data: municipalities = [], isLoading } = useSWR<Municipality[]>(
    "municipalities",
    () => getMunicipalities({ limit: 2000 })
  );
  const { data: provinces = [] } = useSWR<Province[]>("provinces", getProvinces);

  const filtered = useMemo(() => {
    return municipalities.filter((m) => {
      if (provinceFilter && m.province !== provinceFilter) return false;
      if (searchFilter && !m.name.toLowerCase().includes(searchFilter.toLowerCase())) return false;
      if (minScore > 0 && (m.geo_score ?? 0) < minScore) return false;
      return true;
    });
  }, [municipalities, provinceFilter, searchFilter, minScore]);

  function handleSelect(id: number) {
    setSelectedId((prev) => (prev === id ? null : id));
    if (!showMap) return;
    // Scroll to selected row is handled inside MunicipalityTable
  }

  return (
    <div className="flex flex-col h-[calc(100vh-56px)]">
      {/* Filter bar */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-800 bg-slate-950 shrink-0">
        <select
          className="bg-slate-900 border border-slate-700 text-slate-300 text-sm rounded px-2 py-1.5 focus:outline-none focus:border-amber-500"
          value={provinceFilter}
          onChange={(e) => { setProvinceFilter(e.target.value); setSelectedId(null); }}
        >
          <option value="">All provinces</option>
          {provinces.map((p) => (
            <option key={p.name} value={p.name}>{p.name}</option>
          ))}
        </select>
        <input
          type="text"
          placeholder="Search municipality…"
          className="bg-slate-900 border border-slate-700 text-slate-300 text-sm rounded px-2 py-1.5 focus:outline-none focus:border-amber-500 w-48"
          value={searchFilter}
          onChange={(e) => { setSearchFilter(e.target.value); setSelectedId(null); }}
        />
        <label className="flex items-center gap-1.5 text-sm text-slate-400 cursor-pointer">
          <span>Min score</span>
          <input
            type="range" min={0} max={1} step={0.05}
            value={minScore}
            onChange={(e) => setMinScore(Number(e.target.value))}
            className="w-24 accent-amber-400"
          />
          <span className="text-amber-400 tabular-nums w-8">{minScore.toFixed(2)}</span>
        </label>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-slate-500 text-xs">{filtered.length.toLocaleString()} results</span>
          <button
            className={`px-3 py-1.5 text-xs rounded border transition-colors ${
              showMap
                ? "border-amber-500 text-amber-400 bg-amber-500/10"
                : "border-slate-700 text-slate-400 hover:border-slate-500"
            }`}
            onClick={() => setShowMap((v) => !v)}
          >
            {showMap ? "Hide Map" : "Show Map"}
          </button>
        </div>
      </div>

      {/* Map panel */}
      {showMap && (
        <div className="h-64 shrink-0 border-b border-slate-800">
          <MapView
            municipalities={filtered}
            selectedId={selectedId}
            onSelect={handleSelect}
          />
        </div>
      )}

      {/* Table */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center h-32 text-slate-500">Loading…</div>
        ) : (
          <MunicipalityTable
            municipalities={filtered}
            selectedId={selectedId}
            onSelect={handleSelect}
          />
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Start FastAPI and Next.js, open http://localhost:3000/explore**

```bash
# Terminal 1
cd /Users/aireesm4/Python_Projects/helio
source .venv_helios/bin/activate
uvicorn api.main:app --reload

# Terminal 2
cd /Users/aireesm4/Python_Projects/helio/frontend
npm run dev
```

Verify:
- Table loads with municipalities sorted by geo score
- Province dropdown filters rows
- Search filters by name
- "Show Map" toggle shows the dark map with colored dots
- Clicking a map dot expands the matching row with score bars
- Clicking a row expands/collapses score breakdown
- Pagination works (50/page)

- [ ] **Step 3: Commit**

```bash
cd /Users/aireesm4/Python_Projects/helio
git add frontend/app/explore/
git commit -m "feat: Explore page — filterable table + togglable map with linked selection"
```

---

## Task 11: RunProgress + Analyze Pages

**Files:**
- Create: `frontend/components/run-progress.tsx`
- Create: `frontend/app/analyze/page.tsx`
- Create: `frontend/app/analyze/[runId]/page.tsx`

- [ ] **Step 1: Create `frontend/components/run-progress.tsx`**

```typescript
"use client";
import { useEffect, useState } from "react";
import type { StepEvent } from "@/lib/types";
import { openRunStream } from "@/lib/api";

const PIPELINE_STEPS = [
  { key: "geo_scoring",  label: "Geo Scoring",       description: "Loading pre-computed scores from DB" },
  { key: "web_intel",    label: "Web Intelligence",   description: "Fetching business & market data" },
  { key: "synthesis",    label: "Synthesis",          description: "Combining geo + web intelligence" },
  { key: "report_gen",   label: "Report Generation",  description: "Writing detailed markdown report" },
  { key: "update_kb",    label: "Knowledge Base",     description: "Indexing report into RAG store" },
];

type StepStatus = "waiting" | "running" | "done" | "failed";

interface Props {
  runId: string;
  onComplete?: (runId: string) => void;
  onFailed?: (error: string | null) => void;
}

export default function RunProgress({ runId, onComplete, onFailed }: Props) {
  const [stepStates, setStepStates] = useState<Record<string, StepStatus>>({});
  const [elapsedMs, setElapsedMs] = useState<Record<string, number>>({});
  const [terminated, setTerminated] = useState(false);

  useEffect(() => {
    if (!runId) return;
    const es = openRunStream(runId);

    es.onmessage = (e) => {
      let event: StepEvent;
      try { event = JSON.parse(e.data); } catch { return; }

      if (event.step === "complete") {
        setTerminated(true);
        es.close();
        onComplete?.(runId);
        return;
      }
      if (event.step === "failed") {
        setStepStates((prev) => ({ ...prev, [event.step]: "failed" }));
        setTerminated(true);
        es.close();
        onFailed?.(event.error ?? null);
        return;
      }
      setStepStates((prev) => ({ ...prev, [event.step]: event.status as StepStatus }));
      if (event.elapsed_ms) {
        setElapsedMs((prev) => ({ ...prev, [event.step]: event.elapsed_ms }));
      }
    };

    es.onerror = () => { if (!terminated) es.close(); };
    return () => es.close();
  }, [runId]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-3">
      {PIPELINE_STEPS.map((step) => {
        const status: StepStatus = stepStates[step.key] ?? "waiting";
        const ms = elapsedMs[step.key];
        return (
          <div key={step.key} className="flex items-start gap-3">
            <div className="mt-0.5 shrink-0">
              {status === "done" && (
                <div className="w-5 h-5 rounded-full bg-emerald-500 flex items-center justify-center text-white text-xs">✓</div>
              )}
              {status === "running" && (
                <div className="w-5 h-5 rounded-full border-2 border-amber-400 border-t-transparent animate-spin" />
              )}
              {status === "failed" && (
                <div className="w-5 h-5 rounded-full bg-red-500 flex items-center justify-center text-white text-xs">✕</div>
              )}
              {status === "waiting" && (
                <div className="w-5 h-5 rounded-full border border-slate-700 bg-slate-900" />
              )}
            </div>
            <div>
              <p className={`text-sm font-medium ${
                status === "running" ? "text-amber-400" :
                status === "done" ? "text-slate-200" :
                status === "failed" ? "text-red-400" : "text-slate-600"
              }`}>
                {step.label}
                {status === "done" && ms && (
                  <span className="ml-2 text-xs text-slate-500 font-normal">{(ms / 1000).toFixed(1)}s</span>
                )}
              </p>
              {status === "running" && (
                <p className="text-xs text-slate-500">{step.description}</p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Create `frontend/app/analyze/page.tsx`**

```typescript
"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import type { Province, Municipality } from "@/lib/types";
import { getProvinces, getMunicipalities, createRun } from "@/lib/api";

export default function AnalyzePage() {
  const router = useRouter();
  const [selectedProvince, setSelectedProvince] = useState("");
  const [selectedMunicipalities, setSelectedMunicipalities] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const { data: provinces = [] } = useSWR<Province[]>("provinces", getProvinces);
  const { data: municipalities = [] } = useSWR<Municipality[]>(
    selectedProvince ? `municipalities/${selectedProvince}` : null,
    () => getMunicipalities({ province: selectedProvince, limit: 2000 })
  );

  function toggleMunicipality(name: string) {
    setSelectedMunicipalities((prev) =>
      prev.includes(name) ? prev.filter((m) => m !== name) : [...prev, name]
    );
  }

  async function handleAnalyze() {
    if (!selectedProvince && selectedMunicipalities.length === 0) {
      setError("Select a province or at least one municipality.");
      return;
    }
    setError("");
    setLoading(true);
    try {
      let location: string;
      if (selectedMunicipalities.length === 1) {
        location = `${selectedMunicipalities[0]}, ${selectedProvince}`;
      } else if (selectedMunicipalities.length > 1) {
        location = `${selectedMunicipalities.join("|")}, ${selectedProvince}`;
      } else {
        location = selectedProvince;
      }
      const { run_id } = await createRun(location);
      router.push(`/analyze/${run_id}`);
    } catch (e) {
      setError(String(e));
      setLoading(false);
    }
  }

  return (
    <div className="max-w-xl mx-auto px-6 py-12">
      <h1 className="text-2xl font-semibold text-slate-100 mb-2">Analyze Location</h1>
      <p className="text-slate-400 text-sm mb-8">Run the full 5-step pipeline for a province or specific municipalities.</p>

      <div className="space-y-6">
        <div>
          <label className="block text-xs text-slate-500 uppercase tracking-wider mb-2">Province</label>
          <select
            className="w-full bg-slate-900 border border-slate-700 text-slate-200 rounded px-3 py-2 focus:outline-none focus:border-amber-500"
            value={selectedProvince}
            onChange={(e) => { setSelectedProvince(e.target.value); setSelectedMunicipalities([]); }}
          >
            <option value="">Select province…</option>
            {provinces.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
          </select>
        </div>

        {selectedProvince && municipalities.length > 0 && (
          <div>
            <label className="block text-xs text-slate-500 uppercase tracking-wider mb-2">
              Municipalities <span className="text-slate-600 normal-case">(optional — leave empty to analyze whole province)</span>
            </label>
            <div className="max-h-48 overflow-y-auto border border-slate-700 rounded divide-y divide-slate-800">
              {municipalities.map((m) => (
                <label key={m.id} className="flex items-center gap-3 px-3 py-2 hover:bg-slate-800 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selectedMunicipalities.includes(m.name)}
                    onChange={() => toggleMunicipality(m.name)}
                    className="accent-amber-400"
                  />
                  <span className="text-slate-300 text-sm">{m.name}</span>
                  {m.geo_score !== null && (
                    <span className="ml-auto text-amber-400 text-xs tabular-nums">{m.geo_score.toFixed(3)}</span>
                  )}
                </label>
              ))}
            </div>
          </div>
        )}

        {error && <p className="text-red-400 text-sm">{error}</p>}

        <button
          className="w-full py-2.5 bg-amber-500 hover:bg-amber-400 disabled:opacity-40 disabled:cursor-not-allowed text-slate-950 font-semibold rounded transition-colors"
          onClick={handleAnalyze}
          disabled={loading || !selectedProvince}
        >
          {loading ? "Starting…" : "Analyze"}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create `frontend/app/analyze/[runId]/page.tsx`**

```typescript
"use client";
import { useRouter, useParams } from "next/navigation";
import { useEffect } from "react";
import RunProgress from "@/components/run-progress";

export default function AnalyzeRunPage() {
  const { runId } = useParams<{ runId: string }>();
  const router = useRouter();

  function handleComplete(id: string) {
    setTimeout(() => router.push(`/reports/${id}`), 1500);
  }

  function handleFailed(error: string | null) {
    // stay on page — RunProgress shows the failed step
    console.error("Pipeline failed:", error);
  }

  return (
    <div className="max-w-md mx-auto px-6 py-16">
      <h1 className="text-lg font-medium text-slate-300 mb-2">Running analysis…</h1>
      <p className="text-xs text-slate-500 mb-8 font-mono">{runId}</p>
      <RunProgress runId={runId} onComplete={handleComplete} onFailed={handleFailed} />
    </div>
  );
}
```

- [ ] **Step 4: Verify analyze flow in browser**

With both servers running (FastAPI + Next.js dev):

1. Open http://localhost:3000/analyze
2. Select a province → municipality list populates
3. Click "Analyze" — should navigate to `/analyze/[runId]`
4. Step tracker should show steps updating via SSE
5. On completion, should auto-redirect to `/reports/[runId]`

- [ ] **Step 5: Commit**

```bash
cd /Users/aireesm4/Python_Projects/helio
git add frontend/components/run-progress.tsx frontend/app/analyze/
git commit -m "feat: Analyze page and RunProgress SSE step tracker"
```

---

## Task 12: ChatPanel + RunList

**Files:**
- Create: `frontend/components/chat-panel.tsx`
- Create: `frontend/components/run-list.tsx`

- [ ] **Step 1: Create `frontend/components/chat-panel.tsx`**

```typescript
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
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  className="prose prose-sm prose-invert max-w-none prose-p:my-1 prose-headings:text-amber-400"
                >
                  {msg.content || (streaming && i === messages.length - 1 ? "▌" : "")}
                </ReactMarkdown>
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
```

- [ ] **Step 2: Create `frontend/components/run-list.tsx`**

```typescript
"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { Run } from "@/lib/types";

const STATUS_STYLES = {
  done:    "bg-emerald-500/20 text-emerald-400",
  running: "bg-amber-500/20 text-amber-400",
  pending: "bg-slate-700 text-slate-400",
  failed:  "bg-red-500/20 text-red-400",
};

interface Props {
  runs: Run[];
  basePath?: string; // defaults to "/reports"
}

export default function RunList({ runs, basePath = "/reports" }: Props) {
  const pathname = usePathname();

  if (runs.length === 0) {
    return (
      <div className="p-4 text-slate-600 text-xs">
        No runs yet.{" "}
        <Link href="/analyze" className="text-amber-500 hover:underline">Run an analysis</Link>
      </div>
    );
  }

  return (
    <div className="divide-y divide-slate-800">
      {runs.map((run) => {
        const href = `${basePath}/${run.id}`;
        const active = pathname === href;
        const date = new Date(run.created_at).toLocaleDateString("en-PH", {
          month: "short", day: "numeric",
        });
        return (
          <Link
            key={run.id}
            href={href}
            className={`block px-3 py-3 transition-colors hover:bg-slate-900 ${
              active ? "bg-slate-900 border-l-2 border-amber-500" : ""
            }`}
          >
            <p className="text-xs text-slate-300 font-medium leading-snug line-clamp-2">{run.location}</p>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-slate-600 text-xs">{date}</span>
              <span className={`text-xs px-1.5 py-0.5 rounded ${STATUS_STYLES[run.status]}`}>
                {run.status}
              </span>
            </div>
          </Link>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
cd /Users/aireesm4/Python_Projects/helio
git add frontend/components/chat-panel.tsx frontend/components/run-list.tsx
git commit -m "feat: ChatPanel (streaming) and RunList sidebar components"
```

---

## Task 13: Reports Page

**Files:**
- Create: `frontend/app/reports/page.tsx`
- Create: `frontend/app/reports/[runId]/page.tsx`

- [ ] **Step 1: Create `frontend/app/reports/page.tsx`**

```typescript
import { redirect } from "next/navigation";
import { getRuns } from "@/lib/api";
import Link from "next/link";

export default async function ReportsIndexPage() {
  let runs;
  try { runs = await getRuns(1); } catch { runs = []; }

  if (runs.length > 0) redirect(`/reports/${runs[0].id}`);

  return (
    <div className="flex items-center justify-center h-[calc(100vh-56px)]">
      <div className="text-center">
        <p className="text-slate-400 mb-4">No reports yet.</p>
        <Link href="/analyze" className="px-4 py-2 bg-amber-500 text-slate-950 font-semibold rounded hover:bg-amber-400 transition-colors">
          Run your first analysis
        </Link>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create `frontend/app/reports/[runId]/page.tsx`**

```typescript
"use client";
import { useParams } from "next/navigation";
import useSWR from "swr";
import type { Run, RunDetail } from "@/lib/types";
import { getRuns, getRun } from "@/lib/api";
import RunList from "@/components/run-list";
import ChatPanel from "@/components/chat-panel";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export default function ReportPage() {
  const { runId } = useParams<{ runId: string }>();
  const { data: runs = [] } = useSWR<Run[]>("runs", () => getRuns(50));
  const { data: run, isLoading } = useSWR<RunDetail>(
    runId ? `run/${runId}` : null,
    () => getRun(runId)
  );

  function downloadMarkdown() {
    if (!run?.report?.markdown) return;
    const blob = new Blob([run.report.markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${run.report.slug}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div
      className="grid h-[calc(100vh-56px)]"
      style={{ gridTemplateColumns: "180px 1fr" }}
    >
      {/* Left sidebar — run list */}
      <aside className="border-r border-slate-800 overflow-y-auto bg-slate-950">
        <div className="px-3 py-3 border-b border-slate-800">
          <p className="text-xs text-slate-500 uppercase tracking-wider">Past Runs</p>
        </div>
        <RunList runs={runs} />
      </aside>

      {/* Right — report + chat */}
      <div className="flex flex-col overflow-hidden">
        {/* Report scroll area */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {isLoading && (
            <div className="flex items-center justify-center h-32 text-slate-500">Loading…</div>
          )}
          {run && !run.report && (
            <div className="p-8 text-slate-500">
              {run.status === "running" || run.status === "pending"
                ? "Analysis still running…"
                : "No report available for this run."}
            </div>
          )}
          {run?.report && (
            <div className="p-8">
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h1 className="text-xl font-semibold text-slate-100">{run.location}</h1>
                  <p className="text-xs text-slate-500 mt-1">
                    {new Date(run.created_at).toLocaleString("en-PH")}
                  </p>
                </div>
                <button
                  onClick={downloadMarkdown}
                  className="px-3 py-1.5 text-xs border border-slate-700 text-slate-400 rounded hover:border-slate-500 transition-colors"
                >
                  ↓ Download .md
                </button>
              </div>
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                className="prose prose-invert max-w-none prose-headings:text-amber-400 prose-a:text-amber-400 prose-strong:text-slate-200 prose-code:text-emerald-400 prose-pre:bg-slate-900 prose-table:text-sm"
              >
                {run.report.markdown}
              </ReactMarkdown>
            </div>
          )}
        </div>

        {/* Bottom-pinned chat */}
        <div className="h-72 border-t border-slate-800 shrink-0">
          <ChatPanel
            runId={runId}
            placeholder={`Ask about ${run?.location ?? "this report"}…`}
          />
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify reports page in browser**

1. After a completed run, open http://localhost:3000/reports
2. Should redirect to latest run
3. Left sidebar shows past runs, active highlighted
4. Center shows rendered markdown with amber headings
5. Click "Download .md" — file saves
6. Bottom chat panel is visible and accepts messages

- [ ] **Step 4: Commit**

```bash
cd /Users/aireesm4/Python_Projects/helio
git add frontend/app/reports/
git commit -m "feat: Reports page — three-panel with run list, markdown, and scoped chat"
```

---

## Task 14: Chat Page (Global)

**Files:**
- Create: `frontend/app/chat/page.tsx`

- [ ] **Step 1: Create `frontend/app/chat/page.tsx`**

```typescript
"use client";
import { useState } from "react";
import useSWR from "swr";
import type { Run } from "@/lib/types";
import { getRuns } from "@/lib/api";
import ChatPanel from "@/components/chat-panel";

export default function ChatPage() {
  const [contextRunId, setContextRunId] = useState<string | null>(null);
  const { data: runs = [] } = useSWR<Run[]>("runs", () => getRuns(50));

  return (
    <div
      className="h-[calc(100vh-56px)] grid"
      style={{ gridTemplateColumns: "1fr 220px" }}
    >
      {/* Chat panel */}
      <div className="border-r border-slate-800 overflow-hidden">
        <ChatPanel
          runId={contextRunId}
          placeholder={
            contextRunId
              ? "Ask about this run's municipalities…"
              : "Ask about any solar opportunity across all analyzed locations…"
          }
        />
      </div>

      {/* Run context switcher */}
      <aside className="overflow-y-auto bg-slate-950">
        <div className="px-3 py-3 border-b border-slate-800">
          <p className="text-xs text-slate-500 uppercase tracking-wider">Context</p>
        </div>
        <button
          className={`w-full text-left px-3 py-3 text-sm border-b border-slate-800 transition-colors hover:bg-slate-900 ${
            contextRunId === null ? "text-amber-400 bg-slate-900 border-l-2 border-amber-500" : "text-slate-400"
          }`}
          onClick={() => setContextRunId(null)}
        >
          Global KB
          <p className="text-xs text-slate-600 mt-0.5">All analyzed locations</p>
        </button>
        {runs.map((run) => (
          <button
            key={run.id}
            className={`w-full text-left px-3 py-3 border-b border-slate-800 transition-colors hover:bg-slate-900 ${
              contextRunId === run.id ? "bg-slate-900 border-l-2 border-amber-500" : ""
            }`}
            onClick={() => setContextRunId(run.id)}
          >
            <p className="text-xs text-slate-300 font-medium line-clamp-2">{run.location}</p>
            <p className="text-xs text-slate-600 mt-0.5">
              {new Date(run.created_at).toLocaleDateString("en-PH", { month: "short", day: "numeric" })}
            </p>
          </button>
        ))}
      </aside>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/aireesm4/Python_Projects/helio
git add frontend/app/chat/
git commit -m "feat: Chat page — global KB chat with run context switcher"
```

---

## Task 15: StatCard + Admin Page

**Files:**
- Create: `frontend/components/stat-card.tsx`
- Create: `frontend/app/admin/page.tsx`

- [ ] **Step 1: Create `frontend/components/stat-card.tsx`**

```typescript
interface Props {
  label: string;
  value: string | number | null;
  sub?: string;
}

export default function StatCard({ label, value, sub }: Props) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg px-4 py-4">
      <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">{label}</p>
      <p className="text-2xl font-semibold text-slate-100 tabular-nums">
        {value === null ? "—" : typeof value === "number" ? value.toLocaleString() : value}
      </p>
      {sub && <p className="text-xs text-slate-600 mt-1">{sub}</p>}
    </div>
  );
}
```

- [ ] **Step 2: Create `frontend/app/admin/page.tsx`**

```typescript
"use client";
import { useState } from "react";
import useSWR from "swr";
import type { AdminStats } from "@/lib/types";
import { getAdminStats, postAdminReindexKB, postAdminRefreshScores, openRefreshStream } from "@/lib/api";
import StatCard from "@/components/stat-card";
import RunProgress from "@/components/run-progress";

export default function AdminPage() {
  const { data: stats, mutate } = useSWR<AdminStats>("admin/stats", getAdminStats, {
    refreshInterval: 30000,
  });
  const [reindexing, setReindexing] = useState(false);
  const [reindexMsg, setReindexMsg] = useState("");
  const [refreshRunId, setRefreshRunId] = useState<string | null>(null);
  const [refreshMsg, setRefreshMsg] = useState("");

  async function handleReindex() {
    setReindexing(true);
    setReindexMsg("");
    try {
      await postAdminReindexKB();
      setReindexMsg("Re-index started.");
      setTimeout(() => mutate(), 3000);
    } catch (e) {
      setReindexMsg(`Error: ${e}`);
    } finally {
      setReindexing(false);
    }
  }

  async function handleRefresh() {
    setRefreshMsg("");
    try {
      await postAdminRefreshScores();
      // Use a synthetic run-like ID to trigger RunProgress with the admin stream
      setRefreshRunId("admin-refresh-" + Date.now());
    } catch (e) {
      setRefreshMsg(`Error: ${e}`);
    }
  }

  const lastPrecompute = stats?.last_precompute
    ? new Date(stats.last_precompute).toLocaleString("en-PH")
    : "Never";

  return (
    <div className="max-w-3xl mx-auto px-6 py-10">
      <h1 className="text-xl font-semibold text-slate-100 mb-6">Admin</h1>

      {/* Stats grid */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-10">
          <StatCard label="Municipalities" value={stats.municipalities} />
          <StatCard label="Geo Scores" value={stats.geo_scores} sub={`Last: ${lastPrecompute}`} />
          <StatCard label="Runs" value={stats.runs} />
          <StatCard label="Reports" value={stats.reports} />
          <StatCard label="Run Results" value={stats.run_results} />
          <StatCard label="Chat Messages" value={stats.chat_messages} />
          <StatCard label="Web Intel Cache" value={stats.web_intel_cache} />
          <StatCard label="KB Chunks" value={null} sub="ChromaDB (see logs)" />
        </div>
      )}

      {/* Actions */}
      <div className="space-y-6">
        <div className="border border-slate-800 rounded-lg p-5">
          <h2 className="text-sm font-semibold text-slate-200 mb-1">Refresh Geo Scores</h2>
          <p className="text-xs text-slate-500 mb-4">Re-run precompute_geo_scores.py for all 1,622 municipalities. Implemented in Plan 2.</p>
          {refreshRunId ? (
            <RunProgress
              runId={refreshRunId}
              onComplete={() => { setRefreshRunId(null); setRefreshMsg("Done."); mutate(); }}
              onFailed={(e) => { setRefreshRunId(null); setRefreshMsg(`Failed: ${e}`); }}
            />
          ) : (
            <button
              className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm rounded transition-colors"
              onClick={handleRefresh}
            >
              Refresh Geo Scores
            </button>
          )}
          {refreshMsg && <p className="mt-2 text-xs text-slate-400">{refreshMsg}</p>}
        </div>

        <div className="border border-slate-800 rounded-lg p-5">
          <h2 className="text-sm font-semibold text-slate-200 mb-1">Re-index Knowledge Base</h2>
          <p className="text-xs text-slate-500 mb-4">Scan kb/reports/ and kb/intel/ for new markdown files and add to ChromaDB.</p>
          <button
            className="px-4 py-2 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-slate-300 text-sm rounded transition-colors"
            onClick={handleReindex}
            disabled={reindexing}
          >
            {reindexing ? "Re-indexing…" : "Re-index KB"}
          </button>
          {reindexMsg && <p className="mt-2 text-xs text-slate-400">{reindexMsg}</p>}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify admin page in browser**

Open http://localhost:3000/admin — stat cards should show DB row counts. Both action buttons should be visible.

- [ ] **Step 4: Run full test suite one final time**

```bash
cd /Users/aireesm4/Python_Projects/helio
source .venv_helios/bin/activate
pytest tests/ -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add frontend/components/stat-card.tsx frontend/app/admin/
git commit -m "feat: Admin page — stats, re-index KB, refresh geo scores"
```

---

## Self-Review

**Spec coverage check:**
- ✅ Dark Intelligence aesthetic (slate/amber throughout)
- ✅ Explore: table-first, map toggle, score columns, tier badge
- ✅ Map click → scroll-to + expand row with ScoreBar
- ✅ Analyze: cascade selects, POST /runs, redirect to progress page
- ✅ Step tracker (5 steps, spinner → checkmark + elapsed)
- ✅ Reports: three-panel (RunList sidebar / markdown / bottom ChatPanel)
- ✅ Download .md button
- ✅ Chat: global KB + run context switcher
- ✅ Admin: stats cards + re-index KB + refresh scores (stub)
- ✅ SSE step events (Tasks 1–2)
- ✅ Streaming chat (Task 3)
- ✅ SWR for data fetching; EventSource for SSE; fetch + ReadableStream for chat
- ✅ NEXT_PUBLIC_API_URL env var; CORS already configured

**Type consistency:**
- `getTier()` defined in `lib/types.ts`, used in `municipality-table.tsx` and `tier-badge.tsx` ✅
- `openRunStream()` in `lib/api.ts`, called in `run-progress.tsx` ✅
- `openRefreshStream()` in `lib/api.ts`, available but admin page uses `RunProgress` with a synthetic ID (the admin refresh SSE endpoint is a stub until Plan 2) ✅
- `streamChat()` in `lib/api.ts`, called in `chat-panel.tsx` ✅
- `ChatMessage` type used by `chat-panel.tsx` and `run-list.tsx` — no conflict ✅
