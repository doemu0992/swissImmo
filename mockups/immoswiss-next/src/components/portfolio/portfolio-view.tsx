"use client";

import { useState } from "react";
import { ArrowDownRight, ArrowUpRight, CalendarCheck, Info } from "lucide-react";
import { CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Sparkline } from "@/components/dashboard/sparkline";
import { PageTitle, pageMain } from "@/components/shared/page-title";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { apos, chf } from "@/lib/format";
import { CASHFLOW, HOLDINGS, PAYOUT, PORTFOLIO_KPIS } from "@/lib/portfolio-data";
import { cn } from "@/lib/utils";

const tooltipStyle = { background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 12, color: "hsl(var(--foreground))", fontSize: 13 };
const tick = { fill: "hsl(var(--muted-foreground))", fontSize: 12 };

const SERIES = [
  { key: "einnahmen", label: "Einnahmen", color: "--chart-1", width: 2.5 },
  { key: "ausgaben", label: "Ausgaben", color: "--chart-4", width: 2.5, dash: "6 5" },
  { key: "netto", label: "Netto-Cashflow", color: "--chart-3", width: 3 },
] as const;

function CashflowCard() {
  const [range, setRange] = useState<"6" | "12">("12");
  const data = range === "12" ? CASHFLOW : CASHFLOW.slice(-6);
  const sum = (k: "einnahmen" | "ausgaben" | "netto") => data.reduce((s, r) => s + r[k], 0);
  return (
    <Card className="flex min-w-0 flex-col">
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1.5">
          <CardTitle>Cashflow</CardTitle>
          <CardDescription>Letzte {range} Monate · bis Oktober 2026</CardDescription>
        </div>
        <Tabs value={range} onValueChange={(v) => setRange(v as "6" | "12")}>
          <TabsList aria-label="Zeitraum">
            <TabsTrigger value="6">6 Monate</TabsTrigger>
            <TabsTrigger value="12">12 Monate</TabsTrigger>
          </TabsList>
        </Tabs>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col">
        <dl className="mb-5 grid grid-cols-1 gap-4 sm:grid-cols-3 sm:gap-6">
          {SERIES.map((s) => (
            <div key={s.key} className="min-w-0">
              <dt className="flex items-center gap-2 text-sm text-muted-foreground">
                <span className="h-0.5 w-4 rounded" style={{ background: `hsl(var(${s.color}))` }} aria-hidden="true" />{s.label}
              </dt>
              <dd className="tabular whitespace-nowrap text-xl font-extrabold tracking-tight">{chf(sum(s.key))}</dd>
            </div>
          ))}
        </dl>
        <div className="h-64 w-full sm:h-72 xl:h-[22rem]" role="img" aria-label={`Liniendiagramm Cashflow der letzten ${range} Monate: Einnahmen, Ausgaben und Netto-Cashflow`}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeOpacity={0.7} />
              <XAxis dataKey="month" axisLine={false} tickLine={false} tick={tick} dy={8} interval="preserveStartEnd" minTickGap={16} />
              <YAxis axisLine={false} tickLine={false} width={48} tickCount={5} tick={tick} domain={[150000, 500000]} ticks={[150000, 250000, 350000, 450000]} tickFormatter={(v: number) => `${Math.round(v / 1000)}k`} />
              <Tooltip
                cursor={{ stroke: "hsl(var(--border))" }}
                contentStyle={tooltipStyle}
                itemStyle={{ color: "hsl(var(--foreground))" }}
                formatter={(v: number, n: string) => [chf(v), SERIES.find((s) => s.key === n)?.label ?? n]}
              />
              {SERIES.map((s) => (
                <Line key={`${range}-${s.key}`} type="monotone" dataKey={s.key} stroke={`hsl(var(${s.color}))`} strokeWidth={s.width} strokeDasharray={"dash" in s ? s.dash : undefined} dot={false} activeDot={{ r: 5, strokeWidth: 2, stroke: "hsl(var(--card))" }} isAnimationActive={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}

const COLORS = ["--chart-1", "--chart-3", "--chart-4", "--chart-5", "--chart-2"];

function DonutCard() {
  const [by, setBy] = useState<"liegenschaft" | "nutzung">("liegenschaft");
  const slices =
    by === "liegenschaft"
      ? HOLDINGS.map((h, i) => ({ key: h.id, label: h.name.split(",")[0], value: h.value, color: COLORS[i % COLORS.length] }))
      : (["Wohnen", "Gemischt", "Gewerbe"] as const)
          .map((u, i) => ({ key: u, label: u, value: HOLDINGS.filter((h) => h.use === u).reduce((s, h) => s + h.value, 0), color: COLORS[i] }))
          .filter((s) => s.value > 0);
  const total = slices.reduce((s, x) => s + x.value, 0);
  return (
    <Card className="flex min-w-0 flex-col">
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1.5">
          <CardTitle>Portfolio-Verteilung</CardTitle>
          <CardDescription>Verkehrswert {chf(total)}</CardDescription>
        </div>
        <Tabs value={by} onValueChange={(v) => setBy(v as typeof by)}>
          <TabsList aria-label="Gruppierung">
            <TabsTrigger value="liegenschaft">Liegenschaft</TabsTrigger>
            <TabsTrigger value="nutzung">Nutzung</TabsTrigger>
          </TabsList>
        </Tabs>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col items-center gap-6 sm:flex-row lg:flex-col 2xl:flex-row">
        <div className="relative size-48 shrink-0" role="img" aria-label={`Donut-Diagramm Portfolio-Verteilung: ${slices.map((s) => `${s.label} ${((s.value / total) * 100).toFixed(1)} Prozent`).join(", ")}`}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Tooltip contentStyle={tooltipStyle} itemStyle={{ color: "hsl(var(--foreground))" }} formatter={(v: number, n: string) => [chf(v), n]} />
              <Pie key={by} data={slices} dataKey="value" nameKey="label" innerRadius={62} outerRadius={88} paddingAngle={3} cornerRadius={8} stroke="none" startAngle={90} endAngle={-270} isAnimationActive={false}>
                {slices.map((s) => <Cell key={s.key} fill={`hsl(var(${s.color}))`} />)}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
            <div>
              <div className="tabular text-3xl font-extrabold tracking-tight">{apos(total / 1e6, 1)}</div>
              <div className="text-xs font-medium text-muted-foreground">Mio. CHF</div>
            </div>
          </div>
        </div>
        <ul className="flex w-full min-w-0 flex-col gap-2">
          {slices.map((s) => (
            <li key={s.key} className="flex items-center gap-3 rounded-xl border bg-background/50 px-3.5 py-2.5">
              <span className="size-3 shrink-0 rounded-full" style={{ background: `hsl(var(${s.color}))` }} aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate text-sm font-semibold">{s.label}</span>
              <span className="tabular hidden whitespace-nowrap text-xs text-muted-foreground sm:inline">{chf(s.value / 1e6, 1).replace("CHF", "")} Mio.</span>
              <span className="tabular w-14 whitespace-nowrap text-right text-sm font-extrabold">{((s.value / total) * 100).toFixed(1)} %</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function PerformanceTable() {
  const target = HOLDINGS.reduce((s, h) => s + h.target, 0);
  const actual = HOLDINGS.reduce((s, h) => s + h.actual, 0);
  return (
    <Card className="min-w-0 overflow-hidden">
      <CardHeader className="pb-4">
        <CardTitle>Performance je Liegenschaft</CardTitle>
        <CardDescription>Soll- und Ist-Miete pro Jahr, Rendite-Verlauf der letzten 6 Monate</CardDescription>
      </CardHeader>
      <Table label="Performance je Liegenschaft" className="min-w-[860px]">
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Liegenschaft</TableHead>
            <TableHead className="text-right">Soll-Miete p. a.</TableHead>
            <TableHead className="text-right">Ist-Miete p. a.</TableHead>
            <TableHead className="min-w-[150px]">Ist / Soll</TableHead>
            <TableHead className="text-right">Leerstand</TableHead>
            <TableHead className="text-right">Rendite</TableHead>
            <TableHead>Verlauf</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {HOLDINGS.map((h) => {
            const pct = (h.actual / h.target) * 100;
            const up = h.trend[h.trend.length - 1] >= h.trend[0];
            return (
              <TableRow key={h.id}>
                <TableCell><div className="whitespace-nowrap font-bold">{h.name}</div><div className="text-xs text-muted-foreground">{h.use}</div></TableCell>
                <TableCell className="tabular whitespace-nowrap text-right">{chf(h.target)}</TableCell>
                <TableCell className="tabular whitespace-nowrap text-right font-bold">{chf(h.actual)}</TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-secondary" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} aria-label={`Ist gegenüber Soll ${h.name}`}>
                      <div className={cn("h-full rounded-full", pct >= 98 ? "bg-primary" : "bg-warning")} style={{ width: `${pct}%` }} />
                    </div>
                    <span className="tabular w-12 text-right text-xs font-semibold">{pct.toFixed(1)} %</span>
                  </div>
                </TableCell>
                <TableCell className="text-right"><Badge variant={h.vacancy > 5 ? "destructive" : h.vacancy > 3 ? "warning" : "success"} className="tabular">{h.vacancy.toFixed(1)} %</Badge></TableCell>
                <TableCell className="tabular whitespace-nowrap text-right font-extrabold">{h.yield.toFixed(1)} %</TableCell>
                <TableCell><Sparkline data={h.trend} positive={up} className="w-20" /><span className="sr-only">Rendite-Verlauf {up ? "steigend" : "fallend"}</span></TableCell>
              </TableRow>
            );
          })}
          <TableRow className="bg-secondary/40 hover:bg-secondary/40">
            <TableCell className="font-extrabold">Total Portfolio</TableCell>
            <TableCell className="tabular whitespace-nowrap text-right font-bold">{chf(target)}</TableCell>
            <TableCell className="tabular whitespace-nowrap text-right font-extrabold">{chf(actual)}</TableCell>
            <TableCell><span className="tabular text-xs font-semibold">{((actual / target) * 100).toFixed(1)} %</span></TableCell>
            <TableCell className="text-right"><Badge variant="success" className="tabular">2.4 %</Badge></TableCell>
            <TableCell className="tabular text-right font-extrabold">4.8 %</TableCell>
            <TableCell />
          </TableRow>
        </TableBody>
      </Table>
    </Card>
  );
}

function PayoutCard() {
  return (
    <Card className="min-w-0 border-primary/30 from-primary/10 to-card/80">
      <CardContent className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-start gap-4">
          <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-primary/15 text-primary"><CalendarCheck className="size-6" aria-hidden="true" /></span>
          <div className="min-w-0">
            <div className="text-xs font-bold uppercase tracking-widest text-muted-foreground">Auszahlung {PAYOUT.month}</div>
            <div className="tabular mt-1 text-3xl font-extrabold tracking-tight">{chf(PAYOUT.amount)}</div>
            <p className="mt-1 flex items-start gap-1.5 text-sm text-muted-foreground"><Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />Valuta {PAYOUT.date} auf Ihr Konto bei der ZKB. Die Abrechnung erhalten Sie am 20.11.2026.</p>
          </div>
        </div>
        <dl className="grid min-w-0 gap-2 text-sm lg:w-[26rem]">
          {PAYOUT.items.map((i) => (
            <div key={i.label} className="flex items-baseline justify-between gap-4">
              <dt className="min-w-0 text-muted-foreground">{i.label}</dt>
              <dd className={cn("tabular whitespace-nowrap font-semibold", i.amount < 0 && "text-muted-foreground")}>{chf(i.amount)}</dd>
            </div>
          ))}
          <div className="flex items-baseline justify-between gap-4 border-t pt-2 font-extrabold">
            <dt>Auszahlung</dt><dd className="tabular whitespace-nowrap">{chf(PAYOUT.amount)}</dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}

export function PortfolioView() {
  return (
    <main className={pageMain}>
      <PageTitle role="Eigentümer" title="Portfolio" subtitle="5 Liegenschaften · 126 Einheiten · Stand Oktober 2026" actions={<Button variant="outline">Eigentümerbericht (PDF)</Button>} />

      <section aria-label="Kennzahlen" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4 lg:gap-5">
        {PORTFOLIO_KPIS.map((k) => (
          <Card key={k.id} className="min-w-0 p-5 sm:p-6">
            <div className="text-sm font-medium text-muted-foreground">{k.label}</div>
            <div className="tabular mt-1 whitespace-nowrap text-2xl font-extrabold leading-tight tracking-tight">{k.value}</div>
            <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
              <Badge variant={k.positive ? "success" : "destructive"}>
                {k.trend.startsWith("−") ? <ArrowDownRight className="size-3" strokeWidth={2.6} aria-hidden="true" /> : <ArrowUpRight className="size-3" strokeWidth={2.6} aria-hidden="true" />}{k.trend}
                <span className="sr-only"> ({k.positive ? "günstig" : "ungünstig"}) gegenüber Vorjahr</span>
              </Badge>
              <span>{k.note}</span>
            </div>
          </Card>
        ))}
      </section>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-5 lg:gap-7">
        <div className="min-w-0 xl:col-span-3"><CashflowCard /></div>
        <div className="min-w-0 xl:col-span-2"><DonutCard /></div>
      </div>

      <PerformanceTable />
      <PayoutCard />
    </main>
  );
}
