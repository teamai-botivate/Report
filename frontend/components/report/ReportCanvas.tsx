"use client";

import * as React from "react";
import {
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  Database,
  Code2,
  ImageDown,
  Download,
  FileSpreadsheet,
  CheckCircle2,
  AlertTriangle,
  Info,
  DollarSign,
  Percent,
  Hash,
  Type,
  ShieldAlert,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ChartRenderer } from "./ChartRenderer";
import { DataTableView } from "./DataTableView";
import { ViewDataDialog } from "./ViewDataDialog";
import { ViewQueryDialog } from "./ViewQueryDialog";
import { formatValue, cn } from "@/lib/utils";
import { exportCsv, exportExcel, downloadBlob } from "@/lib/api";
import { exportNodeToPng, slugify } from "@/lib/png-export";
import { useTheme } from "@/components/layout/ThemeProvider";
import { kpiAccentPalette } from "@/lib/chartTheme";
import type {
  ReportSpec,
  KPISpec,
  ChartSpec,
  TableSpec,
  InsightSpec,
} from "@/lib/types";

// Flattens every table's rows underneath this report into one array — used
// for the report-level "View Data" / "Export CSV" / "Export Excel" actions,
// which operate on the report's underlying rows as a whole (per-table export
// is also available inside each table block/the View Data dialog).
function collectReportRows(report: ReportSpec): Record<string, unknown>[] {
  const rows: Record<string, unknown>[] = [];
  for (const t of report.tables || []) rows.push(...t.rows);
  if (rows.length === 0) {
    for (const c of report.charts || []) rows.push(...c.data);
  }
  return rows;
}

export function ReportCanvas({ report }: { report: ReportSpec }) {
  const data = React.useMemo(() => collectReportRows(report), [report]);
  const queries = report.query_trace || [];
  const canvasRef = React.useRef<HTMLDivElement>(null);
  const [viewDataOpen, setViewDataOpen] = React.useState(false);
  const [viewQueryOpen, setViewQueryOpen] = React.useState(false);
  const [busy, setBusy] = React.useState<"csv" | "excel" | "png" | null>(null);

  const sections = React.useMemo(() => buildSections(report), [report]);

  // Shared category-name -> palette-index map across all charts in this
  // report, so a category like "North Region" resolves to the same color
  // whether it appears in a donut chart or a bar chart elsewhere in the same
  // report. Built once by walking each chart's own dimension field in
  // first-seen order — a simple, cheap, purely presentational lookup with no
  // data-flow changes; charts with no matching name simply fall back to
  // their own local index-based coloring (see colorForName in ChartRenderer).
  const categoryColorMap = React.useMemo(() => buildCategoryColorMap(report.charts || []), [report.charts]);

  const scrollToTop = React.useCallback(() => {
    canvasRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  async function handleDownloadImage() {
    if (!canvasRef.current) return;
    setBusy("png");
    try {
      await exportNodeToPng(canvasRef.current, `${slugify(report.title)}.png`);
    } catch (e) {
      console.error("Failed to render image", e);
    } finally {
      setBusy(null);
    }
  }

  async function handleExport(kind: "csv" | "excel") {
    setBusy(kind);
    try {
      const filename = `${slugify(report.title)}.${kind === "csv" ? "csv" : "xlsx"}`;
      const columns = data[0] ? Object.keys(data[0]) : undefined;
      const blob =
        kind === "csv" ? await exportCsv(data, columns) : await exportExcel(data, columns);
      downloadBlob(blob, filename);
    } catch (e) {
      console.error("Export failed", e);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="w-full">
      <div
        ref={canvasRef}
        className="rounded-2xl border border-border bg-card p-5 shadow-[0_1px_2px_rgba(0,0,0,0.04),0_8px_24px_-12px_rgba(0,0,0,0.10)] dark:shadow-[0_1px_2px_rgba(0,0,0,0.2),0_8px_24px_-12px_rgba(0,0,0,0.5)] sm:p-7"
      >
        <div className="mb-6">
          <h2 className="text-xl font-bold tracking-tight sm:text-2xl">{report.title}</h2>
          {report.subtitle && (
            <p className="mt-1 text-sm text-muted-foreground">{report.subtitle}</p>
          )}
        </div>

        {/* 2026-09-19 single-image revision: when the backend produced ONE
            AI-generated image for the whole report (title + KPIs + charts +
            tables + insights all composed together), render ONLY that image
            for the report body — no mixing with the per-section DOM layout.
            report_image_url is absent/null when image generation is disabled
            or failed, in which case the full multi-section ECharts/DOM
            layout below is rendered as the report-level fallback, exactly as
            it worked before this change. */}
        {report.report_image_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={report.report_image_url}
            alt={report.title}
            className="w-full rounded-xl border border-border object-contain"
          />
        ) : (
          <RenderSections sections={sections} onBackToTop={scrollToTop} categoryColorMap={categoryColorMap} />
        )}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={() => setViewDataOpen(true)}>
          <Database className="h-3.5 w-3.5" /> View Data
        </Button>
        <Button size="sm" variant="outline" onClick={() => setViewQueryOpen(true)}>
          <Code2 className="h-3.5 w-3.5" /> View Query
        </Button>
        <Button size="sm" variant="outline" disabled={busy !== null} onClick={handleDownloadImage}>
          <ImageDown className="h-3.5 w-3.5" /> {busy === "png" ? "Rendering…" : "Download Image"}
        </Button>
        <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => handleExport("csv")}>
          <Download className="h-3.5 w-3.5" /> {busy === "csv" ? "Exporting…" : "Export CSV"}
        </Button>
        <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => handleExport("excel")}>
          <FileSpreadsheet className="h-3.5 w-3.5" /> {busy === "excel" ? "Exporting…" : "Export Excel"}
        </Button>
      </div>

      <ViewDataDialog
        open={viewDataOpen}
        onOpenChange={setViewDataOpen}
        title={report.title}
        rows={data}
      />
      <ViewQueryDialog
        open={viewQueryOpen}
        onOpenChange={setViewQueryOpen}
        title={report.title}
        queries={queries}
      />
    </div>
  );
}

