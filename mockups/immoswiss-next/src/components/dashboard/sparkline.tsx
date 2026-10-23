import { cn } from "@/lib/utils";

/** Mini-Verlauf ohne Achsen. Farbe folgt der Bewertung, nicht der Richtung. */
export function Sparkline({ data, positive, className }: { data: number[]; positive: boolean; className?: string }) {
  const w = 96, h = 32;
  const min = Math.min(...data), max = Math.max(...data);
  const pts = data.map((v, i) => [i * (w / (data.length - 1)), h - 3 - ((v - min) / (max - min || 1)) * (h - 8)] as const);
  const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const [lx, ly] = pts[pts.length - 1];
  const color = positive ? "hsl(var(--success))" : "hsl(var(--destructive))";
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className={cn("h-8 w-24 overflow-visible", className)} aria-hidden="true">
      <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={lx} cy={ly} r="3" fill={color} />
    </svg>
  );
}
