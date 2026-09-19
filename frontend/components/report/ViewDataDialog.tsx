"use client";

import * as React from "react";
import { Download, FileSpreadsheet } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { DataTableView } from "./DataTableView";
import { exportCsv, exportExcel, downloadBlob } from "@/lib/api";

export function ViewDataDialog({
  open,
  onOpenChange,
  title,
  rows,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  rows: Record<string, unknown>[];
}) {
  const [busy, setBusy] = React.useState<"csv" | "excel" | null>(null);
  const columns = rows[0] ? Object.keys(rows[0]) : [];

  async function handleExport(kind: "csv" | "excel") {
    setBusy(kind);
    try {
      const filename = `${title.replace(/\s+/g, "_").toLowerCase()}.${kind === "csv" ? "csv" : "xlsx"}`;
      const blob =
        kind === "csv" ? await exportCsv(rows, columns) : await exportExcel(rows, columns);
      downloadBlob(blob, filename);
    } catch (e) {
      console.error("Export failed", e);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{title} — Data Preview</DialogTitle>
          <DialogDescription>
            {rows.length} row{rows.length === 1 ? "" : "s"} · {columns.length} column
            {columns.length === 1 ? "" : "s"}
          </DialogDescription>
        </DialogHeader>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={busy !== null || rows.length === 0}
            onClick={() => handleExport("csv")}
          >
            <Download className="h-4 w-4" /> {busy === "csv" ? "Exporting…" : "Export CSV"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={busy !== null || rows.length === 0}
            onClick={() => handleExport("excel")}
          >
            <FileSpreadsheet className="h-4 w-4" /> {busy === "excel" ? "Exporting…" : "Export Excel"}
          </Button>
        </div>
        <div className="max-h-[55vh] overflow-auto rounded-md border border-border">
          <DataTableView data={rows} />
        </div>
      </DialogContent>
    </Dialog>
  );
}