// ---- Section grouping / ordering ----

type Section =
  | { kind: "kpis"; items: KPISpec[] }
  | { kind: "chart"; item: ChartSpec }
  | { kind: "table"; item: TableSpec }
  | { kind: "insights"; items: InsightSpec[] };

// `layout` in ReportSpec is a loosely-typed `any[]` (backend hint for future
// use) rather than a strict ordering contract, so section order here is
// simply the natural KPIs -> charts -> tables -> insights grouping, which
// matches every real ReportSpec the Report Agent / heuristic fallback emit.
function buildSections(report: ReportSpec): Section[] {
  const hasKpis = report.kpis && report.kpis.length > 0;
  const hasInsights = report.insights && report.insights.length > 0;

  const sections: Section[] = [];
  if (hasKpis) sections.push({ kind: "kpis", items: report.kpis });
  for (const chart of report.charts || []) sections.push({ kind: "chart", item: chart });
  for (const table of report.tables || []) sections.push({ kind: "table", item: table });
  if (hasInsights) sections.push({ kind: "insights", items: report.insights });
  return sections;
}

function isWideChart(chart: ChartSpec): boolean {
  return (
    chart.type === "line" ||
    chart.type === "area" ||
    chart.type === "heatmap" ||
    (chart.data?.length ?? 0) > 8
  );
}

// Groups consecutive "chart" sections into a responsive grid (narrow charts
// pair up two-per-row, wide charts take the full row), while tables/kpis/
// insights render as their own full-width blocks in order.
function RenderSections({
  sections,
  onBackToTop,
  categoryColorMap,
}: {
  sections: Section[];
  onBackToTop: () => void;
  categoryColorMap: Map<string, number>;
}) {
  const nodes: React.ReactNode[] = [];
  let chartBuffer: ChartSpec[] = [];
  // A single running counter across charts+tables gives each "section card"
  // its own step through the accent cycle, independent of the KPI row's own
  // index-based cycle — so a report with 3 charts + 2 tables gets 5 distinct
  // accent-cycle positions across those cards, same idea as the KPI cards.
  let sectionAccentIndex = 0;

  const flushCharts = (keyPrefix: string) => {
    if (chartBuffer.length === 0) return;
    nodes.push(
      <div key={`${keyPrefix}-grid`} className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        {chartBuffer.map((chart) => {
          const accentIndex = sectionAccentIndex++;
          return (
            <div key={chart.id} className={cn(isWideChart(chart) && "lg:col-span-2")}>
              <ChartBlock chart={chart} accentIndex={accentIndex} categoryColorMap={categoryColorMap} />
            </div>
          );
        })}
      </div>
    );
    chartBuffer = [];
  };

  sections.forEach((section, i) => {
    if (section.kind === "chart") {
      chartBuffer.push(section.item);
      return;
    }
    flushCharts(`before-${i}`);
    if (section.kind === "kpis") nodes.push(<KpiRow key={i} kpis={section.items} />);
    else if (section.kind === "table")
      nodes.push(<TableBlock key={section.item.id} table={section.item} accentIndex={sectionAccentIndex++} />);
    else nodes.push(<InsightsBlock key={i} insights={section.items} onBackToTop={onBackToTop} />);
  });
  flushCharts("tail");

  return <>{nodes}</>;
}

