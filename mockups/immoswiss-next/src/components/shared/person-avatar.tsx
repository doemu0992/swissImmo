import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";

/* Initialen statt Fotos — Mieter- und Mitarbeiterdaten fallen unter das DSG. */
const GRADIENTS = [
  "from-[#35577d] to-[#6e9bd1]",
  "from-[#2f6b5b] to-[#4cc08a]",
  "from-[#6b5530] to-[#d9a548]",
  "from-[#5b3a52] to-[#d98cb7]",
];

export const initials = (name: string) => name.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();

export function PersonAvatar({ name, className }: { name: string; className?: string }) {
  const idx = [...name].reduce((s, c) => s + c.charCodeAt(0), 0) % GRADIENTS.length;
  return (
    <Avatar className={cn("size-8", className)} title={name}>
      <AvatarFallback className={cn("bg-gradient-to-br", GRADIENTS[idx])}>
        <span aria-hidden="true">{initials(name)}</span>
        <span className="sr-only">{name}</span>
      </AvatarFallback>
    </Avatar>
  );
}
