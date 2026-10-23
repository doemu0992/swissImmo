/* Deterministische Schweizer Formatierung (Apostroph als Tausendertrenner) — unabhängig von der ICU-Version. */
export function apos(n: number, decimals = 0): string {
  const neg = n < 0;
  const [int, dec] = Math.abs(n).toFixed(decimals).split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, "'");
  return `${neg ? "−" : ""}${grouped}${dec ? "." + dec : ""}`;
}
export const chf = (n: number, decimals = 0) => `CHF ${apos(n, decimals)}`;

const MONTH_SHORT = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];
export const MONTH_LONG = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];
/** ISO (YYYY-MM-DD) → TT.MM.JJJJ */
export const dmy = (iso: string) => iso.split("-").reverse().join(".");
export const dm = (iso: string) => dmy(iso).slice(0, 5) + ".";
export { MONTH_SHORT };
