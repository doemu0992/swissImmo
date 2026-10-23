import { KPIS } from "@/lib/mock-data";
import { KpiCard } from "./kpi-card";

export function KpiGrid() {
  return (
    <section aria-label="Kennzahlen" className="grid grid-cols-1 gap-4 sm:grid-cols-2 sm:gap-5 xl:grid-cols-4 lg:gap-6">
      {KPIS.map((kpi) => <KpiCard key={kpi.id} kpi={kpi} />)}
    </section>
  );
}
