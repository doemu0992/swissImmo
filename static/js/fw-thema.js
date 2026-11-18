/* Hell/Dunkel-Umschalter — bis 15.11.2026 als Inline-Skript in `core/templates/fw/base.html`.
   Als Datei, damit der Browser es zwischenspeichert statt es mit jeder Seite neu zu laden (Audit P15).
   Texte und Schalter der Seite kommen aus dem Datenblock `#fw-rahmen-daten` (siehe base.html). */
// Hell/Dunkel-Umschalter (persistiert pro Browser via localStorage)
function fwSetTheme(t){
    document.documentElement.setAttribute('data-theme', t);
    try { localStorage.setItem('fw-theme', t); } catch(e){}
    fwSyncThemeButtons();
}
// Der runde Knopf in der Kopfzeile: wechselt vom gerade sichtbaren Modus in
// den anderen — auch wenn der sichtbare aus der Systemeinstellung kommt.
function fwThemeWechseln(){
    var r = document.documentElement.getAttribute('data-theme');
    var jetzt = r || (window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    fwSetTheme(jetzt === 'dark' ? 'light' : 'dark');
}
function fwSyncThemeButtons(){
    var cur = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
    document.querySelectorAll('[data-theme-btn]').forEach(function(b){
        b.classList.toggle('an', b.getAttribute('data-theme-btn') === cur);
    });
}
fwSyncThemeButtons();
