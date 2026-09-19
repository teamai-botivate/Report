"use client";

import * as React from "react";
import axios from "axios";
import { Send, Sparkles, KeyRound, FlaskConical, LayoutList } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ReportCanvas } from "@/components/report/ReportCanvas";
import { postChat, getRecommended, runRecommended, ChatTimeoutError, ChatJobError } from "@/lib/api";
import { MOCK_CHAT_RESPONSE } from "@/lib/mockReport";
import type { ChatResponse, RecommendedReportSummary } from "@/lib/types";

// Chat runs as a background job on the server (see lib/api.ts's postChat)
// specifically because a multi-query AI question — query planning, several
// SQL generations, executions, report composition, each a separate OpenAI
// call — can legitimately take well over what a single blocking HTTP
// request can survive through a hosting proxy; a real production request
// logged 6 sequential OpenAI calls. Give the frontend a generous,
// failure-specific message for each real failure mode instead of one
// generic "something went wrong" that hides whether it was a timeout, a
// network drop, a job that genuinely errored, or an actual server error.
function describeChatError(err: unknown): string {
  if (err instanceof ChatTimeoutError) {
    return "That question is taking longer than expected. It may still be processing — please try asking again in a moment.";
  }
  if (err instanceof ChatJobError) {
    return `The AI service ran into a problem: ${err.message}`;
  }
  if (axios.isAxiosError(err)) {
    if (err.code === "ECONNABORTED") {
      return "That question took longer than expected to analyze (complex multi-step questions can take a while). Please try again — it may just need another moment.";
    }
    if (!err.response) {
      return "Couldn't reach the server. Please check your connection and try again.";
    }
    const detail = err.response.data as { detail?: string; message?: string } | undefined;
    const serverMessage = detail?.detail || detail?.message;
    return serverMessage
      ? `The server reported an error: ${serverMessage}`
      : `The server returned an unexpected error (status ${err.response.status}). Please try again.`;
  }
  return "Something went wrong reaching the AI service. Please try again.";
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  response?: ChatResponse;
}

const EXAMPLE_PROMPTS = [
  "Show total revenue",
  "Compare this month with last month",
  "Top 10 customers by revenue",
  "Which products have high sales but low stock?",
  "Show delayed deliveries",
  "Show attendance by department",
];

let msgCounter = 0;
function nextId() {
  msgCounter += 1;
  return `m_${Date.now()}_${msgCounter}`;
}

export default function ChatPage() {
  const [messages, setMessages] = React.useState<ChatMessage[]>([]);
  const [input, setInput] = React.useState("");
  const [sending, setSending] = React.useState(false);
  const [conversationId, setConversationId] = React.useState<string | undefined>(undefined);
  const [recommended, setRecommended] = React.useState<RecommendedReportSummary[]>([]);
  const [runningRecommended, setRunningRecommended] = React.useState<string | null>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const started = messages.length > 0;

  React.useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  React.useEffect(() => {
    // Recommended reports are a separate, zero-LLM feature the backend may
    // still be building out — hide the section entirely rather than crash
    // or show an error if the endpoint isn't there yet (e.g. 404).
    getRecommended()
      .then((reports) => setRecommended(reports))
      .catch(() => setRecommended([]));
  }, []);

  async function handleRunRecommended(id: string) {
    if (runningRecommended) return;
    setRunningRecommended(id);
    const summary = recommended.find((r) => r.id === id);
    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: "user", text: summary ? summary.title : id },
    ]);
    try {
      const response = await runRecommended(id);
      setConversationId(response.conversation_id);
      setMessages((prev) => [
        ...prev,
        { id: nextId(), role: "assistant", text: response.message, response },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { id: nextId(), role: "assistant", text: describeChatError(err) },
      ]);
    } finally {
      setRunningRecommended(null);
    }
  }

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || sending) return;
    setInput("");
    setMessages((prev) => [...prev, { id: nextId(), role: "user", text: trimmed }]);
    setSending(true);
    try {
      const response = await postChat(trimmed, conversationId);
      setConversationId(response.conversation_id);
      setMessages((prev) => [
        ...prev,
        { id: nextId(), role: "assistant", text: response.message, response },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { id: nextId(), role: "assistant", text: describeChatError(err) },
      ]);
    } finally {
      setSending(false);
    }
  }

  function loadMockReport() {
    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: "user", text: "[dev preview] Show September sales performance" },
      {
        id: nextId(),
        role: "assistant",
        text: MOCK_CHAT_RESPONSE.message,
        response: MOCK_CHAT_RESPONSE,
      },
    ]);
  }

  if (!started) {
    return (
      <div className="flex min-h-[calc(100vh-3.5rem)] flex-col items-center justify-center px-4">
        <div className="w-full max-w-2xl text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground">
            <Sparkles className="h-6 w-6" />
          </div>
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Insight BI</h1>
          <p className="mt-2 text-base text-muted-foreground">
            Ask anything about your business.
          </p>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
            className="mt-8 flex items-center gap-2 rounded-2xl border border-border bg-card p-2 shadow-sm"
          >
            <input
              autoFocus
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask anything about your business..."
              className="flex-1 bg-transparent px-3 py-2 text-sm outline-none placeholder:text-muted-foreground"
            />
            <Button type="submit" size="icon" disabled={sending || !input.trim()}>
              <Send className="h-4 w-4" />
            </Button>
          </form>

          <div className="mt-5 flex flex-wrap justify-center gap-2">
            {EXAMPLE_PROMPTS.map((p) => (
              <button
                key={p}
                onClick={() => setInput(p)}
                className="rounded-full border border-border bg-background px-3.5 py-1.5 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
              >
                {p}
              </button>
            ))}
          </div>

          {recommended.length > 0 && (
            <div className="mt-8">
              <p className="mb-3 flex items-center justify-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground/70">
                <LayoutList className="h-3.5 w-3.5" /> Recommended reports
              </p>
              <div className="flex flex-wrap justify-center gap-2">
                {recommended.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => handleRunRecommended(r.id)}
                    disabled={runningRecommended !== null}
                    title={r.description}
                    className="rounded-xl border border-border bg-card px-3.5 py-2 text-left text-xs shadow-sm transition-colors hover:border-primary/40 disabled:opacity-50"
                  >
                    <div className="font-medium">{r.title}</div>
                    <div className="mt-0.5 text-[11px] text-muted-foreground">{r.description}</div>
                  </button>
                ))}
              </div>
              <p className="mt-2 text-[11px] text-muted-foreground/60">
                Instant, pre-built reports — no AI needed.
              </p>
            </div>
          )}

          {process.env.NODE_ENV === "development" && (
            <button
              onClick={loadMockReport}
              className="mt-8 inline-flex items-center gap-1.5 rounded-md border border-dashed border-border px-2.5 py-1 text-[11px] text-muted-foreground/70 hover:text-muted-foreground"
              title="Dev-only: preview ReportCanvas with a mock response"
            >
              <FlaskConical className="h-3 w-3" /> Preview report fixture (dev only)
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">
      <div ref={scrollRef} className="flex-1 space-y-6 overflow-y-auto px-4 py-6 sm:px-8">
        <div className="mx-auto max-w-4xl space-y-6">
          {messages.map((m) => (
            <MessageBlock
              key={m.id}
              message={m}
              recommended={recommended}
              onRunRecommended={handleRunRecommended}
            />
          ))}
          {sending && <ThinkingIndicator />}
        </div>
      </div>

      <div className="border-t border-border bg-background/95 px-4 py-3 backdrop-blur sm:px-8">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
          className="mx-auto flex max-w-4xl items-center gap-2 rounded-2xl border border-border bg-card p-2 shadow-sm"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask anything about your business..."
            className="flex-1 bg-transparent px-3 py-2 text-sm outline-none placeholder:text-muted-foreground"
          />
          <Button type="submit" size="icon" disabled={sending || !input.trim()}>
            <Send className="h-4 w-4" />
          </Button>
        </form>
      </div>
    </div>
  );
}

