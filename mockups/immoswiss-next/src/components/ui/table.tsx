import * as React from "react";
import { cn } from "@/lib/utils";

/* shadcn/ui Table — der Wrapper scrollt horizontal im eigenen Container (kein Seitenüberlauf). */
const Table = React.forwardRef<HTMLTableElement, React.HTMLAttributes<HTMLTableElement> & { containerClassName?: string; label?: string }>(({ className, containerClassName, label, ...props }, ref) => (
  <div className={cn("relative w-full overflow-x-auto", containerClassName)} role="region" aria-label={label ?? "Tabelle"} tabIndex={0}>
    <table ref={ref} className={cn("w-full caption-bottom border-collapse text-sm", className)} {...props} />
  </div>
));
Table.displayName = "Table";

const TableHeader = React.forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(({ className, ...props }, ref) => (
  <thead ref={ref} className={cn("[&_tr]:border-b", className)} {...props} />
));
TableHeader.displayName = "TableHeader";

const TableBody = React.forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(({ className, ...props }, ref) => (
  <tbody ref={ref} className={cn("[&_tr:last-child]:border-0", className)} {...props} />
));
TableBody.displayName = "TableBody";

const TableRow = React.forwardRef<HTMLTableRowElement, React.HTMLAttributes<HTMLTableRowElement>>(({ className, ...props }, ref) => (
  <tr ref={ref} className={cn("border-b transition-colors hover:bg-accent/40 data-[state=selected]:bg-accent/60", className)} {...props} />
));
TableRow.displayName = "TableRow";

const TableHead = React.forwardRef<HTMLTableCellElement, React.ThHTMLAttributes<HTMLTableCellElement>>(({ className, ...props }, ref) => (
  <th ref={ref} className={cn("h-12 whitespace-nowrap px-4 text-left align-middle text-xs font-bold uppercase tracking-wider text-muted-foreground", className)} {...props} />
));
TableHead.displayName = "TableHead";

const TableCell = React.forwardRef<HTMLTableCellElement, React.TdHTMLAttributes<HTMLTableCellElement>>(({ className, ...props }, ref) => (
  <td ref={ref} className={cn("px-4 py-3.5 align-middle", className)} {...props} />
));
TableCell.displayName = "TableCell";

export { Table, TableHeader, TableBody, TableRow, TableHead, TableCell };
