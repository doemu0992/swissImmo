/* Rahmen der Anwendung: Leiste, Zahlen, Modal, Tabellen, Spaltenfilter — bis 15.11.2026 als Inline-Skript in `core/templates/fw/base.html`.
   Als Datei, damit der Browser es zwischenspeichert statt es mit jeder Seite neu zu laden (Audit P15).
   Texte und Schalter der Seite kommen aus dem Datenblock `#fw-rahmen-daten` (siehe base.html). */
var FW_RAHMEN = (function () {
    try { return JSON.parse(document.getElementById('fw-rahmen-daten').textContent); }
    catch (e) { return {kopfReduziert: true, filter: {ph: '', alle: '', stand: '%(n)s / %(m)s', reset: '', spalte: ''}}; }
})();
// Leiste ein-/ausklappen (Zustand in localStorage)
function fwToggleSidebar() {
    var collapsed = document.documentElement.classList.toggle('_sbc');
    localStorage.setItem('sbCollapsed', collapsed ? '1' : '0');
}

// Leiste am Telefon als Schublade öffnen/schliessen
function fwOpenMobileNav() {
    document.getElementById('fwSidebar').classList.add('offen');
    document.getElementById('fwBackdrop').classList.remove('hidden');
    fwStil(document.body, {overflow: 'hidden'});
}
function fwCloseMobileNav() {
    document.getElementById('fwSidebar').classList.remove('offen');
    document.getElementById('fwBackdrop').classList.add('hidden');
    fwStil(document.body, {overflow: null});
}
// ESC schliesst die Schublade
document.addEventListener('keydown', function(e){ if (e.key === 'Escape') fwCloseMobileNav(); });

// Navigationsgruppe auf-/zuklappen
function fwNavToggle(key) {
    var grp = document.getElementById('navgrp-' + key);
    var sub = document.getElementById('navsub-' + key);
    if (!grp || !sub) return;
    sub.classList.toggle('hidden');
    grp.classList.toggle('nav-open', !sub.classList.contains('hidden'));
}

// ─── Zahlen in der Leiste (konzept-v8) ───
// Nach dem Seitenaufbau geholt, damit keine Seite auf den Arbeitsvorrat wartet.
(function () {
    if (document.documentElement.classList.contains('_embed')) return;
    if (FW_RAHMEN.kopfReduziert) return;   // Hauswartung und Portal-Rollen dürfen die Zahlen nicht abfragen (403 im Hintergrund)
    fetch('/neu/leistenzahlen/', {headers: {'X-Requested-With': 'fetch'}, credentials: 'same-origin'})
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (z) {
            if (!z) return;
            document.querySelectorAll('[data-zaehler]').forEach(function (el) {
                var n = z[el.getAttribute('data-zaehler')];
                if (n) { if (el.classList.contains('fw-pip')) { el.hidden = false; }
                         else { el.textContent = n; el.hidden = false; } }
            });
        }).catch(function () {});
})();

