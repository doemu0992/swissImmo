import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

/* Farben sind Tokens (src/app/globals.css) — shadcn/ui-Konvention: HSL-Kanäle in CSS-Variablen.
   60-30-10: 60 % Navy-Flächen (background/card), 30 % Strukturblau (border, secondary, brand),
   10 % Akzent (primary) und Zustandsfarben (success/warning/destructive). */
const config: Config = {
  darkMode: ["class"],
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    container: { center: true, padding: "1rem", screens: { "2xl": "1480px" } },
    extend: {
      fontFamily: { sans: ["Plus Jakarta Sans", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"] },
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        secondary: { DEFAULT: "hsl(var(--secondary))", foreground: "hsl(var(--secondary-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
        popover: { DEFAULT: "hsl(var(--popover))", foreground: "hsl(var(--popover-foreground))" },
        brand: { DEFAULT: "hsl(var(--brand))", foreground: "hsl(var(--brand-foreground))" },
        success: "hsl(var(--success))",
        warning: "hsl(var(--warning))",
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
      },
      borderRadius: { lg: "var(--radius)", md: "calc(var(--radius) - 4px)", sm: "calc(var(--radius) - 8px)", "3xl": "1.5rem" },
      boxShadow: {
        card: "var(--shadow-card)",
        pop: "var(--shadow-pop)",
        glow: "0 10px 28px -12px hsl(var(--primary) / .55)",
      },
    },
  },
  plugins: [animate],
};
export default config;
