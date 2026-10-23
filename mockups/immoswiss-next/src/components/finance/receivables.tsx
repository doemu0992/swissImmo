"use client";

import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Download, FileSpreadsheet, FileText, FileType, Mail, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { apos, chf, dmy } from "@/lib/format";
import { RECEIVABLES, RECEIVABLE_PROPERTIES, STATUS_META, type Receivable, type ReceivableStatus } from "@/lib/finance-data";
import { cn } from "@/lib/utils";

/** Ampel: Punkt PLUS Text — nie nur Farbe. */
export function StatusLight({ status, extra }: { status: ReceivableStatus; extra?: string }) {
  const m = STATUS_META[status];
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap text-sm font-semibold">
      <span className={cn("size-2.5 rounded-full", m.dot)} aria-hidden="true" />
      {m.label}
      {extra && <span className="text-xs font-medium text-muted-foreground">· {extra}</span>}
    </span>
  );
}

type SortKey = "id" | "tenant" | "property" | "due" | "amount" | "dunning" | "status";
const STATUS_ORDER: Record<ReceivableStatus, number> = { ueberfaellig: 0, offen: 1, bezahlt: 2 };
const PAGE_SIZE = 10;

const COLUMNS: { key: SortKey; label: string; align?: "right" }[] = [
  { key: "id", label: "Rechnung" },
  { key: "tenant", label: "Mieter" },
  { key: "property", label: "Liegenschaft" },
  { key: "due", label: "Fällig" },
  { key: "amount", label: "Betrag", align: "right" },
  { key: "dunning", label: "Mahnstufe" },
  { key: "status", label: "Status" },
];

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub: string; tone?: "bad" | "good" }) {
  return (
    <Card className={cn("min-w-0 p-4 sm:p-5", tone === "bad" && "border-destructive/40 from-destructive/10 to-card/80")}>
      <div className="text-sm font-medium text-muted-foreground">{label}</div>
      <div className={cn("tabular mt-1 whitespace-nowrap text-xl font-extrabold tracking-tight sm:text-2xl", tone === "bad" && "text-destructive")}>{value}</div>
      <div className="mt-1 text-xs text-muted-foreground">{sub}</div>
    </Card>
  );
}