// ─── Zuletzt geöffnet (konzept-v8) ───
// Nur im Browser dieser Person, nur Akten. Drei Einträge, der neueste oben.
(function () {
    var MUSTER = /^\/neu\/(liegenschaften|objekte|vertraege|personen|mandate|faelle|schaeden|dienstleister)\/\d+\/$/;
    var liste = [];
    // Je Person UND Verwaltung: am geteilten PC oder nach dem Mandantenwechsel stehen keine fremden Akten darin (Audit K3).
    var SCHLUESSEL = (typeof FW_RAHMEN !== 'undefined' && FW_RAHMEN.zuletztSchluessel) || 'fw-zuletzt';
    try { liste = JSON.parse(localStorage.getItem(SCHLUESSEL) || '[]') || []; } catch (e) {}
    if (MUSTER.test(location.pathname) && !document.documentElement.classList.contains('_embed')) {
        var h = document.querySelector('.fw-aktenkopf h1, .fw-phead h1, main h1');
        var titel = h ? h.textContent.replace(/\s+/g, ' ').trim() : '';
        if (titel) {
            liste = [{h: location.pathname, l: titel}].concat(
                liste.filter(function (x) { return x.h !== location.pathname; })).slice(0, 3);
            try { localStorage.setItem(SCHLUESSEL, JSON.stringify(liste)); } catch (e) {}
        }
    }
    if (!liste.length) return;
    function kurz(s) { return s.split(/[\s·,-]+/).filter(function (w) { return /^[A-Za-zÀ-ÿ]/.test(w); })
                               .slice(0, 2).map(function (w) { return w[0]; }).join('').toUpperCase(); }
    // Dieselbe Liste an zwei Orten: in der Schublade und im Profilmenü (am PC ist die Schublade aus).
    // [Liste, Titel bzw. Abschnitt, der erst mit Einträgen erscheint]
    [['fwZuletzt', 'fwZuletztTitel'], ['fwZuletztProfil', 'fwZuletztProfilAbschnitt'], ['fwZuletztFach', 'fwZuletztFachAbschnitt']].forEach(function (p) {
        var ziel = document.getElementById(p[0]);
        if (!ziel) return;
        liste.forEach(function (x) {
            var a = document.createElement('a');
            a.href = x.h; a.className = 'fw-nav-eintrag fw-zuletzt-eintrag' + (x.h === location.pathname ? ' hier' : '');
            var k = document.createElement('span'); k.className = 'fw-avatar fw-avatar-klein'; k.textContent = kurz(x.l);
            var t = document.createElement('span'); t.className = 'truncate'; t.textContent = x.l;
            a.appendChild(k); a.appendChild(t); ziel.appendChild(a);
        });
        var titel = document.getElementById(p[1]);
        if (titel) titel.hidden = false;
    });
})();

// Die Bereichs-Kapsel oben: Ränder zeigen, wenn sie weiterläuft (Telefon, ab 901 px
// bei sehr schmalem Fenster). Das Menüband darunter macht `static/js/fw-menueband.js`.
(function () {
    var kapsel = document.getElementById('fwHauptnav');
    if (!kapsel) return;
    var kr = function () { var m = kapsel.scrollWidth - kapsel.clientWidth;
        kapsel.classList.toggle('rand-l', m > 1 && kapsel.scrollLeft > 2);
        kapsel.classList.toggle('rand-r', m > 1 && kapsel.scrollLeft < m - 2); };
    kr(); kapsel.addEventListener('scroll', kr, { passive: true }); window.addEventListener('resize', kr);
    setTimeout(kr, 400);
})();

// Profilmenü öffnen/schliessen
function fwProfilMenu() {
    var m = document.getElementById('fwProfil');
    if (m) m.classList.toggle('hidden');
}
document.addEventListener('click', function(e) {
    var m = document.getElementById('fwProfil');
    if (!m || m.classList.contains('hidden')) return;
    // Klick ausserhalb von Menü + Auslöser schliesst
    if (!m.contains(e.target) && !e.target.closest('button[data-bei-klick="fwProfilMenu"]')) {
        m.classList.add('hidden');
    }
});
document.addEventListener('keydown', function(e) {
    var m = document.getElementById('fwProfil');
    if (e.key === 'Escape' && m) m.classList.add('hidden');
});

// Menü öffnen (Telefon): Profilmenü umschalten und Seitenleiste aufklappen
function fwMenueOeffnen() { fwProfilMenu(); fwOpenMobileNav(); }
// Reiter wechseln und zu seiner Fläche scrollen (Verweise wie «Zum Konto»); `false` hält den Link an
function fwTabSpringen(gruppe, name) {
    fwTab(gruppe, name);
    var z = document.getElementById(gruppe + '-' + name);
    if (z) z.scrollIntoView({behavior: 'smooth', block: 'start'});
    return false;
}
// Generische Tab-Umschaltung für Detailseiten:
// Buttons: data-tab="<gruppe>" data-target="<name>"; Panels: id="<gruppe>-<name>"
function fwTab(gruppe, name) {
    document.querySelectorAll('[data-panel="' + gruppe + '"]').forEach(function(p) {
        p.classList.toggle('hidden', p.id !== gruppe + '-' + name);
    });
    document.querySelectorAll('[data-tab="' + gruppe + '"]').forEach(function(b) {
        var aktiv = b.dataset.target === name;
        // `hier` ist die Klasse der Reiterleiste (`fw-reiter`, Tokens). Die
        // alte Tailwind-Leiste gibt es nicht mehr (Production-Check 26.10.2026).
        b.classList.toggle('hier', aktiv);
        // Reiter-Schema (WAI-ARIA): ausgewählt + als einziger per Tab erreichbar, Pfeiltasten wechseln.
        b.setAttribute('aria-selected', aktiv ? 'true' : 'false');
        b.tabIndex = aktiv ? 0 : -1;
    });
}
// Die Flächen der Reiter bekommen Rolle und Bezug zum Reiter, ohne dass jede Vorlage es einzeln tragen muss.
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('[data-panel]').forEach(function(p) {
        p.setAttribute('role', 'tabpanel');
        var t = document.getElementById('tab-' + p.id);
        if (t) p.setAttribute('aria-labelledby', t.id);
    });
});
document.addEventListener('keydown', function(e) {
    var b = e.target && e.target.closest ? e.target.closest('[role="tab"][data-tab]') : null;
    if (!b || ['ArrowRight', 'ArrowLeft', 'Home', 'End'].indexOf(e.key) < 0) return;
    var alle = Array.prototype.slice.call(b.parentNode.querySelectorAll('[role="tab"][data-tab]'));
    var i = alle.indexOf(b);
    var j = e.key === 'Home' ? 0 : e.key === 'End' ? alle.length - 1
          : (i + (e.key === 'ArrowRight' ? 1 : -1) + alle.length) % alle.length;
    e.preventDefault();
    alle[j].focus();
    alle[j].click();
});

