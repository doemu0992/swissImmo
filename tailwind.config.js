/* Die Anwendung: Tailwind mit der Petrol-Palette. */
module.exports = {
  content: require('./tailwind.inhalt.js'),
  theme: { extend: { colors: require('./tailwind.palette.js') } },
};
