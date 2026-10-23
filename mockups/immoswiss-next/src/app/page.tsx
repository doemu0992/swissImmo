import { AppointmentsCard } from "@/components/dashboard/appointments-card";
import { KpiGrid } from "@/components/dashboard/kpi-grid";
import { OccupancyChart } from "@/components/dashboard/occupancy-chart";
import { PageHeader } from "@/components/dashboard/page-header";
import { RevenueChart } from "@/components/dashboard/revenue-chart";

export default function DashboardPage() {
  return (
    <main className="mx-auto flex w-full max-w-[1480px] flex-1 flex-col gap-6 px-4 pb-36 pt-7 sm:px-6 lg:gap-7 lg:px-8 lg:pb-14">
      <PageHeader />
      <KpiGrid />
      <RevenueChart />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5 lg:gap-7">
        <div className="min-w-0 lg:col-span-3"><AppointmentsCard /></div>
        <div className="min-w-0 lg:col-span-2"><OccupancyChart /></div>
      </div>
    </main>
  );
}
