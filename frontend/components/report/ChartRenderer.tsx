"use client";

import * as React from "react";
import ReactECharts from "echarts-for-react";
import { useTheme } from "@/components/layout/ThemeProvider";
import { categoricalPalette, chartChrome } from "@/lib/chartTheme";
import { formatValue, isNumeric } from "@/lib/utils";
import type { ChartType, ChartSeriesSpec } from "@/lib/types";

export interface ChartRendererProps {
  type: ChartType | string;
  data: Record<string, unknown>[];
  xField?: string | null;
  yField?: string | null;
  series?: ChartSeriesSpec[];
  // Dimension field used to pivot rows into multiple named series (e.g.
  // region names becoming separate lines/bars). Distinct from `series`
  // above (the ChartSpec.series list of {name, field} measure labels).
  seriesField?: string;
  format?: "currency" | "percentage" | "number" | "decimal" | string;
  height?: number | string;
  // Optional report-level map of category/series name -> palette index, so
  // the same category name (e.g. "North Region") resolves to the same color
  // across different charts in the same report instead of each chart
  // independently assigning colors by its own local data order. Purely a
  // presentational lookup — falls back to local index-based coloring for any
  // name not present in the map (e.g. single-chart reports, where this prop
  // is simply omitted).
  categoryColorMap?: Map<string, number>;
}

function pickDimAndMeasure(
  data: Record<string, unknown>[],
  xField?: string | null,
  yField?: string | null,
  series?: ChartSeriesSpec[]
): { dimKey: string; measureKeys: string[] } {
  const sample = data[0] || {};
  const keys = Object.keys(sample);

  let dimKey = xField || undefined;
  let measureKeys: string[] | undefined =
    series && series.length > 0
      ? series.map((s) => s.field).filter((f) => keys.includes(f))
      : yField
      ? [yField]
      : undefined;

  if (!dimKey) {
    dimKey = keys.find((k) => !isNumeric(sample[k])) || keys[0];
  }
  if (!measureKeys || measureKeys.length === 0) {
    measureKeys = keys.filter((k) => k !== dimKey && isNumeric(sample[k]));
    if (measureKeys.length === 0 && keys.length > 1) measureKeys = [keys[1]];
  }
  return { dimKey: dimKey || keys[0], measureKeys: measureKeys || [] };
}

function baseTooltip(dark: boolean) {
  const c = chartChrome(dark);
  return {
    trigger: "axis" as const,
    backgroundColor: dark ? "#232322" : "#ffffff",
    borderColor: c.gridline,
    textStyle: { color: c.textPrimary, fontSize: 12 },
    axisPointer: { type: "shadow" as const },
  };
}

// Builds a { seriesName -> value }[] pivot when a seriesField is present,
// e.g. turning [{month, region, revenue}] rows into per-region series lines.
function pivotBySeries(
  data: Record<string, unknown>[],
  dimKey: string,
  seriesField: string,
  measureKey: string
): { categories: string[]; seriesNames: string[]; matrix: number[][] } {
  const categories = Array.from(new Set(data.map((r) => String(r[dimKey] ?? ""))));
  const seriesNames = Array.from(new Set(data.map((r) => String(r[seriesField] ?? ""))));
  const lookup = new Map<string, number>();
  for (const r of data) {
    lookup.set(`${String(r[dimKey])}::${String(r[seriesField])}`, Number(r[measureKey]) || 0);
  }
  const matrix = seriesNames.map((s) => categories.map((c) => lookup.get(`${c}::${s}`) ?? 0));
  return { categories, seriesNames, matrix };
}

// Resolves a stable color for a named category/series: prefers the
// report-level shared map (so the same name gets the same color across
// different charts in one report), falling back to the chart-local index
// when the name isn't in the map (or no map was supplied at all).
function colorForName(
  name: string,
  localIndex: number,
  palette: string[],
  map: Map<string, number> | undefined
): string {
  const idx = map?.has(name) ? map.get(name)! : localIndex;
  return palette[idx % palette.length];
}

