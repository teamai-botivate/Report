import axios, { AxiosInstance } from "axios";
import type {
  ChatResponse,
  JobEnqueueResponse,
  JobStatusResponse,
  SchemaResponse,
  DataPreviewResponse,
  RecommendedReportSummary,
  HealthResponse,
} from "./types";

// Empty string means "same origin" (used in the single-container Render/
// Docker deployment, where FastAPI serves the frontend and /api/* from the
// same host:port). Only fall back to localhost:8000 when the env var is
// genuinely unset (local dev running frontend/backend as separate processes).
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL !== undefined
    ? process.env.NEXT_PUBLIC_API_URL
    : "http://localhost:8000";

const client: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
});

// ---- Health / schema ----

export async function getHealth(): Promise<HealthResponse> {
  const { data } = await client.get<HealthResponse>("/api/health");
  return data;
}

export async function getSchema(): Promise<SchemaResponse> {
  const { data } = await client.get<SchemaResponse>("/api/schema");
  return data;
}

// ---- Chat ----
//
// A chat turn can involve several sequential OpenAI calls (intent
// classification, query planning, one SQL-generation call per query node,
// report composition, explanation) plus real database queries — a real
// multi-query question logged 6 OpenAI calls before returning, long enough
// that a hosting proxy (Render's included) can drop the connection before a
// single blocking request completes, independent of any client-side timeout.
// So the backend runs a chat turn as a background job: POST /api/chat
// returns a job_id almost immediately, and this function polls
// GET /api/chat/jobs/{job_id} until it's done. Callers just
// `await postChat(message, conversationId)` and get a Promise<ChatResponse> —
// polling is an internal implementation detail.
//
// 2026-09-19: a report turn generates ONE gpt-image-2 image for the whole
// report (app/ai/chart_image_client.py's generate_full_report_image),
// replacing an earlier same-day approach that generated one image per
// KPI/chart/table (which needed several bounded-concurrency batches at
// ~10-20s each and had pushed this budget up to ~6 minutes). A single
// prompt-writing call plus a single image-generation call is still slower
// than plain text but no longer scales with the number of report sections,
// so the budget is brought back down — kept a bit above the original
// ~3-minute pre-image budget rather than exactly at it, since one big
// whole-report prompt is more data (and likely somewhat slower to write and
// render) than the plain-text-only case that budget was originally sized for.
const CHAT_POLL_INTERVAL_MS = 1500;
const CHAT_POLL_TIMEOUT_MS = 240000; // ~4 minutes overall budget

export class ChatTimeoutError extends Error {
  constructor() {
    super("Chat job did not finish in time");
    this.name = "ChatTimeoutError";
  }
}

export class ChatJobError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ChatJobError";
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function postChat(
  message: string,
  conversationId?: string
): Promise<ChatResponse> {
  const { data: created } = await client.post<JobEnqueueResponse>("/api/chat", {
    message,
    conversation_id: conversationId,
  });

  const deadline = Date.now() + CHAT_POLL_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const { data: job } = await client.get<JobStatusResponse>(
      `/api/chat/jobs/${created.job_id}`
    );
    if (job.status === "done" && job.result) {
      return job.result;
    }
    if (job.status === "error") {
      throw new ChatJobError(job.error || "The AI service failed to process this request.");
    }
    await sleep(CHAT_POLL_INTERVAL_MS);
  }
  throw new ChatTimeoutError();
}

// ---- Recommended reports (fixed SQL, no LLM call — work even with AI disabled) ----

export async function getRecommended(): Promise<RecommendedReportSummary[]> {
  const { data } = await client.get<RecommendedReportSummary[]>("/api/recommended");
  return data;
}

export async function runRecommended(id: string): Promise<ChatResponse> {
  const { data } = await client.post<ChatResponse>(`/api/recommended/${id}/run`);
  return data;
}

// ---- Export ----

export async function exportCsv(
  rows: Record<string, unknown>[],
  columns?: string[]
): Promise<Blob> {
  const { data } = await client.post(
    "/api/export/csv",
    { rows, columns },
    { responseType: "blob" }
  );
  return data;
}

export async function exportExcel(
  rows: Record<string, unknown>[],
  columns?: string[]
): Promise<Blob> {
  const { data } = await client.post(
    "/api/export/excel",
    { rows, columns },
    { responseType: "blob" }
  );
  return data;
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

// ---- Data explorer ----

export async function getDataPreview(
  table: string,
  limit = 50
): Promise<DataPreviewResponse> {
  const { data } = await client.get<DataPreviewResponse>("/api/data/preview", {
    params: { table, limit },
  });
  return data;
}

export default client;
