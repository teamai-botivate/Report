"use client";

import * as React from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import type { QueryTraceSpec } from "@/lib/types";

export function ViewQueryDialog({
  open,
  onOpenChange,
  title,
  queries,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  queries?: QueryTraceSpec[];
}) {
  const hasTrace = queries && queries.length > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title} — Query</DialogTitle>
          <DialogDescription>
            Traceability details for the SQL behind this report — table names, row
            counts, and timing, not raw model reasoning.
          </DialogDescription>
        </DialogHeader>

        {hasTrace ? (
          <div className="max-h-[60vh] space-y-4 overflow-auto">
            {queries!.map((q) => (
              <div key={q.node_id} className="rounded-md border border-border p-3">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">{q.description}</span>
                  <Badge variant={q.status === "success" ? "success" : "destructive"}>
                    {q.status}
                  </Badge>
                  <span className="text-xs text-muted-foreground">{q.row_count} rows</span>
                  <span className="text-xs text-muted-foreground">{q.elapsed_ms}ms</span>
                </div>
                <pre className="max-h-48 overflow-auto rounded bg-muted p-2 text-xs">
                  {q.sql}
                </pre>
                {q.tables?.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {q.tables.map((t) => (
                      <Badge key={t} variant="outline">
                        {t}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No query trace available for this report.
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}