function buildOption(
  type: string,
  data: Record<string, unknown>[],
  xField: string | undefined | null,
  yField: string | undefined | null,
  seriesField: string | undefined,
  series: ChartSeriesSpec[] | undefined,
  format: string | undefined,
  dark: boolean,
  categoryColorMap?: Map<string, number>
): Record<string, unknown> {
  const palette = categoricalPalette(dark);
  const c = chartChrome(dark);
  const { dimKey, measureKeys } = pickDimAndMeasure(data, xField, yField, series);
  const categories = data.map((r) => String(r[dimKey] ?? ""));

  const axisLabelFormatter = (v: number | string) => formatValue(v, format);

  const useSeriesPivot =
    !!seriesField && (type === "line" || type === "area" || type === "bar");

  const commonGrid = { left: 8, right: 16, top: 40, bottom: 8, containLabel: true };
  // Clean dot + label legend chips above the chart instead of ECharts'
  // default boxed legend swatches.
  const legend = {
    show: true,
    top: 0,
    icon: "circle" as const,
    itemWidth: 8,
    itemHeight: 8,
    itemGap: 18,
    textStyle: { color: c.textSecondary, fontSize: 11.5, fontWeight: 500 },
  };

  if (useSeriesPivot && seriesField) {
    const measure = measureKeys[0];
    const { categories: cats, seriesNames, matrix } = pivotBySeries(data, dimKey, seriesField, measure);
    const stack = undefined;
    const isLine = type === "line" || type === "area";

    return {
      color: palette,
      tooltip: baseTooltip(dark),
      legend,
      grid: commonGrid,
      xAxis: {
        type: "category",
        data: cats,
        axisLine: { lineStyle: { color: c.baseline } },
        axisLabel: { color: c.textSecondary, fontSize: 11 },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: c.gridline } },
        axisLabel: { color: c.textSecondary, fontSize: 11, formatter: axisLabelFormatter },
      },
      series: seriesNames.map((name, i) => {
        const color = colorForName(name, i, palette, categoryColorMap);
        return {
          name,
          type: isLine ? "line" : "bar",
          stack,
          smooth: false,
          symbol: "circle",
          symbolSize: 6,
          showSymbol: cats.length <= 30,
          lineStyle: isLine ? { width: 2, color } : undefined,
          areaStyle: type === "area" ? { opacity: 0.15, color } : undefined,
          itemStyle: { color, borderRadius: !isLine && !stack ? [4, 4, 0, 0] : undefined },
          barMaxWidth: 28,
          data: matrix[i],
        };
      }),
    };
  }

  switch (type) {
    case "bar": {
      const barMaxWidth = categories.length <= 4 ? 56 : categories.length <= 10 ? 40 : 26;
      return {
        color: palette,
        tooltip: baseTooltip(dark),
        legend: measureKeys.length > 1 ? legend : undefined,
        grid: measureKeys.length > 1 ? commonGrid : { ...commonGrid, top: 16 },
        xAxis: {
          type: "category",
          data: categories,
          axisLine: { lineStyle: { color: c.baseline } },
          axisLabel: { color: c.textSecondary, fontSize: 11 },
        },
        yAxis: {
          type: "value",
          splitLine: { lineStyle: { color: c.gridline } },
          axisLabel: { color: c.textSecondary, fontSize: 11, formatter: axisLabelFormatter },
        },
        series: measureKeys.map((m, i) => ({
          name: m,
          type: "bar",
          data: data.map((r) => Number(r[m]) || 0),
          itemStyle: { color: palette[i % palette.length], borderRadius: [6, 6, 0, 0] },
          barMaxWidth,
        })),
      };
    }
    case "horizontal_bar": {
      const barMaxWidth = categories.length <= 4 ? 32 : categories.length <= 10 ? 24 : 16;
      return {
        color: palette,
        tooltip: baseTooltip(dark),
        legend: measureKeys.length > 1 ? legend : undefined,
        grid: measureKeys.length > 1 ? commonGrid : { ...commonGrid, top: 16 },
        yAxis: {
          type: "category",
          data: categories,
          axisLine: { lineStyle: { color: c.baseline } },
          axisLabel: { color: c.textSecondary, fontSize: 11 },
        },
        xAxis: {
          type: "value",
          splitLine: { lineStyle: { color: c.gridline } },
          axisLabel: { color: c.textSecondary, fontSize: 11, formatter: axisLabelFormatter },
        },
        series: measureKeys.map((m, i) => ({
          name: m,
          type: "bar",
          data: data.map((r) => Number(r[m]) || 0),
          itemStyle: { color: palette[i % palette.length], borderRadius: [0, 6, 6, 0] },
          barMaxWidth,
        })),
      };
    }
    case "line":
    case "area": {
      return {
        color: palette,
        tooltip: { ...baseTooltip(dark), trigger: "axis", axisPointer: { type: "line" } },
        legend: measureKeys.length > 1 ? legend : undefined,
        grid: measureKeys.length > 1 ? commonGrid : { ...commonGrid, top: 16 },
        xAxis: {
          type: "category",
          data: categories,
          boundaryGap: false,
          axisLine: { lineStyle: { color: c.baseline } },
          axisLabel: { color: c.textSecondary, fontSize: 11 },
        },
        yAxis: {
          type: "value",
          splitLine: { lineStyle: { color: c.gridline } },
          axisLabel: { color: c.textSecondary, fontSize: 11, formatter: axisLabelFormatter },
        },
        series: measureKeys.map((m, i) => ({
          name: m,
          type: "line",
          smooth: 0.25,
          symbol: "circle",
          symbolSize: 6,
          showSymbol: data.length <= 30,
          lineStyle: { width: 2.5, color: palette[i % palette.length] },
          itemStyle: { color: palette[i % palette.length], borderWidth: 2, borderColor: c.surface },
          areaStyle:
            type === "area"
              ? {
                  color: {
                    type: "linear",
                    x: 0,
                    y: 0,
                    x2: 0,
                    y2: 1,
                    colorStops: [
                      { offset: 0, color: `${palette[i % palette.length]}33` },
                      { offset: 1, color: `${palette[i % palette.length]}03` },
                    ],
                  },
                }
              : undefined,
          data: data.map((r) => Number(r[m]) || 0),
        })),
      };
    }
    case "pie":
    case "donut": {
      const measure = measureKeys[0];
      const values = data.map((r) => Number(r[measure]) || 0);
      const total = values.reduce((a, b) => a + b, 0);
      const isDonut = type === "donut";
      // Native ECharts graphic center label (not an HTML overlay) so the
      // "Download Image" toPng export renders it correctly without any risk
      // of clipping/misalignment.
      const centerGraphic = isDonut
        ? [
            {
              type: "text" as const,
              left: "23.5%",
              top: "46%",
              style: {
                text: formatValue(total, format),
                textAlign: "center" as const,
                fill: c.textPrimary,
                fontSize: 22,
                fontWeight: 700,
              },
            },
            {
              type: "text" as const,
              left: "23.5%",
              top: "56%",
              style: {
                text: "Total",
                textAlign: "center" as const,
                fill: c.textSecondary,
                fontSize: 11,
                fontWeight: 500,
              },
            },
          ]
        : undefined;
      return {
        color: palette,
        tooltip: { trigger: "item", backgroundColor: dark ? "#232322" : "#fff", textStyle: { color: c.textPrimary } },
        graphic: centerGraphic,
        legend: {
          orient: "vertical",
          right: 8,
          top: "middle",
          icon: "circle",
          itemWidth: 8,
          itemHeight: 8,
          itemGap: 12,
          formatter: (name: string) => {
            const idx = data.findIndex((r) => String(r[dimKey]) === name);
            const v = idx >= 0 ? values[idx] : 0;
            const pct = total > 0 ? ((v / total) * 100).toFixed(1) : "0.0";
            return `{name|${name}}  {val|${formatValue(v, format)} (${pct}%)}`;
          },
          textStyle: {
            rich: {
              name: { color: c.textSecondary, fontSize: 11.5, fontWeight: 500, width: 84 },
              val: { color: c.textPrimary, fontSize: 11.5, fontWeight: 600 },
            },
          },
        },
        series: [
          {
            type: "pie",
            radius: isDonut ? ["48%", "72%"] : "72%",
            center: ["38%", "50%"],
            avoidLabelOverlap: true,
            itemStyle: { borderColor: c.surface, borderWidth: 2, borderRadius: 4 },
            label: { show: false },
            labelLine: { show: false },
            data: data.map((r, i) => ({
              name: String(r[dimKey]),
              value: Number(r[measure]) || 0,
              itemStyle: { color: colorForName(String(r[dimKey]), i, palette, categoryColorMap) },
            })),
          },
        ],
      };
    }
    case "scatter": {
      const xMeasure = measureKeys[0];
      const yMeasure = measureKeys[1] || measureKeys[0];
      return {
        color: palette,
        tooltip: { trigger: "item", backgroundColor: dark ? "#232322" : "#fff", textStyle: { color: c.textPrimary } },
        grid: commonGrid,
        xAxis: {
          type: "value",
          name: xMeasure,
          axisLabel: { color: c.textSecondary, fontSize: 11 },
          splitLine: { lineStyle: { color: c.gridline } },
        },
        yAxis: {
          type: "value",
          name: yMeasure,
          axisLabel: { color: c.textSecondary, fontSize: 11 },
          splitLine: { lineStyle: { color: c.gridline } },
        },
        series: [
          {
            type: "scatter",
            symbolSize: 10,
            itemStyle: { color: palette[0] },
            data: data.map((r) => [Number(r[xMeasure]) || 0, Number(r[yMeasure]) || 0]),
          },
        ],
      };
    }
    case "funnel": {
      const measure = measureKeys[0];
      const values = data.map((r) => Number(r[measure]) || 0);
      // Percent-of-first-stage is a client-computed derived figure from the
      // real data array already provided — not a fabricated number.
      const firstStage = values[0] || 0;
      return {
        color: palette,
        tooltip: { trigger: "item", backgroundColor: dark ? "#232322" : "#fff", textStyle: { color: c.textPrimary } },
        series: [
          {
            type: "funnel",
            left: "8%",
            width: "84%",
            top: 12,
            bottom: 8,
            minSize: "12%",
            maxSize: "100%",
            gap: 3,
            sort: "descending",
            label: {
              color: c.textPrimary,
              fontSize: 12,
              fontWeight: 500,
              formatter: (p: { dataIndex: number; name: string }) => {
                const v = values[p.dataIndex] ?? 0;
                const pct = firstStage > 0 ? ((v / firstStage) * 100).toFixed(0) : "0";
                return `{name|${p.name}}\n{val|${formatValue(v, format)} · ${pct}%}`;
              },
              rich: {
                name: { color: c.textPrimary, fontSize: 12, fontWeight: 600, lineHeight: 16 },
                val: { color: c.textSecondary, fontSize: 11, lineHeight: 16 },
              },
            },
            labelLine: { show: false },
            itemStyle: { borderColor: c.surface, borderWidth: 2 },
            data: data.map((r, i) => ({
              name: String(r[dimKey]),
              value: values[i],
              itemStyle: { color: colorForName(String(r[dimKey]), i, palette, categoryColorMap) },
            })),
          },
        ],
      };
    }
    case "gauge": {
      const measure = measureKeys[0];
      const value = Number(data[0]?.[measure]) || 0;
      // Sensible max: percent-style values are 0-100 (or 0-1 fractions,
      // formatValue handles both), otherwise scale headroom off the value.
      const max =
        format === "percentage"
          ? value <= 1
            ? 1
            : 100
          : Math.max(value * 1.25, 10);
      return {
        series: [
          {
            type: "gauge",
            min: 0,
            max,
            startAngle: 210,
            endAngle: -30,
            progress: {
              show: true,
              width: 14,
              itemStyle: { color: palette[0] },
            },
            axisLine: {
              lineStyle: {
                width: 14,
                color: [
                  [0.5, dark ? "#2c2c2a" : "#e1e0d9"],
                  [0.8, `${palette[0]}55`],
                  [1, palette[0]],
                ],
              },
            },
            pointer: {
              show: true,
              length: "55%",
              width: 4,
              itemStyle: { color: c.textPrimary },
            },
            anchor: { show: true, size: 10, itemStyle: { color: c.textPrimary } },
            axisTick: { show: false },
            splitLine: { show: false },
            axisLabel: { show: false },
            detail: {
              valueAnimation: true,
              formatter: (v: number) => formatValue(v, format),
              color: c.textPrimary,
              fontSize: 26,
              fontWeight: 700,
              offsetCenter: [0, "68%"],
            },
            data: [{ value }],
          },
        ],
      };
    }
    case "heatmap": {
      const measure = measureKeys[0];
      const yField = seriesField;
      const yCats = yField ? Array.from(new Set(data.map((r) => String(r[yField])))) : ["value"];
      const xCats = Array.from(new Set(categories));
      const points = data.map((r) => [
        xCats.indexOf(String(r[dimKey])),
        yField ? yCats.indexOf(String(r[yField])) : 0,
        Number(r[measure]) || 0,
      ]);
      const values = points.map((p) => p[2] as number);
      return {
        tooltip: { position: "top", backgroundColor: dark ? "#232322" : "#fff", textStyle: { color: c.textPrimary } },
        grid: { ...commonGrid, top: 24 },
        xAxis: { type: "category", data: xCats, axisLabel: { color: c.textSecondary, fontSize: 10 }, splitArea: { show: true } },
        yAxis: { type: "category", data: yCats, axisLabel: { color: c.textSecondary, fontSize: 10 }, splitArea: { show: true } },
        visualMap: {
          min: Math.min(0, ...values),
          max: Math.max(1, ...values),
          calculable: true,
          orient: "horizontal",
          left: "center",
          bottom: 0,
          textStyle: { color: c.textSecondary },
          inRange: { color: dark ? ["#0d366b", "#3987e5"] : ["#cde2fb", "#2a78d6"] },
        },
        series: [
          {
            type: "heatmap",
            data: points,
            label: { show: false },
            itemStyle: { borderColor: c.surface, borderWidth: 2 },
          },
        ],
      };
    }
    default:
      return {};
  }
}

export function ChartRenderer({
  type,
  data,
  xField,
  yField,
  series,
  seriesField,
  format,
  height = "100%",
  categoryColorMap,
}: ChartRendererProps) {
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";

  const option = React.useMemo(() => {
    if (!data || data.length === 0) return {};
    return buildOption(type, data, xField, yField, seriesField, series, format, dark, categoryColorMap);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [type, data, xField, yField, seriesField, series, format, dark, categoryColorMap]);

  if (!data || data.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-1 text-center">
        <p className="text-xs text-muted-foreground">No data</p>
      </div>
    );
  }

  if (!option || Object.keys(option).length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-1 text-center">
        <p className="text-xs text-muted-foreground">Unsupported chart type: {type}</p>
      </div>
    );
  }

  return (
    <ReactECharts
      option={option}
      style={{ height, width: "100%" }}
      notMerge
      lazyUpdate
      opts={{ renderer: "canvas" }}
    />
  );
}