export function Receivables() {
  const [status, setStatus] = useState<"alle" | ReceivableStatus>("alle");
  const [query, setQuery] = useState("");
  const [property, setProperty] = useState("");
  const [arrearsOnly, setArrearsOnly] = useState(false);
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "due", dir: "asc" });
  const [selected, setSelected] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const [notice, setNotice] = useState("");

  const kpi = useMemo(() => {
    const open = RECEIVABLES.filter((r) => r.status !== "bezahlt");
    const over = RECEIVABLES.filter((r) => r.status === "ueberfaellig");
    const l3 = RECEIVABLES.filter((r) => r.dunning === 3);
    const sum = (a: Receivable[]) => a.reduce((s, r) => s + r.amount, 0);
    const billed = RECEIVABLES.filter((r) => r.due <= "2026-10-31");
    const rate = (sum(billed.filter((r) => r.status === "bezahlt")) / sum(billed)) * 100;
    return { open: sum(open), openN: open.length, over: sum(over), overN: over.length, l3N: l3.length, l3: sum(l3), rate };
  }, []);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const f = RECEIVABLES.filter((r) => {
      if (arrearsOnly && r.status !== "ueberfaellig") return false;
      if (status !== "alle" && r.status !== status) return false;
      if (property && r.property !== property) return false;
      if (q && !`${r.id} ${r.tenant} ${r.unit} ${r.property}`.toLowerCase().includes(q)) return false;
      return true;
    });
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...f].sort((a, b) => {
      const va = sort.key === "status" ? STATUS_ORDER[a.status] : a[sort.key];
      const vb = sort.key === "status" ? STATUS_ORDER[b.status] : b[sort.key];
      return (typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb), "de")) * dir;
    });
  }, [status, query, property, arrearsOnly, sort]);

  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const cur = Math.min(page, pages);
  const pageRows = rows.slice((cur - 1) * PAGE_SIZE, cur * PAGE_SIZE);
  const allOnPage = pageRows.length > 0 && pageRows.every((r) => selected.includes(r.id));
  const reset = () => setPage(1);

  const toggleSort = (key: SortKey) => setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }));
  const toggleRow = (id: string) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const togglePage = () => setSelected((s) => (allOnPage ? s.filter((id) => !pageRows.some((r) => r.id === id)) : [...new Set([...s, ...pageRows.map((r) => r.id)])]));

  const CHIPS: { id: "alle" | ReceivableStatus; label: string }[] = [
    { id: "alle", label: "Alle" },
    { id: "bezahlt", label: "Bezahlt" },
    { id: "offen", label: "Offen" },
    { id: "ueberfaellig", label: "Überfällig" },
  ];

  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <Kpi label="Offen total" value={chf(kpi.open)} sub={`${kpi.openN} Rechnungen`} />
        <Kpi label="Überfällig" value={chf(kpi.over)} sub={`${kpi.overN} Rechnungen`} tone="bad" />
        <Kpi label="Mahnstufe 3" value={`${kpi.l3N} Fälle`} sub={`${chf(kpi.l3)} · Betreibung prüfen`} tone="bad" />
        <Kpi label="Zahlungsquote Oktober" value={`${apos(kpi.rate, 1)} %`} sub="bezahlt von fakturiert" />
      </div>

      <Card className="overflow-hidden">
        {/* Filter */}
        <div className="flex flex-col gap-3 border-b p-4 sm:p-5">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
            <label className="relative w-full lg:max-w-xs">
              <span className="sr-only">Debitoren durchsuchen</span>
              <Search className="pointer-events-none absolute left-3.5 top-1/2 size-[18px] -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
              <Input type="search" value={query} onChange={(e) => { setQuery(e.target.value); reset(); }} placeholder="Mieter oder Rechnung …" className="pl-10" />
            </label>
            <div className="w-full lg:w-60">
              <label className="sr-only" htmlFor="deb-prop">Liegenschaft</label>
              <Select id="deb-prop" value={property} onChange={(e) => { setProperty(e.target.value); reset(); }}>
                <option value="">Alle Liegenschaften</option>
                {RECEIVABLE_PROPERTIES.map((p) => <option key={p}>{p}</option>)}
              </Select>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 lg:ml-auto">
              <button
                type="button"
                role="switch"
                aria-checked={arrearsOnly}
                onClick={() => { setArrearsOnly((v) => !v); reset(); }}
                className="flex items-center gap-2.5 whitespace-nowrap rounded-xl py-1 text-sm font-semibold"
              >
                <span className={cn("relative h-6 w-11 rounded-full border transition-colors", arrearsOnly ? "border-primary bg-primary" : "bg-secondary")} aria-hidden="true">
                  <span className={cn("absolute top-0.5 size-4 rounded-full bg-white shadow transition-all", arrearsOnly ? "left-[22px]" : "left-0.5")} />
                </span>
                Nur Zahlungsrückstände
              </button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline"><Download /> Export</Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuLabel>Exportieren als</DropdownMenuLabel>
                  <DropdownMenuItem onSelect={() => setNotice("CSV-Export vorbereitet (Mockup).")}><FileText /> CSV</DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => setNotice("Excel-Export vorbereitet (Mockup).")}><FileSpreadsheet /> Excel (.xlsx)</DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => setNotice("PDF-Export vorbereitet (Mockup).")}><FileType /> PDF</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Statusfilter">
            {CHIPS.map((c) => (
              <button
                key={c.id}
                type="button"
                aria-pressed={status === c.id}
                onClick={() => { setStatus(c.id); reset(); }}
                className={cn("inline-flex h-9 items-center gap-2 rounded-full border px-3.5 text-sm font-semibold transition-colors", status === c.id ? "border-primary bg-primary/15 text-primary" : "bg-card/60 text-muted-foreground hover:bg-accent hover:text-foreground")}
              >
                {c.id !== "alle" && <span className={cn("size-2 rounded-full", STATUS_META[c.id].dot)} aria-hidden="true" />}
                {c.label}
              </button>
            ))}
          </div>
        </div>

        {/* Sammelaktionen */}
        {(selected.length > 0 || notice) && (
          <div className="flex flex-wrap items-center gap-3 border-b bg-accent/40 px-4 py-3 sm:px-5" role="status">
            {selected.length > 0 && <span className="text-sm font-bold">{selected.length} ausgewählt</span>}
            {selected.length > 0 && (
              <>
                <Button size="sm" onClick={() => setNotice(`Mahnung für ${selected.length} Rechnungen vorbereitet (Mockup).`)}><Mail /> Mahnung versenden</Button>
                <Button size="sm" variant="outline" onClick={() => setNotice(`${selected.length} Rechnungen zum Export vorgemerkt (Mockup).`)}><Download /> Exportieren</Button>
                <Button size="sm" variant="ghost" onClick={() => setSelected([])}>Auswahl aufheben</Button>
              </>
            )}
            {notice && <span className="ml-auto text-sm text-muted-foreground">{notice}</span>}
          </div>
        )}

        <Table label="Debitoren" className="min-w-[960px]">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-12 pr-0">
                <input type="checkbox" className="size-4 cursor-pointer accent-[hsl(var(--primary))]" checked={allOnPage} onChange={togglePage} aria-label="Alle Zeilen dieser Seite auswählen" />
              </TableHead>
              {COLUMNS.map((c) => {
                const on = sort.key === c.key;
                const Icon = !on ? ArrowUpDown : sort.dir === "asc" ? ArrowUp : ArrowDown;
                return (
                  <TableHead key={c.key} aria-sort={on ? (sort.dir === "asc" ? "ascending" : "descending") : "none"} className={c.align === "right" ? "text-right" : undefined}>
                    <button type="button" onClick={() => toggleSort(c.key)} className={cn("inline-flex items-center gap-1.5 rounded-md uppercase tracking-wider hover:text-foreground", on && "text-foreground", c.align === "right" && "flex-row-reverse")}>
                      {c.label}
                      <Icon className="size-3.5" aria-hidden="true" />
                      <span className="sr-only">sortieren</span>
                    </button>
                  </TableHead>
                );
              })}
            </TableRow>
          </TableHeader>
          <TableBody>
            {pageRows.map((r) => (
              <TableRow key={r.id} data-state={selected.includes(r.id) ? "selected" : undefined}>
                <TableCell className="w-12 pr-0">
                  <input type="checkbox" className="size-4 cursor-pointer accent-[hsl(var(--primary))]" checked={selected.includes(r.id)} onChange={() => toggleRow(r.id)} aria-label={`Rechnung ${r.id} von ${r.tenant} auswählen`} />
                </TableCell>
                <TableCell className="tabular whitespace-nowrap font-semibold text-muted-foreground">{r.id}</TableCell>
                <TableCell className="whitespace-nowrap font-bold">{r.tenant}</TableCell>
                <TableCell className="whitespace-nowrap">
                  {r.property}
                  <div className="text-xs text-muted-foreground">{r.unit}</div>
                </TableCell>
                <TableCell className="tabular whitespace-nowrap">{dmy(r.due)}</TableCell>
                <TableCell className="tabular whitespace-nowrap text-right font-bold">{chf(r.amount, 2)}</TableCell>
                <TableCell>
                  {r.dunning ? <Badge variant={r.dunning === 3 ? "destructive" : r.dunning === 2 ? "warning" : "secondary"}>Stufe {r.dunning}</Badge> : <span className="text-muted-foreground">–<span className="sr-only">keine Mahnung</span></span>}
                </TableCell>
                <TableCell><StatusLight status={r.status} extra={r.overdueDays ? `${r.overdueDays} Tage` : undefined} /></TableCell>
              </TableRow>
            ))}
            {pageRows.length === 0 && (
              <TableRow><TableCell colSpan={8} className="py-12 text-center text-muted-foreground">Keine Rechnungen für diese Filter.</TableCell></TableRow>
            )}
          </TableBody>
        </Table>

        {/* Pagination */}
        <nav aria-label="Seitenwahl" className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3.5 sm:px-5">
          <p className="tabular text-sm text-muted-foreground" aria-live="polite">
            {rows.length ? `${(cur - 1) * PAGE_SIZE + 1}–${Math.min(cur * PAGE_SIZE, rows.length)} von ${rows.length} Rechnungen` : "0 Rechnungen"}
          </p>
          <div className="flex items-center gap-1.5">
            <Button variant="outline" size="icon" className="size-9" disabled={cur === 1} onClick={() => setPage(cur - 1)} aria-label="Vorherige Seite"><ChevronLeft /></Button>
            {Array.from({ length: pages }, (_, i) => i + 1).map((n) => (
              <Button key={n} variant={n === cur ? "default" : "ghost"} size="icon" className="size-9" onClick={() => setPage(n)} aria-label={`Seite ${n}`} aria-current={n === cur ? "page" : undefined}>{n}</Button>
            ))}
            <Button variant="outline" size="icon" className="size-9" disabled={cur === pages} onClick={() => setPage(cur + 1)} aria-label="Nächste Seite"><ChevronRight /></Button>
          </div>
        </nav>
      </Card>
    </div>
  );
}