// Deep-Link: ?tab=<name> aktiviert beim Laden den passenden Tab
document.addEventListener('DOMContentLoaded', function() {
    try {
        var t = new URLSearchParams(window.location.search).get('tab');
        if (!t) return;
        var btn = document.querySelector('[data-tab][data-target="' + t + '"]');
        if (btn) fwTab(btn.dataset.tab, t);
    } catch (e) {}
});

// Globaler Submit-Guard: verhindert Doppel-Submits (z.B. GWR-Import, Buchungen).
// Beim Absenden wird der Submit-Button deaktiviert und zeigt einen Spinner;
// Formulare mit data-no-guard sind ausgenommen (z.B. target=_blank-PDFs).
document.addEventListener('submit', function(e) {
    var form = e.target;
    if (!(form instanceof HTMLFormElement) || form.hasAttribute('data-no-guard')
        || form.target === '_blank') return;
    var btn = form.querySelector('button[type="submit"], button:not([type])');
    if (!btn || btn.disabled) return;
    setTimeout(function() {                       // erst NACH dem Submit deaktivieren
        btn.disabled = true;
        btn.classList.add('opacity-60', 'cursor-wait');
        // SEIT E2.39 GIBT ES KEIN `<i class="fa-…">` MEHR.
        //
        // Die Knoepfe tragen `<svg class="fw-zeichen">`; das Zeichen wird
        // gegen den drehenden Kreis getauscht.
        var ic = btn.querySelector('svg.fw-zeichen use');
        if (ic) { ic.setAttribute('href', '#z-laedt');
                  ic.parentNode.classList.add('fw-dreht'); }
    }, 0);
    // Sicherheitsnetz: nach 15 s wieder aktivieren (z.B. Validierungsfehler ohne Reload)
    setTimeout(function() {
        btn.disabled = false;
        btn.classList.remove('opacity-60', 'cursor-wait');
    }, 15000);
});

// Generischer Live-Filter für Listen: <input data-suche="#tbodyId"> filtert
// Zeilen der Ziel-Tabelle beim Tippen (Suchtext gegen Zeilentext).
document.addEventListener('input', function(e) {
    var inp = e.target;
    if (!inp.matches || !inp.matches('[data-suche]')) return;
    var ziel = document.querySelector(inp.dataset.suche);
    if (!ziel) return;
    var q = (inp.value || '').toLowerCase();
    ziel.querySelectorAll('[data-zeile]').forEach(function(tr) {
        tr.classList.toggle('hidden', q && tr.textContent.toLowerCase().indexOf(q) === -1);
    });
});

