"use client";

import * as React from "react";
import { ArrowUpRight, ArrowDownRight } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatValue, isNumeric, cn } from "@/lib/utils";

// Columns whose name suggests a growth/change metric get a small inline
// up/down arrow colored by the sign of the (already-displayed, real) cell
// value — a presentational read of data already in the row, not a fabricated
// figure. Conservative: only triggers on a name match, everything else is
// unaffected.
const GROWTH_COLUMN_PATTERN = /growth|change|delta|trend/i;

function isGrowthColumn(name: string): boolean {
  return GROWTH_COLUMN_PATTERN.test(name);
}

export function DataTableView({
  data,
  columns: columnsProp,
  format,
  highlightColumn,
  maxRows,
}: {
  data: Record<string, unknown>[];
  columns?: string[];
  format?: string;
  highlightColumn?: string;
  maxRows?: number;
}) {
  if (!data || data.length === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-xs text-muted-foreground">No data</p>
      </div>
    );
  }

  const columns = columnsProp && columnsProp.length > 0 ? columnsProp : Object.keys(data[0]);
  const rows = maxRows ? data.slice(0, maxRows) : data;

  // When the highlighted column is numeric, compute a compact share-of-total
  // sub-value per row (value / column sum * 100) — a real client-side
  // derived calculation from the already-displayed data, not fabricated.
  const highlightIsNumeric =
    !!highlightColumn && rows.length > 0 && rows.every((r) => isNumeric(r[highlightColumn]));
  const highlightSum = highlightIsNumeric
    ? rows.reduce((sum, r) => sum + (Number(r[highlightColumn as string]) || 0), 0)
    : 0;

  return (
    <div className="h-full overflow-auto scrollbar-thin">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            {columns.map((c) => {
              const numericCol = isNumeric(rows[0]?.[c]);
              return (
                <TableHead
                  key={c}
                  className={cn(
                    numericCol && "text-right",
                    c === highlightColumn && "bg-primary/5 font-semibold text-foreground"
                  )}
                >
                  {c.replace(/_/g, " ")}
                </TableHead>
              );
            })}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, i) => (
            <TableRow key={i} className="border-border/50">
              {columns.map((c) => {
                const val = row[c];
                const numeric = isNumeric(val);
                const isHighlighted = c === highlightColumn;
                const share =
                  isHighlighted && highlightIsNumeric && highlightSum > 0
                    ? ((Number(val) || 0) / highlightSum) * 100
                    : null;
                const growthCol = numeric && isGrowthColumn(c);
                const growthValue = growthCol ? Number(val) || 0 : 0;
                return (
                  <TableCell
                    key={c}
                    className={cn(
                      numeric && "text-right tabular-nums",
                      isHighlighted && "bg-primary/5 font-semibold text-foreground"
                    )}
                  >
                    {growthCol ? (
                      <span
                        className={cn(
                          "inline-flex items-center justify-end gap-0.5",
                          growthValue > 0 && "text-[#0ca30c]",
                          growthValue < 0 && "text-destructive"
                        )}
                      >
                        {growthValue > 0 && <ArrowUpRight className="h-3 w-3 shrink-0" />}
                        {growthValue < 0 && <ArrowDownRight className="h-3 w-3 shrink-0" />}
                        {formatValue(val, format)}
                      </span>
                    ) : numeric ? (
                      formatValue(val, format)
                    ) : (
                      String(val ?? "—")
                    )}
                    {share !== null && (
                      <span className="ml-1.5 block text-[10px] font-normal text-muted-foreground">
                        {share.toFixed(1)}% of total
                      </span>
                    )}
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