// ---- KPI row ----

function KpiRow({ kpis }: { kpis: KPISpec[] }) {
  if (!kpis || kpis.length === 0) return null;
  return (
    <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {kpis.map((kpi, i) => (
        <KpiStat key={kpi.id} kpi={kpi} accentIndex={i} />
      ))}
    </div>
  );
}

// Simple case-insensitive keyword heuristic: risk-flavored KPI labels get an
// accent icon badge, independent of the trend direction (a down-trend isn't
// inherently "bad" — the delta pill already communicates direction).
const RISK_KEYWORDS = ["risk", "overdue", "delayed", "rejection", "churn", "default", "complaint"];

function isRiskLabel(label: string): boolean {
  const lower = label.toLowerCase();
  return RISK_KEYWORDS.some((kw) => lower.includes(kw));
}

function kpiIcon(format: KPISpec["format"], risky: boolean): React.ComponentType<{ className?: string }> {
  if (risky) return ShieldAlert;
  switch (format) {
    case "currency":
      return DollarSign;
    case "percentage":
      return Percent;
    case "number":
      return Hash;
    case "decimal":
      return Type;
    default:
      return Type;
  }
}

function KpiStat({ kpi, accentIndex }: { kpi: KPISpec; accentIndex: number }) {
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";

  const trendColor =
    kpi.trend === "up"
      ? "text-[#0ca30c] bg-[#0ca30c]/10"
      : kpi.trend === "down"
      ? "text-destructive bg-destructive/10"
      : "text-muted-foreground bg-muted";

  const TrendIcon = kpi.trend === "up" ? ArrowUpRight : kpi.trend === "down" ? ArrowDownRight : Minus;

  const risky = isRiskLabel(kpi.label);
  const Icon = kpiIcon(kpi.format, risky);

  // Risk-flagged KPIs always stay red/amber regardless of position — the
  // risk check takes priority over the deterministic accent cycle below.
  // Non-risk KPIs cycle through a small fixed semantic palette by their
  // position in the row (1st = blue, 2nd = purple, 3rd = teal, 4th = indigo,
  // 5th = amber, then repeats) — purely presentational, not derived from any
  // invented data field, and stable across re-renders/exports since it's a
  // pure function of index.
  const accentPalette = kpiAccentPalette(dark);
  const accent = accentPalette[accentIndex % accentPalette.length];
  const badgeStyle = risky
    ? undefined
    : { backgroundColor: accent.bg, color: accent.text };
  const badgeColor = risky ? "bg-destructive/10 text-destructive" : undefined;

  // Note: KPISpec.image_url (per-item AI image) is superseded by the
  // report-level report_image_url (see ReportCanvas above) and is no longer
  // populated by the backend, so this always renders the real numeric value.
  return (
    <div className="rounded-xl border border-border bg-background p-4 shadow-sm transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between gap-2">
        <p className="truncate text-xs font-medium text-muted-foreground">{kpi.label}</p>
        <span
          className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", badgeColor)}
          style={badgeStyle}
        >
          <Icon className="h-4.5 w-4.5" />
        </span>
      </div>
      <p className="mt-2.5 truncate text-2xl font-bold tabular-nums tracking-tight">
        {formatValue(kpi.value, kpi.format)}
      </p>
      {kpi.delta !== null && kpi.delta !== undefined && (
        <div className="mt-2 flex items-center gap-1.5">
          <span className={cn("flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-xs font-medium tabular-nums", trendColor)}>
            <TrendIcon className="h-3 w-3" />
            {Math.abs(kpi.delta).toFixed(1)}%
          </span>
          {kpi.delta_label && (
            <span className="truncate text-[11px] text-muted-foreground">{kpi.delta_label}</span>
          )}
        </div>
      )}
    </div>
  );
}