// Globales "⋯ Mehr"-Dropdown: Markup ohne eigenes Script.
//   <div class="relative" data-menu>
//     <button data-menu-btn aria-haspopup="menu" aria-expanded="false">… Mehr</button>
//     <div data-menu-list role="menu" class="hidden absolute …">…Aktionen…</div>
//   </div>
// Seit dem UI-Audit (26.10.2026) laufen ALLE Aktionsmenüs hierüber — vorher hatten
// acht Akten ein eigenes onclick + Schliess-Skript und waren am Telefon und Tablet
// rechtsbündig verankert: Das Menü ragte links aus dem Bild, kein Eintrag war
// erreichbar. Jetzt passt `fwMenuEinpassen` das offene Menü in den Bildschirm ein,
// Escape und ein Klick daneben schliessen, Pfeiltasten führen durch die Einträge.
function fwMenuEinpassen(list) {
    // Links endet der freie Bereich an der Schiene (sie liegt über dem Inhalt): Einträge darunter wären nicht klickbar.
    var schiene = document.getElementById('fwSchiene');
    var links = schiene && schiene.offsetWidth ? schiene.getBoundingClientRect().right : 0;
    fwStil(list, {transform: null, maxWidth: (innerWidth - links - 24) + 'px'});
    var r = list.getBoundingClientRect(), rand = 12, dx = 0;
    if (r.right > innerWidth - rand) dx = innerWidth - rand - r.right;
    if (r.left + dx < links + rand) dx = links + rand - r.left;
    if (dx) fwStil(list, {transform: 'translateX(' + Math.round(dx) + 'px)'});
    // Unten kein Platz, oben schon → nach oben aufklappen
    list.classList.remove('fw-menu-oben');
    if (r.bottom > innerHeight - rand && r.top - r.height - 48 > rand) list.classList.add('fw-menu-oben');
}
function fwMenuZu(list) {
    if (!list || list.classList.contains('hidden')) return;
    list.classList.add('hidden');
    var wrap = list.closest('[data-menu]'), btn = wrap && wrap.querySelector('[data-menu-btn]');
    if (btn) btn.setAttribute('aria-expanded', 'false');
}
document.addEventListener('click', function(ev) {
    var btn = ev.target.closest ? ev.target.closest('[data-menu-btn]') : null;
    if (btn) {
        ev.preventDefault();
        var wrap = btn.closest('[data-menu]');
        var list = wrap && wrap.querySelector('[data-menu-list]');
        if (!list) return;
        var willOpen = list.classList.contains('hidden');
        document.querySelectorAll('[data-menu-list]').forEach(fwMenuZu);
        if (willOpen) {
            list.classList.remove('hidden');
            btn.setAttribute('aria-expanded', 'true');
            fwMenuEinpassen(list);
        }
        return;
    }
    document.querySelectorAll('[data-menu-list]:not(.hidden)').forEach(function(l) {
        var wrap = l.closest('[data-menu]');
        if (wrap && !wrap.contains(ev.target)) fwMenuZu(l);
    });
});
document.addEventListener('keydown', function(ev) {
    var offen = document.querySelector('[data-menu-list]:not(.hidden)');
    if (!offen) return;
    if (ev.key === 'Escape') {
        fwMenuZu(offen);
        var b = offen.closest('[data-menu]').querySelector('[data-menu-btn]');
        if (b) b.focus();
        return;
    }
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
        var eintraege = Array.prototype.filter.call(offen.querySelectorAll('a,button'), function(e) { return e.offsetParent !== null; });
        if (!eintraege.length) return;
        ev.preventDefault();
        var i = eintraege.indexOf(document.activeElement);
        i = ev.key === 'ArrowDown' ? (i + 1) % eintraege.length : (i <= 0 ? eintraege.length - 1 : i - 1);
        eintraege[i].focus();
    }
});
window.addEventListener('resize', function() {
    document.querySelectorAll('[data-menu-list]:not(.hidden)').forEach(fwMenuEinpassen);
});

