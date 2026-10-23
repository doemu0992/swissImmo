"use client";

import { useMemo, useState } from "react";
import { AlertCircle, ChevronLeft, ChevronRight, ClipboardCheck, Eye, HandHelping, KeyRound, MapPin, Wrench, type LucideIcon } from "lucide-react";
import { PageTitle, pageMain } from "@/components/shared/page-title";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CALENDAR_EVENTS, EVENT_KINDS, TODAY_ISO, type CalendarEvent, type EventKind } from "@/lib/calendar-data";
import { MONTH_LONG } from "@/lib/format";
import { cn } from "@/lib/utils";

const KIND_META: Record<EventKind, { icon: LucideIcon; chip: string; variant: "default" | "success" | "warning" | "secondary" | "destructive" }> = {
  Abnahme: { icon: ClipboardCheck, chip: "bg-primary/15 text-primary", variant: "default" },
  Besichtigung: { icon: Eye, chip: "bg-success/15 text-success", variant: "success" },
  Handwerker: { icon: Wrench, chip: "bg-warning/15 text-warning", variant: "warning" },
  Übergabe: { icon: KeyRound, chip: "bg-secondary text-foreground ring-1 ring-inset ring-border", variant: "secondary" },
  Frist: { icon: AlertCircle, chip: "bg-destructive/15 text-destructive", variant: "destructive" },
};

const WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const WEEKDAYS_LONG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];