function MessageBlock({
  message,
  recommended,
  onRunRecommended,
}: {
  message: ChatMessage;
  recommended: RecommendedReportSummary[];
  onRunRecommended: (id: string) => void;
}) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground">
          {message.text}
        </div>
      </div>
    );
  }

  const response = message.response;

  if (response?.error === "ai_disabled") {
    return <AiDisabledNotice recommended={recommended} onRunRecommended={onRunRecommended} />;
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-start">
        <div className="max-w-[85%] rounded-2xl rounded-bl-sm bg-muted px-4 py-2.5 text-sm">
          <p className="whitespace-pre-wrap">{message.text}</p>
        </div>
      </div>
      {response?.report && <ReportCanvas report={response.report} />}
    </div>
  );
}

function AiDisabledNotice({
  recommended,
  onRunRecommended,
}: {
  recommended: RecommendedReportSummary[];
  onRunRecommended: (id: string) => void;
}) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[95%] rounded-2xl border border-primary/15 bg-gradient-to-br from-primary/5 to-transparent px-5 py-4 sm:max-w-[70%]">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
            <KeyRound className="h-4 w-4" />
          </span>
          <p className="text-sm font-semibold">AI chat isn&apos;t configured yet</p>
        </div>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          Conversational analysis requires an OpenAI API key on the server. Once an{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">OPENAI_API_KEY</code> is
          configured, you&apos;ll be able to ask things like &ldquo;Show total revenue&rdquo; or
          &ldquo;Compare this month with last month&rdquo; and get a full report right here.
        </p>
        <p className="mt-2 text-xs text-muted-foreground/70">
          In the meantime, the Data explorer still works — browse real tables and preview rows.
        </p>
        {recommended.length > 0 && (
          <div className="mt-3 border-t border-border/60 pt-3">
            <p className="mb-2 text-xs font-medium text-muted-foreground">
              Or try one of these instant, pre-built reports (no AI needed):
            </p>
            <div className="flex flex-wrap gap-1.5">
              {recommended.map((r) => (
                <button
                  key={r.id}
                  onClick={() => onRunRecommended(r.id)}
                  title={r.description}
                  className="rounded-full border border-border bg-background px-3 py-1 text-xs transition-colors hover:border-primary/40"
                >
                  {r.title}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ThinkingIndicator() {
  // Chat runs as a background job that can genuinely take a while for a
  // complex multi-query question — swap in a reassuring message after a
  // few seconds so a long wait doesn't look like the UI is stuck.
  const [longWait, setLongWait] = React.useState(false);
  React.useEffect(() => {
    const timer = setTimeout(() => setLongWait(true), 6000);
    return () => clearTimeout(timer);
  }, []);

  return (
    <div className="flex justify-start">
      <div className="flex items-center gap-2 rounded-2xl rounded-bl-sm bg-muted px-4 py-3">
        <span className="flex gap-1">
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:-0.3s]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:-0.15s]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/60" />
        </span>
        <span className="text-xs text-muted-foreground">
          {longWait ? "Still working — running multiple queries for this one…" : "Analyzing your data…"}
        </span>
      </div>
    </div>
  );
}
