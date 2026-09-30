/* Die Anwendung: Tailwind mit der Petrol-Palette.

   Rundungen, Schatten und Schrift folgen seit dem Redesign (konzept-v8)
   den Tokens der Stilschicht. So sehen die Seiten, die noch Utilities
   tragen, gleich aus wie die, die schon auf fw-Bausteinen stehen:
   `rounded-2xl` ist dieselbe Karte wie `fw-card`. */
module.exports = {
  content: require('./tailwind.inhalt.js'),
  theme: { extend: {
    colors: require('./tailwind.palette.js'),
    borderRadius: { md: '8px', lg: '9px', xl: '12px', '2xl': '12px', '3xl': '16px' },
    boxShadow: {
      sm: 'var(--ds-shadow-sm)', DEFAULT: 'var(--ds-shadow-sm)',
      md: 'var(--ds-shadow)', lg: 'var(--ds-shadow)',
      xl: 'var(--ds-shadow-lg)', '2xl': 'var(--ds-shadow-lg)',
    },
    fontFamily: {
      sans: ['IBM Plex Sans', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
      mono: ['IBM Plex Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
    },
  } },
};
