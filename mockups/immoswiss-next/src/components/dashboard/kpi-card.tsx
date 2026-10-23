import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { Kpi } from "@/lib/mock-data";
import { Sparkline } from "./sparkline";

export function KpiCard({ kpi }: { kpi: Kpi }) {
  const up = kpi.trend > 0;
  const positive = (kpi.goodWhen === "up") === up;
  const Arrow = up ? ArrowUpRight : ArrowDownRight;
  const abs = Math.abs(kpi.trend).toString().replace(".", ",");
  const Icon = kpi.icon;

  return (
    <Card
      className={cn(
        "min-w-0 p-5 transition-all duration-200 hover:-translate-y-0.5 sm:p-6",
        kpi.alert && "border-destructive/40 from-destructive/10 to-card/80",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className={cn("grid size-11 place-items-center rounded-xl", kpi.alert ? "bg-destructive/15 text-destructive" : "bg-secondary text-primary")}>
          <Icon className="size-5" strokeWidth={1.8} />
        </span>
        <Sparkline data={kpi.spark} positive={positive} />
      </div>
      <div className="mt-5 flex items-center gap-2 text-sm font-medium text-muted-foreground">
        {kpi.label}
        {kpi.alert && <span className="size-2 rounded-full bg-destructive"><span className="sr-only">Handlungsbedarf</span></span>}
      </div>
      <div className="tabular mt-1 whitespace-nowrap text-[28px] font-extrabold leading-tight tracking-tight">{kpi.value}</div>
      <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <Badge variant={positive ? "success" : "destructive"}>
          <Arrow className="size-3" strokeWidth={2.6} />
          {up ? "+" : "−"}{abs}{kpi.trendUnit}
          <span className="sr-only">{positive ? " (günstig)" : " (ungünstig)"}</span>
        </Badge>
        <span>{kpi.trendNote}</span>
      </div>
    </Card>
  );
}
