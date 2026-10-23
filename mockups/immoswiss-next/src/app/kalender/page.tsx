import type { Metadata } from "next";
import { CalendarView } from "@/components/calendar/calendar-view";

export const metadata: Metadata = { title: "Kalender — immoswiss" };
export default function CalendarPage() {
  return <CalendarView />;
}
