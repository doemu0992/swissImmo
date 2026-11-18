/* Die Schiene (bei jeder Breite; am Telefon nur mit Symbolen): ein Klick auf einen Bereich klappt seine Seiten auf, ein Klick auf eine Seite schliesst
   das Feld wieder. Tastatur: «G» dann H/B/A/L/F/R (E = Einstellungen) öffnet den Bereich, 1–9 wählt die Seite im offenen Feld, Esc schliesst.
   Ohne dieses Skript sind die Symbole gewöhnliche Links auf den Bereichskopf (`core/navigation.py`). */
(function () {
    var schiene = document.getElementById('fwSchiene');
    var fach = document.getElementById('fwFach');
    if (!schiene || !fach) return;
    var knoepfe = [].slice.call(schiene.querySelectorAll('[data-fach]'));
    var bereiche = [].slice.call(fach.querySelectorAll('[data-fach-bereich]'));
    var TASTEN = {h: 'heute', b: 'betrieb', a: 'akten', l: 'laeufe', f: 'finanzen', r: 'berichte', e: 'einst'};
    var offen = null;

    // «Selten gebraucht» nur mit Einträgen; die Zahlen 1–9 stehen an den ersten neun Seiten des Bereichs.
    bereiche.forEach(function (b) {
        var liste = b.querySelector('.fw-fach-selten-liste'), kopf = b.querySelector('.fw-fach-selten');
        if (kopf) kopf.hidden = !(liste && liste.children.length);
        [].slice.call(b.querySelectorAll('ul:not(.fw-fach-selten-liste) kbd')).forEach(function (k, i) {
            if (i < 9) k.textContent = String(i + 1);
        });
    });

    function zu(zurueck) {
        if (!offen) return;
        var knopf = schiene.querySelector('[data-fach="' + offen + '"]');
        offen = null;
        fach.hidden = true;
        knoepfe.forEach(function (k) { k.setAttribute('aria-expanded', 'false'); });
        if (zurueck && knopf) knopf.focus();
    }
    function auf(key) {
        var ziel = fach.querySelector('[data-fach-bereich="' + key + '"]');
        if (!ziel) return false;
        bereiche.forEach(function (b) { b.hidden = b !== ziel; });
        knoepfe.forEach(function (k) { k.setAttribute('aria-expanded', k.getAttribute('data-fach') === key ? 'true' : 'false'); });
        fach.hidden = false;
        offen = key;
        var erste = ziel.querySelector('a.hier') || ziel.querySelector('a');
        if (erste) erste.focus({preventScroll: true});
        return true;
    }

    knoepfe.forEach(function (k) {
        k.setAttribute('aria-expanded', 'false');
        k.setAttribute('aria-controls', 'fwFach');
        k.addEventListener('click', function (e) {
            var key = k.getAttribute('data-fach');
            e.preventDefault();
            if (offen === key) zu(true); else auf(key);
        });
    });
    fach.addEventListener('click', function (e) { if (e.target.closest('a')) zu(false); });
    document.addEventListener('click', function (e) {
        if (offen && !fach.contains(e.target) && !schiene.contains(e.target)) zu(false);
    });
    var g = false, gZeit = 0;
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && offen) { zu(true); return; }
        var t = e.target, tag = t && t.tagName;
        if (e.ctrlKey || e.metaKey || e.altKey) return;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable)) return;
        if (document.querySelector('dialog[open]')) return;
        var k = (e.key || '').toLowerCase();
        if (g && Date.now() - gZeit < 1200) {
            g = false;
            if (TASTEN[k] && auf(TASTEN[k])) e.preventDefault();
            return;
        }
        g = false;
        if (k === 'g') { g = true; gZeit = Date.now(); return; }
        if (offen && /^[1-9]$/.test(k)) {
            var links = [].slice.call(fach.querySelectorAll('[data-fach-bereich="' + offen + '"] li a'))
                .filter(function (x) { return !x.closest('.fw-fach-selten-liste'); });
            var a = links[+k - 1];
            if (a) { e.preventDefault(); a.click(); if (a.href) location.href = a.href; }
        }
    });
})();

