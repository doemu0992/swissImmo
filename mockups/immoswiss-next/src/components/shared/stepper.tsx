import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export type StepperStep = { label: string; note?: string };

/** Workflow-Stepper: Zustand wird per Symbol UND Text (erledigt / aktuell / ausstehend) vermittelt, nie nur per Farbe. */
export function Stepper({ steps, current, label, compact }: { steps: readonly StepperStep[]; current: number; label: string; compact?: boolean }) {
  return (
    <ol aria-label={label} className={cn("flex w-full", compact ? "items-center gap-1" : "flex-col gap-4 sm:flex-row sm:gap-0")}>
      {steps.map((s, i) => {
        const done = i < current;
        const now = i === current;
        const state = done ? "erledigt" : now ? "aktuell" : "ausstehend";
        return (
          <li key={s.label} aria-current={now ? "step" : undefined} className={cn("relative flex min-w-0 flex-1", compact ? "items-center gap-1.5" : "gap-3 sm:flex-col sm:items-start sm:gap-2")}>
            {!compact && i < steps.length - 1 && (
              <span aria-hidden="true" className={cn("absolute left-[15px] top-8 h-[calc(100%-1rem)] w-0.5 sm:left-9 sm:top-[15px] sm:h-0.5 sm:w-[calc(100%-3rem)]", done ? "bg-primary" : "bg-border")} />
            )}
            <span
              aria-hidden="true"
              className={cn(
                "relative z-10 grid shrink-0 place-items-center rounded-full border-2 text-xs font-bold",
                compact ? "size-6" : "size-8",
                done && "border-primary bg-primary text-primary-foreground",
                now && "border-primary bg-card text-primary ring-4 ring-primary/20",
                !done && !now && "border-border bg-card text-muted-foreground",
              )}
            >
              {done ? <Check className={compact ? "size-3.5" : "size-4"} strokeWidth={3} /> : i + 1}
            </span>
            <span className="min-w-0">
              <span className={cn("block text-sm font-bold", compact && "truncate text-xs", !done && !now && "text-muted-foreground")}>{s.label}</span>
              {!compact && s.note && <span className="block text-xs text-muted-foreground">{s.note}</span>}
              <span className="sr-only"> ({state})</span>
              {!compact && <span className={cn("mt-0.5 block text-[11px] font-bold uppercase tracking-wider", now ? "text-primary" : done ? "text-success" : "text-muted-foreground/70")} aria-hidden="true">{state}</span>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