// ---- Tabellen mobil stapelbar machen ----
// Jede Zelle bekommt die Überschrift ihrer Spalte als data-label; die Schicht
// blendet unter 768 px den Kopf aus und zeigt stattdessen «Label — Wert» pro
// Zeile. Zentral statt in ~40 Templates: quer scrollen hiess bisher, entweder
// die Bezeichnung ODER den Betrag zu sehen.
// Tabellen, die bereits eine eigene Kartenansicht haben (Journal, Kontoblatt,
// Debitoren …), stehen in einem `hidden md:block` und werden übersprungen.
function fwTabellenStapeln(wurzel) {
    (wurzel || document).querySelectorAll('table').forEach(function (tab) {
        if (tab.dataset.stackGeprueft) return;
        tab.dataset.stackGeprueft = '1';
        var kopfZeile = tab.querySelector('thead tr');
        if (!kopfZeile) return;                       // ohne Überschriften kein sinnvolles Label
        if (tab.closest('.md\\:block')) return;       // Desktop-Variante einer Karten-Lösung
        // textContent klebt über Element-Grenzen hinweg zusammen: Aus
        //   die Kopfzelle «Netto / NK» mit einem Zeilenumbruch und «Referenz» in einem Span
        // wurde mobil das Label «NETTO / NKREFERENZ». Deshalb an jeder
        // Element- und <br>-Grenze ein Leerzeichen einfügen und Läufe
        // anschliessend zusammenfassen.
        var titel = Array.prototype.map.call(kopfZeile.cells, function (th) {
            var teile = [];
            (function sammeln(knoten) {
                Array.prototype.forEach.call(knoten.childNodes, function (k) {
                    if (k.nodeType === 3) { teile.push(k.nodeValue); return; }
                    teile.push(' ');
                    if (k.nodeName !== 'BR') sammeln(k);
                    teile.push(' ');
                });
            })(th);
            return teile.join('').replace(/\s+/g, ' ').trim();
        });
        if (!titel.length) return;
        tab.setAttribute('data-stack', '');
        tab.querySelectorAll('tbody tr, tfoot tr').forEach(function (tr) {
            var i = 0, titelGesetzt = false;
            Array.prototype.forEach.call(tr.cells, function (td) {
                if (!td.hasAttribute('colspan')) td.setAttribute('data-label', titel[i] || '');
                // Leere Zellen (unbenutzte Aktionsspalte) mobil ausblenden statt
                // eine Zeile mit nichts darin zu zeigen.
                var hatText = !!(td.textContent || '').trim();
                if (!hatText && !td.querySelector('img,svg,input,button,a'))
                    td.setAttribute('data-leer', '');
                // Die erste Zelle mit Inhalt benennt den Eintrag — sie wird zur
                // Überschrift der Karte (Auswahlkästchen o.ä. überspringen).
                if (!titelGesetzt && hatText && !td.hasAttribute('colspan')) {
                    td.setAttribute('data-stack-titel', '');
                    titelGesetzt = true;
                }
                // Inhalt in einen eigenen Kasten hängen, der schrumpfen darf.
                // display:contents lässt ihn auf dem Desktop wirkungslos.
                if (!td.querySelector(':scope > .fw-wert')) {
                    var huelle = document.createElement('span');
                    huelle.className = 'fw-wert';
                    while (td.firstChild) huelle.appendChild(td.firstChild);
                    td.appendChild(huelle);
                }
                i += td.colSpan || 1;
            });
        });
    });
}
/* Spaltenfilter für dichte Datentabellen (Phase 3).
   `<table data-spaltenfilter>` bekommt unter dem Kopf eine Filterzeile: Spalten mit wenigen
   verschiedenen Werten (Status, Stufe, Objekt) eine Auswahl, alle anderen ein Textfeld.
   Gefiltert werden die GELADENEN Zeilen — bei Listen mit Seiten also die aktuelle Seite;
   `th[data-nofilter]` nimmt eine Spalte aus. Mit Tastatur bedienbar, Stand per aria-live. */