// ---- Charts ----

// Infers a value-format hint for axis/tooltip labels from the chart's first
// measure field name (e.g. "revenue" -> currency) — ChartSpec carries no
// explicit format field, so this is a conservative, presentation-only guess
// that only affects number formatting, never the underlying data.
function inferChartFormat(chart: ChartSpec): string | undefined {
  const measure = chart.y_field || chart.series[0]?.field;
  if (!measure) return undefined;
  const lower = measure.toLowerCase();
  if (/(revenue|amount|price|cost|value|sales|total|margin)/.test(lower)) return "currency";
  if (/(pct|percent|rate|ratio)/.test(lower)) return "percentage";
  return "number";
}

function ChartBlock({
  chart,
  accentIndex,
  categoryColorMap,
}: {
  chart: ChartSpec;
  accentIndex: number;
  categoryColorMap: Map<string, number>;
}) {
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";
  const palette = kpiAccentPalette(dark);
  const accent = palette[accentIndex % palette.length];

  // Multiple named series in ChartSpec.series pivot the chart by series
  // name when the data rows carry a shared dimension key per series; the
  // ECharts renderer falls back to its own per-measure heuristic otherwise.
  const seriesField =
    chart.series.length > 1 && chart.data[0] && "series" in (chart.data[0] as object)
      ? "series"
      : undefined;

  return (
    <div
      className="h-full rounded-xl border border-border bg-background p-4 pt-3.5 shadow-sm"
      style={{ borderTop: `3px solid ${accent.border}` }}
    >
      <div className="flex items-center gap-1.5">
        <span
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: accent.border }}
          aria-hidden
        />
        <p className="text-sm font-semibold">{chart.title}</p>
      </div>
      {chart.subtitle && <p className="pl-3.5 text-xs text-muted-foreground">{chart.subtitle}</p>}
      <div className="mt-2 h-72 w-full overflow-hidden rounded-lg">
        {/* Note: ChartSpec.image_url (per-item AI image) is superseded by
            the report-level report_image_url (see ReportCanvas above) and is
            no longer populated by the backend, so this always renders via
            ChartRenderer (ECharts). */}
        <ChartRenderer
          type={chart.type}
          data={chart.data || []}
          xField={chart.x_field}
          yField={chart.y_field}
          series={chart.series}
          seriesField={seriesField}
          format={inferChartFormat(chart)}
          categoryColorMap={categoryColorMap}
        />
      </div>
    </div>
  );
}

// ---- Tables ----

function TableBlock({ table, accentIndex }: { table: TableSpec; accentIndex: number }) {
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";
  const palette = kpiAccentPalette(dark);
  const accent = palette[accentIndex % palette.length];

  return (
    <div
      className="mb-4 rounded-xl border border-border bg-background p-4 pt-3.5 shadow-sm"
      style={{ borderTop: `3px solid ${accent.border}` }}
    >
      <div className="flex items-center gap-1.5">
        <span
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: accent.border }}
          aria-hidden
        />
        <p className="text-sm font-semibold">{table.title}</p>
      </div>
      <div className="mt-2 max-h-96 overflow-auto rounded-lg border border-border/70">
        {/* Note: TableSpec.image_url (per-item AI image) is superseded by
            the report-level report_image_url (see ReportCanvas above) and is
            no longer populated by the backend, so this always renders via
            DataTableView. */}
        <DataTableView
          data={table.rows}
          columns={table.columns.map((c) => c.field)}
        />
      </div>
    </div>
  );
}

// ---- Insights ----
// "Action Center" style presentation built from InsightSpec's {text, kind}
// shape: kind maps to a priority badge, and headline-kind insights (or the
// single most severe insight when none is flagged headline) get a
// highlighted callout.

const KIND_STYLES: Record<
  InsightSpec["kind"],
  {
    icon: React.ComponentType<{ className?: string }>;
    iconColor: string;
    badgeClass: string;
    priorityLabel: string;
    rank: number;
  }
