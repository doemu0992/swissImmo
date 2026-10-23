import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Stepper } from "@/components/shared/stepper";
import { chf, dmy } from "@/lib/format";
import { DUNNING_CASES, DUNNING_LEVELS, INVOICE_STEPS, NKA_RUNS, NKA_STEPS, PAYABLES } from "@/lib/finance-data";

export function Payables() {
  const open = PAYABLES.filter((p) => p.step < 3).reduce((s, p) => s + p.amount, 0);
  return (
    <div className="flex flex-col gap-5">
      <Card>
        <CardHeader>
          <CardTitle>Rechnungs-Workflow</CardTitle>
          <CardDescription>Jede Lieferantenrechnung durchläuft vier Schritte; Freigabe nach Vier-Augen-Prinzip.</CardDescription>
        </CardHeader>
        <CardContent>
          <Stepper label="Rechnungs-Workflow" current={1} steps={INVOICE_STEPS.map((l, i) => ({ label: l, note: ["Beleg erfasst und Kontierung vorgeschlagen", "Sachlich geprüft durch Bewirtschafter", "Zahlung freigegeben (Vier-Augen)", "Zahlung ausgeführt, Beleg abgelegt"][i] }))} />
          <p className="mt-4 text-xs text-muted-foreground">Beispielrechnung ER-3318 steht aktuell im Schritt «Geprüft».</p>
        </CardContent>
      </Card>
      <Card className="overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b p-4 sm:p-5">
          <div>
            <h3 className="text-lg font-bold">Offene Kreditoren</h3>
            <p className="tabular text-sm text-muted-foreground">{chf(open, 2)} zur Zahlung offen</p>
          </div>
          <Button variant="outline" size="sm">Zahlungslauf (pain.001)</Button>
        </div>
        <Table label="Kreditoren" className="min-w-[900px]">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Beleg</TableHead><TableHead>Lieferant</TableHead><TableHead>Liegenschaft</TableHead><TableHead>Fällig</TableHead>
              <TableHead className="text-right">Betrag</TableHead><TableHead className="min-w-[300px]">Workflow</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {PAYABLES.map((p) => (
              <TableRow key={p.id}>
                <TableCell className="tabular whitespace-nowrap font-semibold text-muted-foreground">{p.id}</TableCell>
                <TableCell><div className="whitespace-nowrap font-bold">{p.supplier}</div><div className="text-xs text-muted-foreground">{p.subject}</div></TableCell>
                <TableCell className="whitespace-nowrap">{p.property}</TableCell>
                <TableCell className="tabular whitespace-nowrap">{dmy(p.due)}</TableCell>
                <TableCell className="tabular whitespace-nowrap text-right font-bold">{chf(p.amount, 2)}</TableCell>
                <TableCell><Stepper compact label={`Workflow ${p.id}`} current={p.step} steps={INVOICE_STEPS.map((l) => ({ label: l }))} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}

export function Dunning() {
  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {DUNNING_LEVELS.map((l) => {
          const n = DUNNING_CASES.filter((c) => c.level === l.level).length;
          return (
            <Card key={l.level} className="p-5">
              <div className="flex items-center justify-between gap-2">
                <Badge variant={l.level === 3 ? "destructive" : l.level === 2 ? "warning" : "secondary"}>Stufe {l.level}</Badge>
                <span className="tabular text-2xl font-extrabold">{n}</span>
              </div>
              <div className="mt-3 font-bold">{l.label}</div>
              <p className="text-xs text-muted-foreground">{l.note}</p>
            </Card>
          );
        })}
      </div>
      <Card className="overflow-hidden">
        <div className="border-b p-4 sm:p-5"><h3 className="text-lg font-bold">Laufende Mahnfälle</h3></div>
        <Table label="Mahnfälle" className="min-w-[860px]">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Fall</TableHead><TableHead>Mieter</TableHead><TableHead>Stufe</TableHead><TableHead className="text-right">Forderung</TableHead>
              <TableHead className="text-right">Gebühr</TableHead><TableHead>Versendet</TableHead><TableHead>Nächster Schritt</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {DUNNING_CASES.map((c) => (
              <TableRow key={c.id}>
                <TableCell className="tabular whitespace-nowrap font-semibold text-muted-foreground">{c.id}</TableCell>
                <TableCell><div className="whitespace-nowrap font-bold">{c.tenant}</div><div className="text-xs text-muted-foreground">{c.property}</div></TableCell>
                <TableCell><Badge variant={c.level === 3 ? "destructive" : c.level === 2 ? "warning" : "secondary"}>Stufe {c.level}</Badge></TableCell>
                <TableCell className="tabular whitespace-nowrap text-right font-bold">{chf(c.amount, 2)}</TableCell>
                <TableCell className="tabular whitespace-nowrap text-right">{c.fee ? chf(c.fee, 2) : "–"}</TableCell>
                <TableCell className="tabular whitespace-nowrap">{dmy(c.sentOn)}</TableCell>
                <TableCell className="whitespace-nowrap text-muted-foreground">{c.next}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}

export function Nka() {
  return (
    <div className="flex flex-col gap-5">
      <Card>
        <CardHeader>
          <CardTitle>Nebenkostenabrechnung 2025</CardTitle>
          <CardDescription>Ablauf pro Liegenschaft. Nach dem Versand läuft eine Einsprachefrist von 30 Tagen.</CardDescription>
        </CardHeader>
        <CardContent><Stepper label="NKA-Workflow" current={3} steps={NKA_STEPS} /></CardContent>
      </Card>
      <Card className="overflow-hidden">
        <div className="border-b p-4 sm:p-5"><h3 className="text-lg font-bold">Abrechnungen je Liegenschaft</h3></div>
        <Table label="Nebenkostenabrechnungen" className="min-w-[900px]">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Liegenschaft</TableHead><TableHead>Periode</TableHead><TableHead className="text-right">Einheiten</TableHead>
              <TableHead className="text-right">Saldo Mieter</TableHead><TableHead className="min-w-[320px]">Stand</TableHead><TableHead>Hinweis</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {NKA_RUNS.map((r) => (
              <TableRow key={r.id}>
                <TableCell><div className="whitespace-nowrap font-bold">{r.property}</div><div className="tabular text-xs text-muted-foreground">{r.id}</div></TableCell>
                <TableCell className="tabular whitespace-nowrap">{r.period}</TableCell>
                <TableCell className="tabular text-right">{r.units}</TableCell>
                <TableCell className="tabular whitespace-nowrap text-right font-bold">
                  {r.balance === 0 ? "–" : chf(r.balance, 2)}
                  {r.balance !== 0 && <div className="text-xs font-medium text-muted-foreground">{r.balance < 0 ? "Nachzahlung" : "Guthaben"}</div>}
                </TableCell>
                <TableCell><Stepper compact label={`Stand ${r.property}`} current={r.step} steps={NKA_STEPS.map((s) => ({ label: s.label }))} /></TableCell>
                <TableCell className="whitespace-nowrap text-muted-foreground">{r.note}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}