const iso = (y: number, m: number, d: number) => `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
/** Wochentag Mo=0 … So=6 */
const weekday = (y: number, m: number, d: number) => (new Date(Date.UTC(y, m, d)).getUTCDay() + 6) % 7;
const weekdayOf = (isoDate: string) => { const [y, m, d] = isoDate.split("-").map(Number); return weekday(y, m - 1, d); };
const dayLabel = (isoDate: string) => { const [, m, d] = isoDate.split("-").map(Number); return `${WEEKDAYS_LONG[weekdayOf(isoDate)]}, ${d}. ${MONTH_LONG[m - 1]}`; };

/* Diese Woche (Mo–So, KW 43) um den Stichtag */
const todayWd = weekdayOf(TODAY_ISO);
const [ty, tm, td] = TODAY_ISO.split("-").map(Number);
const WEEK_DAYS = Array.from({ length: 7 }, (_, i) => { const d = new Date(Date.UTC(ty, tm - 1, td - todayWd + i)); return iso(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()); });

const byTime = (a: CalendarEvent, b: CalendarEvent) => (a.time || "99").localeCompare(b.time || "99");

function EventChip({ e }: { e: CalendarEvent }) {
  const { icon: Icon, chip } = KIND_META[e.kind];
  return (
    <li className={cn("flex min-w-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-semibold leading-tight", chip)} title={`${e.kind}: ${e.title}${e.time ? `, ${e.time} Uhr` : ""} — ${e.place}`}>
      <Icon className="size-3 shrink-0" aria-hidden="true" />
      <span className="sr-only">{e.kind}: </span>
      <span className="truncate">{e.time && <span className="tabular hidden opacity-80 2xl:inline">{e.time} </span>}{e.title}</span>
    </li>
  );
}

function AgendaItem({ e, past }: { e: CalendarEvent; past?: boolean }) {
  const { icon: Icon, variant } = KIND_META[e.kind];
  return (
    <li className={cn("flex items-start gap-3 rounded-2xl border bg-background/50 p-3.5", past && "opacity-60")}>
      <div className="tabular w-12 shrink-0 pt-0.5 text-sm font-bold">{e.time || <span className="text-xs text-muted-foreground">ganztags</span>}</div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-bold">{e.title}</span>
          <Badge variant={variant}><Icon className="size-3" aria-hidden="true" />{e.kind}</Badge>
          {past && <span className="text-xs text-muted-foreground">vorbei</span>}
        </div>
        <div className="mt-1 flex min-w-0 items-start gap-1 text-xs text-muted-foreground">
          <MapPin className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          <span className="min-w-0">{e.place}</span>
        </div>
      </div>
    </li>
  );
}

function DayGroup({ date, events }: { date: string; events: CalendarEvent[] }) {
  const isToday = date === TODAY_ISO;
  return (
    <section aria-label={dayLabel(date)}>
      <h4 className={cn("mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-wider", isToday ? "text-primary" : "text-muted-foreground")}>
        {dayLabel(date)} {isToday && <Badge>Heute</Badge>}
      </h4>
      <ul className="flex flex-col gap-2.5">
        {events.map((e) => <AgendaItem key={e.id} e={e} past={date < TODAY_ISO} />)}
      </ul>
    </section>
  );
}

function groupByDay(events: CalendarEvent[]) {
  const map = new Map<string, CalendarEvent[]>();
  [...events].sort((a, b) => a.date.localeCompare(b.date) || byTime(a, b)).forEach((e) => map.set(e.date, [...(map.get(e.date) ?? []), e]));
  return [...map.entries()];
}

function AgendaCard() {
  const [tab, setTab] = useState<"heute" | "woche">("heute");
  const today = CALENDAR_EVENTS.filter((e) => e.date === TODAY_ISO).sort(byTime);
  const week = CALENDAR_EVENTS.filter((e) => WEEK_DAYS.includes(e.date));
  return (
    <Card className="min-w-0">
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1.5">
          <CardTitle>Agenda</CardTitle>
          <CardDescription>{tab === "heute" ? "Freitag, 23. Oktober 2026" : "KW 43 · 19.–25. Oktober 2026"}</CardDescription>
        </div>
        <Tabs value={tab} onValueChange={(v) => setTab(v as "heute" | "woche")}>
          <TabsList aria-label="Agenda-Zeitraum">
            <TabsTrigger value="heute">Heute</TabsTrigger>
            <TabsTrigger value="woche">Diese Woche</TabsTrigger>
          </TabsList>
        </Tabs>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {tab === "heute" ? (
          today.length ? <ul className="flex flex-col gap-2.5">{today.map((e) => <AgendaItem key={e.id} e={e} />)}</ul> : <p className="py-6 text-center text-sm text-muted-foreground">Heute keine Termine.</p>
        ) : (
          groupByDay(week).map(([d, ev]) => <DayGroup key={d} date={d} events={ev} />)
        )}
      </CardContent>
    </Card>
  );
}

export function CalendarView() {
  const [ym, setYm] = useState({ y: 2026, m: 9 });
  const { y, m } = ym;
  const go = (delta: number) => setYm(({ y, m }) => { const n = y * 12 + m + delta; return { y: Math.floor(n / 12), m: n % 12 }; });

  const daysInMonth = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
  const lead = weekday(y, m, 1);
  const cells = useMemo(() => {
    const arr: (number | null)[] = [...Array(lead).fill(null), ...Array.from({ length: daysInMonth }, (_, i) => i + 1)];
    while (arr.length % 7) arr.push(null);
    return Array.from({ length: arr.length / 7 }, (_, w) => arr.slice(w * 7, w * 7 + 7));
  }, [lead, daysInMonth]);

  const monthPrefix = `${y}-${String(m + 1).padStart(2, "0")}`;
  const monthEvents = CALENDAR_EVENTS.filter((e) => e.date.startsWith(monthPrefix));
  const monthLabel = `${MONTH_LONG[m]} ${y}`;

  const nav = (
    <div className="flex items-center gap-2">
      <Button variant="outline" size="icon" onClick={() => go(-1)} aria-label="Vorheriger Monat"><ChevronLeft /></Button>
      <Button variant="outline" size="icon" onClick={() => go(1)} aria-label="Nächster Monat"><ChevronRight /></Button>
      <Button variant="outline" onClick={() => setYm({ y: ty, m: tm - 1 })}>Heute</Button>
    </div>
  );

  return (
    <main className={pageMain}>
      <PageTitle role="Bewirtschafter" title="Kalender" subtitle={`${CALENDAR_EVENTS.filter((e) => WEEK_DAYS.includes(e.date) && e.date >= TODAY_ISO).length} Termine und Fristen in dieser Woche noch offen.`} actions={nav} />

      <div className="grid grid-cols-1 gap-6 2xl:grid-cols-3 2xl:gap-7">
        <div className="min-w-0 2xl:col-span-2 2xl:row-start-1">
          <Card>
            <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
              <CardTitle aria-live="polite" className="text-xl">{monthLabel}</CardTitle>
              <ul className="hidden flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground md:flex" aria-label="Legende">
                {EVENT_KINDS.map((k) => {
                  const { icon: Icon, chip } = KIND_META[k];
                  return <li key={k} className="inline-flex items-center gap-1.5"><span className={cn("grid size-5 place-items-center rounded-md", chip)}><Icon className="size-3" aria-hidden="true" /></span>{k}</li>;
                })}
              </ul>
            </CardHeader>
            <CardContent>
              {/* Raster ab 768 px */}
              <table className="hidden w-full table-fixed border-separate border-spacing-1 md:table">
                <caption className="sr-only">Monatsansicht {monthLabel}</caption>
                <thead>
                  <tr>{WEEKDAYS.map((d, i) => <th key={d} scope="col" abbr={WEEKDAYS_LONG[i]} className="pb-1 text-center text-xs font-bold uppercase tracking-wider text-muted-foreground">{d}</th>)}</tr>
                </thead>
                <tbody>
                  {cells.map((week, wi) => (
                    <tr key={wi}>
                      {week.map((d, di) => {
                        if (!d) return <td key={di} className="h-[116px] rounded-xl bg-secondary/20" />;
                        const date = iso(y, m, d);
                        const ev = monthEvents.filter((e) => e.date === date).sort(byTime);
                        const isToday = date === TODAY_ISO;
                        return (
                          <td key={di} className={cn("h-[116px] min-w-0 rounded-xl border p-1.5 align-top", isToday ? "border-primary bg-primary/10 ring-1 ring-primary" : "bg-background/40", di > 4 && !isToday && "bg-secondary/30")} aria-current={isToday ? "date" : undefined}>
                            <div className="mb-1 flex items-center justify-between">
                              <span className={cn("tabular grid size-6 place-items-center rounded-full text-xs font-bold", isToday ? "bg-primary text-primary-foreground" : "text-muted-foreground")}>
                                {d}<span className="sr-only">. {MONTH_LONG[m]}{isToday ? " (heute)" : ""}</span>
                              </span>
                            </div>
                            <ul className="flex flex-col gap-1">
                              {ev.slice(0, 2).map((e) => <EventChip key={e.id} e={e} />)}
                              {ev.length > 2 && <li className="px-1 text-[11px] font-semibold text-muted-foreground" title={ev.slice(2).map((e) => e.title).join(", ")}>+{ev.length - 2} weitere</li>}
                            </ul>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>

              {/* Telefon: Agenda statt Raster */}
              <div className="flex flex-col gap-5 md:hidden">
                {monthEvents.length ? groupByDay(monthEvents).map(([d, ev]) => <DayGroup key={d} date={d} events={ev} />) : (
                  <p className="flex items-center gap-2 py-6 text-sm text-muted-foreground"><HandHelping className="size-4" aria-hidden="true" /> In diesem Monat sind keine Termine erfasst.</p>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
        <div className="order-first min-w-0 md:order-none 2xl:col-start-3 2xl:row-start-1"><AgendaCard /></div>
      </div>
    </main>
  );
}
