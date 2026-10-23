"use client";

import { useId, useState } from "react";
import { Area, AreaChart, CartesianGrid, Tooltip, XAxis, YAxis, type TooltipProps } from "recharts";
import { ResponsiveContainer } from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CHART_VIEWS, type ChartView } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

function ChartTooltip({ active, payload, label, view }: TooltipProps<number, string> & { view: ChartView }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border bg-popover px-3.5 py-3 text-sm shadow-pop">
      <div className="mb-1.5 font-bold">{label}</div>
      {payload.map((p) => {
        const s = view.series.find((x) => x.key === p.dataKey);
        const v = Number(p.value);
        return (
          <div key={String(p.dataKey)} className="flex items-center gap-2 text-muted-foreground">
            <span className="size-2 rounded-full" style={{ background: `hsl(var(${s?.colorVar}))` }} />
            {s?.label}
            <span className="tabular ml-auto pl-4 font-semibold text-foreground">{view.id === "einnahmen" ? `CHF ${v.toLocaleString("de-CH")}` : `${v.toFixed(1)} %`}</span>
          </div>
        );
      })}
    </div>
  );
}

export function RevenueChart() {
  const [viewId, setViewId] = useState<ChartView["id"]>("einnahmen");
  const view = CHART_VIEWS.find((v) => v.id === viewId)!;
  const gradId = useId().replace(/:/g, "");

  return (
    <Card className="flex h-full min-w-0 flex-col">
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1.5">
          <CardTitle>{view.title}</CardTitle>
          <CardDescription>Letzte 6 Monate · Mai – Oktober 2026</CardDescription>
        </div>
        <Tabs value={viewId} onValueChange={(v) => setViewId(v as ChartView["id"])}>
          <TabsList aria-label="Diagrammansicht">
            <TabsTrigger value="einnahmen">Einnahmen</TabsTrigger>
            <TabsTrigger value="belegung">Belegung</TabsTrigger>
          </TabsList>
        </Tabs>
      </CardHeader>

      <CardContent className="flex flex-1 flex-col">
        <dl className="mb-5 grid grid-cols-1 gap-4 sm:grid-cols-3 sm:gap-6">
          {view.summary.map((s) => (
            <div key={s.label} className="min-w-0">
              <dt className="text-sm text-muted-foreground">{s.label}</dt>
              <dd className="flex flex-wrap items-baseline gap-2">
                <span className="tabular text-2xl font-extrabold tracking-tight">{s.value}</span>
                <span className={cn("text-xs font-bold", s.positive ? "text-success" : "text-destructive")}>{s.delta}</span>
              </dd>
            </div>
          ))}
        </dl>

        <ul className="mb-3 flex items-center gap-5 text-sm text-muted-foreground">
          {view.series.map((s) => (
            <li key={s.key} className="inline-flex items-center gap-2">
              <span className="size-2.5 rounded-full" style={{ background: `hsl(var(${s.colorVar}))` }} />
              {s.label}
            </li>
          ))}
        </ul>

        <div className="h-64 w-full sm:h-72" role="img" aria-label={`Liniendiagramm: ${view.title}, Mai bis Oktober 2026`}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={view.rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id={`fill-${gradId}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="hsl(var(--chart-1))" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="hsl(var(--chart-1))" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeOpacity={0.7} />
              <XAxis dataKey="month" axisLine={false} tickLine={false} tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }} dy={8} />
              <YAxis
                domain={view.domain}
                axisLine={false}
                tickLine={false}
                width={48}
                tickCount={5}
                tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
                tickFormatter={(v: number) => `${Math.round(v / view.tickDivisor)}${view.tickSuffix}`}
              />
              <Tooltip content={<ChartTooltip view={view} />} cursor={{ stroke: "hsl(var(--border))", strokeWidth: 1 }} />
              {view.series.map((s, i) => (
                <Area
                  key={`${view.id}-${s.key}`}
                  type="monotone"
                  dataKey={s.key}
                  stroke={`hsl(var(${s.colorVar}))`}
                  strokeWidth={i === 0 ? 3 : 2}
                  strokeDasharray={s.dashed ? "6 5" : undefined}
                  fill={i === 0 ? `url(#fill-${gradId})` : "transparent"}
                  dot={false}
                  activeDot={{ r: 6, strokeWidth: 3, stroke: "hsl(var(--card))", fill: `hsl(var(${s.colorVar}))` }}
                  isAnimationActive={false}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
