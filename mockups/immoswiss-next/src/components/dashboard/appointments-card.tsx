"use client";

import { useState } from "react";
import { Check, MapPin } from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { APPOINTMENTS, TODOS, type Appointment, type Todo } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

/* Initialen statt Fotos — Mieterdaten fallen unter das DSG. */
const AVATAR_GRADIENTS = [
  "from-[#35577d] to-[#6e9bd1]",
  "from-[#2f6b5b] to-[#4cc08a]",
  "from-[#6b5530] to-[#d9a548]",
  "from-[#5b3a52] to-[#d98cb7]",
];
const initials = (name: string) => name.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();

const KIND_VARIANT: Record<Appointment["kind"], "default" | "success" | "warning" | "secondary"> = {
  Abnahme: "default",
  Besichtigung: "success",
  Handwerker: "warning",
  Übergabe: "secondary",
};

function AvatarStack({ people }: { people: string[] }) {
  return (
    <div className="flex shrink-0 -space-x-2">
      {people.slice(0, 3).map((p, i) => (
        <Avatar key={p} className="size-8">
          <AvatarFallback className={cn("bg-gradient-to-br", AVATAR_GRADIENTS[i % AVATAR_GRADIENTS.length])}>{initials(p)}</AvatarFallback>
        </Avatar>
      ))}
    </div>
  );
}

function AppointmentRow({ a }: { a: Appointment }) {
  return (
    <li className="flex items-center gap-4 rounded-2xl border bg-background/50 p-3.5 transition-colors hover:border-primary/40">
      <AvatarStack people={a.people} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-bold">{a.title}</span>
          <Badge variant={KIND_VARIANT[a.kind]}>{a.kind}</Badge>
        </div>
        <div className="mt-0.5 flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
          <MapPin className="size-3.5 shrink-0" />
          <span className="truncate">{a.place}</span>
        </div>
      </div>
      <div className="shrink-0 text-right">
        <div className="tabular text-sm font-bold">{a.time}</div>
        <div className="text-xs text-muted-foreground">{a.date}</div>
      </div>
    </li>
  );
}

export function AppointmentsCard() {
  const [todos, setTodos] = useState<Todo[]>(TODOS);
  const open = todos.filter((t) => !t.done).length;
  const toggle = (id: number) => setTodos((list) => list.map((t) => (t.id === id ? { ...t, done: !t.done } : t)));

  return (
    <Card className="flex h-full min-w-0 flex-col">
      <Tabs defaultValue="termine" className="flex flex-1 flex-col">
        <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
          <div className="flex flex-col gap-1.5">
            <CardTitle>Termine &amp; To-Dos</CardTitle>
            <CardDescription>{APPOINTMENTS.length} Termine diese Woche · {open} To-Dos offen</CardDescription>
          </div>
          <TabsList aria-label="Ansicht">
            <TabsTrigger value="termine">Termine</TabsTrigger>
            <TabsTrigger value="todos">To-Dos</TabsTrigger>
          </TabsList>
        </CardHeader>

        <CardContent className="flex flex-1 flex-col">
          <TabsContent value="termine" className="mt-0">
            <ul className="flex flex-col gap-2.5">{APPOINTMENTS.map((a) => <AppointmentRow key={a.id} a={a} />)}</ul>
          </TabsContent>
          <TabsContent value="todos" className="mt-0">
            <ul className="flex flex-col gap-2.5">
              {todos.map((t) => (
                <li key={t.id}>
                  <button
                    role="checkbox"
                    aria-checked={!!t.done}
                    onClick={() => toggle(t.id)}
                    className="flex w-full items-center gap-3.5 rounded-2xl border bg-background/50 p-3.5 text-left transition-colors hover:border-primary/40"
                  >
                    <span className={cn("grid size-6 shrink-0 place-items-center rounded-lg border-2 transition-colors", t.done ? "border-primary bg-primary text-primary-foreground" : "border-border text-transparent")}>
                      <Check className="size-3.5" strokeWidth={3} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className={cn("block text-sm font-semibold", t.done && "text-muted-foreground line-through")}>{t.title}</span>
                      <span className={cn("mt-0.5 block text-xs", t.urgent && !t.done ? "font-semibold text-destructive" : "text-muted-foreground")}>{t.due}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </TabsContent>
          <div className="mt-auto pt-5"><Button>Termin planen</Button></div>
        </CardContent>
      </Tabs>
    </Card>
  );
}
