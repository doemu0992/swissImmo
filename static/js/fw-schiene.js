/* Die Schiene (bei jeder Breite; am Telefon nur mit Symbolen): ein Klick auf einen Bereich klappt seine Seiten auf, ein Klick auf eine Seite schliesst
   das Feld wieder. Tastatur: «G» dann H/B/A/K/L/F/R (E = Einstellungen) öffnet den Bereich, 1–9 wählt die Seite im offenen Feld, Esc schliesst.
   Ohne dieses Skript sind die Symbole gewöhnliche Links auf den Bereichskopf (`core/navigation.py`). */
(function () {
    var schiene = document.getElementById('fwSchiene');
    var fach = document.getElementById('fwFach');
    if (!schiene || !fach) return;
    var knoepfe = [].slice.call(schiene.querySelectorAll('[data-fach]'));
    var bereiche = [].slice.call(fach.querySelectorAll('[data-fach-bereich]'));
    var TASTEN = {h: 'heute', b: 'betrieb', a: 'akten', k: 'kontakte', l: 'laeufe', f: 'finanzen', r: 'berichte', e: 'einst'};
    var offen = null;
    // Telefon (bis 640 px): Die Schiene ist eine Schublade, die der Menüknopf der Kopfzeile öffnet.
    var telefon = window.matchMedia ? window.matchMedia('(max-width:640px)') : {matches: false};
    var menue = document.getElementById('fwMenueKnopf');
    var vorhang = document.getElementById('fwSchieneVorhang');
    var zurueck = document.getElementById('fwFachZurueck');
    var schubladeOffen = false;
    function schublade(an, fokus) {
        schubladeOffen = !!an;
        schiene.classList.toggle('offen', schubladeOffen);
        if (vorhang) vorhang.hidden = !schubladeOffen;
        if (menue) menue.setAttribute('aria-expanded', schubladeOffen ? 'true' : 'false');
        if (schubladeOffen) { var e1 = schiene.querySelector('a.hier, [data-fach]'); if (e1) e1.focus({preventScroll: true}); }
        else if (fokus && menue) menue.focus();
    }
    // Handy-Tableiste: «Mehr» öffnet dieselbe Schublade wie der Menüknopf oben.
    var mehr = document.querySelector('[data-tab-mehr]');
    if (mehr) mehr.addEventListener('click', function () { schublade(true); });
    // Summe der roten Zahlen der Bereiche am Menüknopf (die Zahlen holt `fw-rahmen.js` nach dem Laden).
    window.fwMenueSumme = function () {
        var sum = 0, el = document.getElementById('fwMenueSumme');
        if (!el) return;
        [].slice.call(schiene.querySelectorAll('.fw-schiene-zahl:not([hidden])')).forEach(function (z) { sum += parseInt(z.textContent, 10) || 0; });
        el.textContent = sum > 99 ? '99+' : String(sum);
        el.hidden = !sum;
    };
    if (menue) menue.addEventListener('click', function () { schublade(!schubladeOffen, false); });
    if (vorhang) vorhang.addEventListener('click', function () { zu(false); schublade(false, true); });
    if (zurueck) zurueck.addEventListener('click', function () { zu(false); schublade(true); });

    // «Selten gebraucht» nur mit Einträgen; die Zahlen 1–9 stehen an den ersten neun Seiten des Bereichs.
    bereiche.forEach(function (b) {
        var liste = b.querySelector('.fw-fach-selten-liste'), kopf = b.querySelector('.fw-fach-selten');
        if (kopf) kopf.hidden = !(liste && liste.children.length);
        [].slice.call(b.querySelectorAll('ul:not(.fw-fach-selten-liste) kbd')).forEach(function (k, i) {
            if (i < 9) k.textContent = String(i + 1);
        });
    });

    // Breite Navigation (ab 1280 px, Mix-Entwurf): Die Schiene ist eine Spalte mit Beschriftung, und die Seiten des Bereichs, in dem man steht,
    // hängen als Baum darunter (die Abschnitte des Feldes ziehen dorthin um — nichts wird doppelt geführt). «Schmal» stellt die Schiene
    // mit Seitenfeld wieder her. Der Wunsch bleibt im Browser.
    var breit = window.matchMedia ? window.matchMedia('(min-width:1280px)') : {matches: false};
    var festKnopf = schiene.querySelector('[data-schiene-fest]');
    var ausgebreitet = false;
    function breitLesen() { try { return localStorage.getItem('fwSchieneBreit') !== '0'; } catch (e) { return true; } }
    function breitSchreiben(an) { try { localStorage.setItem('fwSchieneBreit', an ? '1' : '0'); } catch (e) { /* ohne Speicher: nur für diese Seite */ } }
    function aktiverBereich() {
        var k = schiene.querySelector('[data-fach][aria-current="page"]');
        return k ? k.getAttribute('data-fach') : null;
    }
    function breitAnwenden(an) {
        var neuAn = !!an && breit.matches;
        if (neuAn === ausgebreitet) { if (festKnopf) festKnopf.setAttribute('aria-pressed', neuAn ? 'true' : 'false'); return; }
        if (offen) { offen = null; fach.hidden = true; knoepfe.forEach(function (k) { k.setAttribute('aria-expanded', 'false'); }); }
        ausgebreitet = neuAn;
        document.documentElement.classList.toggle('fw-breit', ausgebreitet);
        var aktiv = aktiverBereich();
        bereiche.forEach(function (b) {
            var key = b.getAttribute('data-fach-bereich');
            var knopf = schiene.querySelector('[data-fach="' + key + '"]');
            if (ausgebreitet) {
                if (knopf) knopf.insertAdjacentElement('afterend', b);
                b.hidden = key !== aktiv;
            } else {
                fach.insertBefore(b, fach.querySelector('.fw-fach-zuletzt'));
                b.hidden = true;
            }
        });
        if (festKnopf) festKnopf.setAttribute('aria-pressed', ausgebreitet ? 'true' : 'false');
    }

    function zu(zurueck) {
        if (!offen) return;
        var knopf = schiene.querySelector('[data-fach="' + offen + '"]');
        offen = null;
        fach.hidden = true;
        knoepfe.forEach(function (k) { k.setAttribute('aria-expanded', 'false'); });
        if (zurueck && knopf) knopf.focus();
    }
    function auf(key, ohneFokus) {
        var ziel = fach.querySelector('[data-fach-bereich="' + key + '"]');
        if (!ziel) return false;
        bereiche.forEach(function (b) { b.hidden = b !== ziel; });
        knoepfe.forEach(function (k) { k.setAttribute('aria-expanded', k.getAttribute('data-fach') === key ? 'true' : 'false'); });
        fach.hidden = false;
        offen = key;
        var erste = ziel.querySelector('a.hier') || ziel.querySelector('a');
        if (erste && !ohneFokus) erste.focus({preventScroll: true});
        return true;
    }

    knoepfe.forEach(function (k) {
        k.setAttribute('aria-expanded', 'false');
        k.setAttribute('aria-controls', 'fwFach');
        k.addEventListener('click', function (e) {
            var key = k.getAttribute('data-fach');
            if (ausgebreitet) return;   // breit: ein Klick führt auf die Seite des Bereichs, der Baum hängt darunter
            e.preventDefault();
            if (offen === key) zu(true); else auf(key);
        });
    });
    fach.addEventListener('click', function (e) { if (e.target.closest('a')) { zu(false); schublade(false); } });
    document.addEventListener('click', function (e) {
        if (offen && !fach.contains(e.target) && !schiene.contains(e.target) && !(menue && menue.contains(e.target))) zu(false);
    });
    if (telefon.addEventListener) telefon.addEventListener('change', function () { zu(false); schublade(false); });
    if (festKnopf) {
        festKnopf.hidden = false;
        festKnopf.addEventListener('click', function () { var an = !ausgebreitet; breitSchreiben(an); if (!breit.matches) return; breitAnwenden(an); });
        if (breit.addEventListener) breit.addEventListener('change', function () { breitAnwenden(breitLesen()); });
        breitAnwenden(breitLesen());
    }
    var g = false, gZeit = 0;
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && offen) { zu(!telefon.matches); if (telefon.matches) schublade(true); return; }
        if (e.key === 'Escape' && schubladeOffen) { schublade(false, true); return; }
        var t = e.target, tag = t && t.tagName;
        if (e.ctrlKey || e.metaKey || e.altKey) return;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable)) return;
        if (document.querySelector('dialog[open]')) return;
        var k = (e.key || '').toLowerCase();
        if (g && Date.now() - gZeit < 1200) {
            g = false;
            if (ausgebreitet && TASTEN[k]) {
                var ziel = schiene.querySelector('[data-fach="' + TASTEN[k] + '"]');
                if (ziel && ziel.href) { e.preventDefault(); location.href = ziel.href; }
                return;
            }
            if (TASTEN[k] && auf(TASTEN[k])) e.preventDefault();
            return;
        }
        g = false;
        if (k === 'g') { g = true; gZeit = Date.now(); return; }
        var tastenBereich = ausgebreitet ? aktiverBereich() : offen;
        if (tastenBereich && /^[1-9]$/.test(k)) {
            var links = [].slice.call(document.querySelectorAll('[data-fach-bereich="' + tastenBereich + '"] li a'))
                .filter(function (x) { return !x.closest('.fw-fach-selten-liste'); });
            var a = links[+k - 1];
            if (a) { e.preventDefault(); a.click(); if (a.href) location.href = a.href; }
        }
    });
})();