> = {
  warning: {
    icon: AlertTriangle,
    iconColor: "text-[#b57900]",
    badgeClass: "bg-[#fab219]/15 text-[#b57900]",
    priorityLabel: "Warning",
    rank: 0,
  },
  headline: {
    icon: CheckCircle2,
    iconColor: "text-[#0ca30c]",
    badgeClass: "bg-[#0ca30c]/10 text-[#0ca30c]",
    priorityLabel: "Headline",
    rank: 1,
  },
  note: {
    icon: Info,
    iconColor: "text-muted-foreground",
    badgeClass: "bg-muted text-muted-foreground",
    priorityLabel: "Note",
    rank: 2,
  },
};

function InsightsBlock({
  insights,
  onBackToTop,
}: {
  insights: InsightSpec[];
  onBackToTop: () => void;
}) {
  if (!insights || insights.length === 0) return null;

  // Headline callout: prefer an insight explicitly flagged "headline";
  // otherwise fall back to the single most severe insight (lowest rank).
  const headlineIndex = insights.reduce((bestIdx, insight, i) => {
    const rank = (KIND_STYLES[insight.kind] || KIND_STYLES.note).rank;
    const bestRank = (KIND_STYLES[insights[bestIdx].kind] || KIND_STYLES.note).rank;
    return rank < bestRank ? i : bestIdx;
  }, 0);
  const headline = insights[headlineIndex];
  const headlineStyle = KIND_STYLES[headline.kind] || KIND_STYLES.note;
  const HeadlineIcon = headlineStyle.icon;

  return (
    <div className="mt-2 rounded-2xl border border-border bg-background p-4 shadow-sm">
      <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Insights &amp; Actions
      </p>

      <div className="divide-y divide-border/60">
        {insights.map((insight) => {
          const style = KIND_STYLES[insight.kind] || KIND_STYLES.note;
          const Icon = style.icon;
          return (
            <div key={insight.id} className="flex items-start gap-3 py-2.5 first:pt-0 last:pb-0">
              <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", style.iconColor)} />
              <p className="flex-1 text-sm text-foreground/90">{insight.text}</p>
              <span
                className={cn(
                  "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                  style.badgeClass
                )}
              >
                {style.priorityLabel}
              </span>
            </div>
          );
        })}
      </div>

      <div
        className={cn(
          "mt-3 flex items-start gap-2 rounded-xl px-3 py-2.5 text-sm",
          headline.kind === "warning" && "bg-[#fab219]/15",
          headline.kind === "headline" && "bg-[#0ca30c]/10",
          headline.kind === "note" && "bg-muted"
        )}
      >
        <HeadlineIcon className={cn("mt-0.5 h-4 w-4 shrink-0", headlineStyle.iconColor)} />
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Headline
          </p>
          <p className="mt-0.5 font-medium text-foreground">{headline.text}</p>
        </div>
      </div>

      <div className="mt-3 flex justify-end">
        <button
          type="button"
          onClick={onBackToTop}
          className="text-xs font-medium text-primary transition-colors hover:text-primary/80 hover:underline"
        >
          Back to top ↑
        </button>
      </div>
    </div>
  );
}

// ---- Cross-chart color consistency ----

// Walks each chart's own dimension field (x_field, falling back to the first
// non-numeric column — same resolution ChartRenderer's pickDimAndMeasure
// does locally) in chart order, assigning each newly-seen category/series
// name the next palette index in first-seen order. This gives a name like
// "North" the same color wherever it recurs across charts in one report,
// without needing to know anything about what the name means.
function buildCategoryColorMap(charts: ChartSpec[]): Map<string, number> {
  const map = new Map<string, number>();
  let nextIndex = 0;
  for (const chart of charts) {
    const rows = chart.data || [];
    if (rows.length === 0) continue;
    const sample = rows[0] as Record<string, unknown>;
    const dimKey =
      chart.x_field ||
      Object.keys(sample).find((k) => Number.isNaN(Number(sample[k]))) ||
      Object.keys(sample)[0];
    if (!dimKey) continue;
    for (const row of rows) {
      const name = String((row as Record<string, unknown>)[dimKey] ?? "");
      if (!name || map.has(name)) continue;
      map.set(name, nextIndex++);
    }
  }
  return map;
}
