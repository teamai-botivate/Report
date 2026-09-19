"use client";

import * as React from "react";
import {
  Download,
  FileSpreadsheet,
  Database,
  KeyRound,
  Link2,
  WifiOff,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { DataTableView } from "@/components/report/DataTableView";
import { getSchema, getDataPreview, exportCsv, exportExcel, downloadBlob } from "@/lib/api";
import type { SchemaTable, DataPreviewResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;

export default function DataExplorerPage() {
  const [tables, setTables] = React.useState<SchemaTable[]>([]);
  const [tablesLoading, setTablesLoading] = React.useState(true);
  const [tablesError, setTablesError] = React.useState<string | null>(null);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [preview, setPreview] = React.useState<DataPreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = React.useState(false);
  const [previewError, setPreviewError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState<"csv" | "excel" | null>(null);

  React.useEffect(() => {
    getSchema()
      .then((res) => {
        const list = res || [];
        setTables(list);
        if (list.length > 0) setSelected(list[0].table);
      })
      .catch((e) =>
        setTablesError(
          e instanceof Error ? e.message : "Backend not reachable — could not load schema."
        )
      )
      .finally(() => setTablesLoading(false));
  }, []);

  React.useEffect(() => {
    if (!selected) return;
    setPreviewLoading(true);
    setPreviewError(null);
    getDataPreview(selected, PAGE_SIZE)
      .then(setPreview)
      .catch((e) =>
        setPreviewError(e instanceof Error ? e.message : "Failed to load preview")
      )
      .finally(() => setPreviewLoading(false));
  }, [selected]);

  const selectedSchema = selected ? tables.find((t) => t.table === selected) : undefined;
  const relationships = React.useMemo(() => {
    if (!selectedSchema) return [];
    return selectedSchema.columns.filter((c) => c.is_fk && c.references);
  }, [selectedSchema]);

  async function handleExport(kind: "csv" | "excel") {
    if (!preview) return;
    setBusy(kind);
    try {
      const filename = `${selected}.${kind === "csv" ? "csv" : "xlsx"}`;
      const blob =
        kind === "csv"
          ? await exportCsv(preview.rows, preview.columns)
          : await exportExcel(preview.rows, preview.columns);
      downloadBlob(blob, filename);
    } finally {
      setBusy(null);
    }
  }

  if (tablesError) {
    return (
      <div className="flex h-[calc(100vh-3.5rem)] flex-col items-center justify-center gap-3 px-4 text-center">
        <WifiOff className="h-8 w-8 text-muted-foreground" />
        <p className="text-sm font-semibold">Backend not reachable</p>
        <p className="max-w-sm text-xs text-muted-foreground">
          Couldn&apos;t load the schema from the API. Make sure the backend is running and
          <code className="mx-1 rounded bg-muted px-1 py-0.5">NEXT_PUBLIC_API_URL</code>
          points at it, then reload this page.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">
      <div className="border-b border-border px-6 py-4">
        <h1 className="text-lg font-semibold">Data Explorer</h1>
        <p className="text-sm text-muted-foreground">
          Browse tables, columns, and relationships from the live schema. Read-only.
        </p>
      </div>

      <div className="flex flex-1 gap-4 overflow-hidden p-4">
        <aside className="w-72 shrink-0 overflow-y-auto rounded-lg border border-border bg-card p-2 scrollbar-thin">
          {tablesLoading && (
            <div className="space-y-2 p-2">
              {[...Array(8)].map((_, i) => (
                <Skeleton key={i} className="h-6 w-full" />
              ))}
            </div>
          )}
          {!tablesLoading && tables.length === 0 && (
            <p className="p-2 text-xs text-muted-foreground">No tables found.</p>
          )}
          {tables.map((t) => (
            <button
              key={t.table}
              onClick={() => setSelected(t.table)}
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent",
                selected === t.table && "bg-primary/10 text-primary"
              )}
            >
              <Database className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">{t.table}</span>
            </button>
          ))}
        </aside>

        <section className="flex-1 overflow-hidden rounded-lg border border-border bg-card">
          {!selected && (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              Select a table to explore
            </div>
          )}
          {selected && (
            <div className="flex h-full flex-col">
              <div className="flex items-center justify-between border-b border-border p-4">
                <div>
                  <p className="text-sm font-semibold">{selected}</p>
                  {preview && (
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {preview.total_count} rows · {preview.columns.length} columns
                    </p>
                  )}
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy !== null || !preview}
                    onClick={() => handleExport("csv")}
                  >
                    <Download className="h-4 w-4" /> CSV
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy !== null || !preview}
                    onClick={() => handleExport("excel")}
                  >
                    <FileSpreadsheet className="h-4 w-4" /> Excel
                  </Button>
                </div>
              </div>

              <Tabs defaultValue="preview" className="flex flex-1 flex-col overflow-hidden">
                <TabsList className="mx-4 mt-3 w-fit">
                  <TabsTrigger value="preview">Data Preview</TabsTrigger>
                  <TabsTrigger value="columns">Columns</TabsTrigger>
                  <TabsTrigger value="relationships">Relationships</TabsTrigger>
                </TabsList>

                <TabsContent value="preview" className="flex-1 overflow-auto">
                  {previewLoading && (
                    <div className="space-y-2 p-4">
                      {[...Array(10)].map((_, i) => (
                        <Skeleton key={i} className="h-6 w-full" />
                      ))}
                    </div>
                  )}
                  {previewError && (
                    <p className="p-4 text-sm text-destructive">{previewError}</p>
                  )}
                  {!previewLoading && !previewError && preview && (
                    <>
                      <DataTableView data={preview.rows} columns={preview.columns} />
                      <p className="border-t border-border p-3 text-xs text-muted-foreground">
                        Showing {preview.row_count} of {preview.total_count} rows
                      </p>
                    </>
                  )}
                </TabsContent>

                <TabsContent value="columns" className="flex-1 overflow-auto p-4">
                  {!selectedSchema && (
                    <p className="text-sm text-muted-foreground">No schema information available.</p>
                  )}
                  {selectedSchema && (
                    <div className="space-y-2">
                      {selectedSchema.columns.map((c) => (
                        <div
                          key={c.name}
                          className="flex items-start justify-between gap-3 rounded-md border border-border p-3"
                        >
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="font-mono text-sm font-medium">{c.name}</span>
                              {c.is_pk && (
                                <Badge variant="outline" className="gap-1">
                                  <KeyRound className="h-3 w-3" /> PK
                                </Badge>
                              )}
                              {c.is_fk && (
                                <Badge variant="outline" className="gap-1">
                                  <Link2 className="h-3 w-3" /> FK
                                </Badge>
                              )}
                            </div>
                          </div>
                          <Badge variant="outline" className="shrink-0 font-mono">
                            {c.type}
                          </Badge>
                        </div>
                      ))}
                    </div>
                  )}
                </TabsContent>

                <TabsContent value="relationships" className="flex-1 overflow-auto p-4">
                  {relationships.length === 0 && (
                    <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                      <div className="text-center">
                        <Link2 className="mx-auto mb-2 h-6 w-6 text-muted-foreground/50" />
                        No foreign key relationships on this table.
                      </div>
                    </div>
                  )}
                  {relationships.length > 0 && (
                    <div className="space-y-2">
                      {relationships.map((c) => (
                        <div
                          key={c.name}
                          className="flex items-center gap-3 rounded-md border border-border p-3 text-sm"
                        >
                          <span className="font-mono font-medium">
                            {selected}.{c.name}
                          </span>
                          <Link2 className="h-4 w-4 shrink-0 text-muted-foreground" />
                          <span className="font-mono font-medium text-primary">{c.references}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </TabsContent>
              </Tabs>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
