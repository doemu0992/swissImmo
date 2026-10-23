"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { OCCUPANCY } from "@/lib/mock-data";

export function OccupancyChart() {
  const total = OCCUPANCY.reduce((s, o) => s + o.value, 0);
  const rate = (((OCCUPANCY[0].value + OCCUPANCY[1].value) / total) * 100).toFixed(1);

  return (
    <Card className="h-full min-w-0">
      <CardHeader>
        <CardTitle>Belegungsstatus</CardTitle>
        <CardDescription>{total} Mietobjekte im Bestand</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col items-center gap-6 sm:flex-row sm:gap-8 lg:flex-col xl:flex-col 2xl:flex-row">
        <div className="relative size-48 shrink-0" role="img" aria-label={`Donut-Diagramm: ${OCCUPANCY.map((o) => `${o.label} ${o.value}`).join(", ")}`}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Tooltip
                formatter={(v: number, n: string) => [`${v} Objekte`, n]}
                contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 12, color: "hsl(var(--foreground))", fontSize: 13 }}
                itemStyle={{ color: "hsl(var(--foreground))" }}
              />
              <Pie data={OCCUPANCY} dataKey="value" nameKey="label" innerRadius={66} outerRadius={90} paddingAngle={4} cornerRadius={8} stroke="none" startAngle={90} endAngle={-270} isAnimationActive={false}>
                {OCCUPANCY.map((o) => <Cell key={o.key} fill={`hsl(var(${o.colorVar}))`} />)}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
            <div>
              <div className="tabular text-3xl font-extrabold tracking-tight">{rate} %</div>
              <div className="text-xs font-medium text-muted-foreground">belegt</div>
            </div>
          </div>
        </div>

        <ul className="flex w-full min-w-0 flex-col gap-3">
          {OCCUPANCY.map((o) => (
            <li key={o.key} className="flex items-center gap-3 rounded-xl border bg-background/50 px-3.5 py-3">
              <span className="size-3 shrink-0 rounded-full" style={{ background: `hsl(var(${o.colorVar}))` }} />
              <span className="flex-1 text-sm font-semibold">{o.label}</span>
              <span className="tabular text-sm font-extrabold">{o.value}</span>
              <span className="tabular w-14 whitespace-nowrap text-right text-xs text-muted-foreground">{((o.value / total) * 100).toFixed(1)} %</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