var FW_FILTER_TXT = FW_RAHMEN.filter;
function fwSpaltenfilter(wurzel) {
    (wurzel || document).querySelectorAll('table[data-spaltenfilter]').forEach(function (tab) {
        if (tab.dataset.filterBereit) return;
        var kopf = tab.querySelector('thead tr'), tbody = tab.tBodies[0];
        if (!kopf || !tbody) return;
        // Zeilen mit colspan (Detail-, Leer- und Summenzeilen) gehören zur Zeile davor.
        var zeilen = [], folge = {};
        Array.prototype.forEach.call(tbody.rows, function (r) {
            if (r.querySelector('td[colspan]')) { if (zeilen.length) (folge[zeilen.length - 1] = folge[zeilen.length - 1] || []).push(r); return; }
            zeilen.push(r);
        });
        if (zeilen.length < 3) return;                 // bei zwei Zeilen hilft kein Filter
        tab.dataset.filterBereit = '1';
        var norm = function (t) { return (t || '').replace(/[\u2019\u0027\s]+/g, ' ').trim().toLowerCase(); };
        var zellText = function (r, i) { var c = r.cells[i]; return c ? norm(c.textContent) : ''; };
        var fz = document.createElement('tr'), felder = [];
        fz.className = 'fw-filterzeile';
        Array.prototype.forEach.call(kopf.cells, function (th, i) {
            var z = document.createElement('th'), ueberschrift = (th.textContent || '').replace(/\s+/g, ' ').trim();
            // Auf kleinen Schirmen ausgeblendete Spalten (`hidden lg:table-cell`) auch hier ausblenden.
            z.className = (th.className || '').split(/\s+/).filter(function (c) { return c === 'hidden' || /:table-cell$/.test(c); }).join(' ');
            fz.appendChild(z);
            if (th.hasAttribute('data-nofilter') || !ueberschrift) { felder.push(null); return; }
            var werte = {}, n = 0;
            zeilen.forEach(function (r) { var t = zellText(r, i); if (t && !werte[t]) { werte[t] = 1; n++; } });
            var feld;
            if (n >= 2 && n <= 8 && Object.keys(werte).every(function (w) { return w.length <= 32; })) {
                feld = document.createElement('select');
                var o = document.createElement('option'); o.value = ''; o.textContent = FW_FILTER_TXT.alle; feld.appendChild(o);
                zeilen.forEach(function (r) {      // Originalschreibweise, nach erster Fundstelle
                    var c = r.cells[i], t = c ? norm(c.textContent) : '';
                    if (t && !Array.prototype.some.call(feld.options, function (x) { return x.value === t; })) {
                        var op = document.createElement('option'); op.value = t;
                        op.textContent = (c.textContent || '').replace(/\s+/g, ' ').trim(); feld.appendChild(op);
                    }
                });
                feld.dataset.exakt = '1';
            } else {
                feld = document.createElement('input'); feld.type = 'search'; feld.placeholder = FW_FILTER_TXT.ph;
                feld.autocomplete = 'off';
            }
            feld.className = 'fw-filterfeld';
            feld.setAttribute('aria-label', FW_FILTER_TXT.spalte + ': ' + ueberschrift);
            z.appendChild(feld); felder.push(feld);
        });
        kopf.parentNode.appendChild(fz);
        var stand = document.createElement('div');
        stand.className = 'fw-filterstand'; stand.hidden = true; stand.setAttribute('aria-live', 'polite');
        var rahmen = tab.closest('.fw-tablewrap') || tab;
        rahmen.parentNode.insertBefore(stand, rahmen);
        var hoehe = function () { fwStil(tab, {'--fw-kopf': kopf.getBoundingClientRect().height + 'px'}); };
        hoehe(); window.addEventListener('resize', hoehe);
        function anwenden() {
            var aktiv = 0, sichtbar = 0;
            felder.forEach(function (f) { if (f) { var an = !!f.value; f.classList.toggle('fw-aktiv', an); if (an) aktiv++; } });
            zeilen.forEach(function (r, ri) {
                var ok = felder.every(function (f, i) {
                    if (!f || !f.value) return true;
                    var t = zellText(r, i), q = norm(f.value);
                    return f.dataset.exakt ? t === q : t.indexOf(q) !== -1;
                });
                r.classList.toggle('fw-gefiltert', !ok);
                (folge[ri] || []).forEach(function (x) { x.classList.toggle('fw-gefiltert', !ok); });
                if (ok) sichtbar++;
            });
            stand.hidden = !aktiv;
            if (aktiv) {
                stand.textContent = FW_FILTER_TXT.stand.replace('%(n)s', sichtbar).replace('%(m)s', zeilen.length) + ' · ';
                var b = document.createElement('button'); b.type = 'button'; b.textContent = FW_FILTER_TXT.reset;
                b.onclick = function () { felder.forEach(function (f) { if (f) f.value = ''; }); anwenden(); };
                stand.appendChild(b);
            }
        }
        felder.forEach(function (f) { if (f) f.addEventListener(f.tagName === 'SELECT' ? 'change' : 'input', anwenden); });
    });
}
document.addEventListener('DOMContentLoaded', function () { fwTabellenStapeln(); fwSpaltenfilter(); });
// Nachgeladene Inhalte (Tab-Wechsel, Modal) ebenfalls erfassen
document.addEventListener('fw:content', function (e) { fwTabellenStapeln(e.target); fwSpaltenfilter(e.target); });
