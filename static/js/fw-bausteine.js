/* Bausteine V11 (26.10.2026): Assistent, Hilfe-Blase, Hilfebox.
 *
 * ASSISTENT — fortschreitende Anreicherung, kein eigenes Formular:
 *   <div class="fw-assistent" data-assistent data-pruefen="Prüfen & speichern" data-stand="Schritt {i} von {n}">
 *     <nav class="fw-assistent-leiste"><ol></ol><div class="fw-assistent-stand"></div></nav>
 *     <div class="fw-assistent-inhalt">
 *       <section data-schritt="Titel" data-schritt-text="Unterzeile" [data-optional]>
 *         <div class="fw-assistent-schritt-kopf"></div> … Karten mit Feldern …
 *       </section>
 *       <section class="fw-assistent-pruefen fw-card"><div class="fw-rumpf"></div></section>
 *       <div class="fw-assistent-fuss"> … Knöpfe mit data-assistent-* … </div>
 *   Ohne Skript stehen alle Schritte untereinander und das Formular schickt wie immer ab —
 *   Feldnamen, Prüfung im Server und Ziel bleiben dieselben. Mit Skript ist genau ein
 *   Schritt sichtbar; «Weiter» prüft die Pflichtfelder des Schritts, der letzte Schritt
 *   fasst zusammen, was eingegeben ist. Ausgeblendete Schritte (`.hidden`, z. B. nur für
 *   Privatpersonen) zählen nicht mit.
 *
 * Für Seiten mit eigenem Skript (27.10.2026, Mietvertrag):
 *   - Ereignis `fw-assistent:zeige` an der Wurzel nach jedem Schrittwechsel,
 *     detail = {index, anzahl, schritt, letzter}. Wer es braucht (Zusammenfassung,
 *     Vorschau), hängt sich daran, statt die Schritte selbst zu steuern.
 *   - `wurzel.fwAssistent.zeige(i)` und `.zeigeFeld(el)`: öffnet den Schritt, in dem
 *     ein Feld steht (z. B. eine Meldung des Servers), und setzt den Fokus.
 *   - Vorschau `<aside class="fw-assistent-vorschau">`: Knopf `[data-vorschau-knopf]`
 *     klappt sie auf schmalen Schirmen ein und aus (Ereignis `fw-assistent:vorschau`).
 */
(function () {
    'use strict';

    function sichtbar(el) {
        return !el.closest('.hidden') && !el.closest('[hidden]');
    }

    function beschriftung(feld) {
        if (feld.id) {
            var l = document.querySelector('label[for="' + feld.id + '"]');
            if (l) return l.textContent.replace(/\*/g, '').trim();
        }
        var umschl = feld.closest('label');
        if (umschl) return umschl.textContent.replace(/\*/g, '').trim();
        var block = feld.closest('.fw-feldblock, div');
        var lab = block && block.querySelector('.fw-label');
        if (lab) return lab.textContent.replace(/\*/g, '').trim();
        return feld.getAttribute('placeholder') || feld.name;
    }

    function wert(feld) {
        if (feld.type === 'checkbox') return feld.checked ? (feld.dataset.ja || '✓') : '';
        if (feld.type === 'radio') return feld.checked ? beschriftung(feld) : '';
        if (feld.tagName === 'SELECT') {
            var o = feld.options[feld.selectedIndex];
            return o && feld.value ? o.textContent.trim() : '';
        }
        return (feld.value || '').trim();
    }

    function assistent(wurzel) {
        // Sichtbar INNERHALB des Assistenten — ein verborgener Rahmen aussen herum
        // (z. B. ein aufklappbarer Block) macht keinen Schritt unsichtbar.
        function sichtbar(el) {
            for (var x = el; x && x !== wurzel; x = x.parentElement) {
                if (x.classList && x.classList.contains('hidden')) return false;
                if (x.hidden) return false;
            }
            return true;
        }
        var alle = Array.prototype.slice.call(wurzel.querySelectorAll('[data-schritt]'));
        var pruefen = wurzel.querySelector('.fw-assistent-pruefen');
        var leiste = wurzel.querySelector('.fw-assistent-leiste ol');
        var stand = wurzel.querySelector('.fw-assistent-stand');
        var fussStand = wurzel.querySelector('.fw-assistent-fuss .stand');
        var zurueck = wurzel.querySelector('[data-assistent-zurueck]');
        var weiter = wurzel.querySelector('[data-assistent-weiter]');
        var absenden = wurzel.querySelectorAll('[data-assistent-absenden]');
        var pruefTitel = wurzel.dataset.pruefen || 'Prüfen';
        var form = wurzel.closest('form');
        var hier = 0;

        function schritte() {
            var s = alle.filter(function (el) { return !el.classList.contains('hidden') && sichtbar(el); });
            if (pruefen) s.push(pruefen);
            return s;
        }

        function leisteZeichnen(liste) {
            leiste.innerHTML = '';
            liste.forEach(function (el, i) {
                var li = document.createElement('li');
                var titel = el === pruefen ? pruefTitel : el.dataset.schritt;
                if (i === hier) li.className = 'hier';
                else if (i < hier) li.className = 'fertig';
                if (el.hasAttribute('data-optional')) li.classList.add('optional');
                var b = document.createElement('button');
                b.type = 'button';
                b.innerHTML = '<span class="nr">' + (i < hier ? '✓' : (i + 1)) + '</span><span class="t"></span>';
                b.querySelector('.t').textContent = titel;
                if (el.hasAttribute('data-optional')) {
                    var z = document.createElement('span'); z.className = 'zusatz';
                    z.textContent = wurzel.dataset.optional || 'optional'; b.appendChild(z);
                }
                if (i === hier) b.setAttribute('aria-current', 'step');
                b.addEventListener('click', function () {
                    // Vorwärts nur über geprüfte Schritte; zurück jederzeit
                    if (i <= hier || pruefeBis(i)) zeige(i);
                });
                li.appendChild(b);
                leiste.appendChild(li);
            });
        }

        function pflichtOk(el, melden) {
            var felder = el.querySelectorAll('input, select, textarea');
            for (var k = 0; k < felder.length; k++) {
                var f = felder[k];
                if (!sichtbar(f) || f.disabled || f.type === 'hidden') continue;
                var leer = !(f.value || '').trim();
                if ((f.hasAttribute('data-pflicht') && leer) || !f.checkValidity()) {
                    if (melden) {
                        if (f.hasAttribute('data-pflicht') && leer && f.setCustomValidity) {
                            f.setCustomValidity(f.dataset.pflicht || wurzel.dataset.pflichtText || 'Bitte ausfüllen.');
                            f.addEventListener('input', function loesen() { this.setCustomValidity(''); this.removeEventListener('input', loesen); });
                        }
                        f.reportValidity ? f.reportValidity() : f.focus();
                    }
                    return false;
                }
            }
            return true;
        }

        function pruefeBis(ziel) {
            var liste = schritte();
            for (var i = hier; i < ziel; i++) {
                if (!pflichtOk(liste[i], true)) { zeige(i); return false; }
            }
            return true;
        }

        function zusammenfassen(liste) {
            var rumpf = pruefen.querySelector('.fw-assistent-zusammenfassung') || pruefen;
            rumpf.innerHTML = '';
            liste.forEach(function (el, i) {
                if (el === pruefen) return;
                var zeilen = [];
                el.querySelectorAll('input[name], select[name], textarea[name]').forEach(function (f) {
                    if (f.type === 'hidden' || f.name === 'csrfmiddlewaretoken' || !sichtbar(f)) return;
                    var w = wert(f);
                    if (w) zeilen.push([beschriftung(f), w]);
                });
                var h = document.createElement('h3');
                h.innerHTML = '<span></span>';
                h.firstChild.textContent = el.dataset.schritt;
                var aend = document.createElement('button');
                aend.type = 'button'; aend.className = 'fw-btn fw-knapp fw-leise';
                aend.textContent = wurzel.dataset.aendern || 'Ändern';
                aend.addEventListener('click', function () { zeige(i); });
                h.appendChild(aend);
                rumpf.appendChild(h);
                if (!zeilen.length) {
                    var p = document.createElement('p'); p.className = 'fw-hilfe';
                    p.textContent = wurzel.dataset.leer || '—'; rumpf.appendChild(p); return;
                }
                var dl = document.createElement('dl');
                zeilen.forEach(function (z) {
                    var dt = document.createElement('dt'); dt.textContent = z[0];
                    var dd = document.createElement('dd'); dd.textContent = z[1];
                    dl.appendChild(dt); dl.appendChild(dd);
                });
                rumpf.appendChild(dl);
            });
        }

        function zeige(i, ohneScroll) {
            var liste = schritte();
            hier = Math.max(0, Math.min(i, liste.length - 1));
            alle.concat(pruefen ? [pruefen] : []).forEach(function (el) { el.classList.remove('zeigt'); });
            var akt = liste[hier];
            akt.classList.add('zeigt');
            var kopf = akt.querySelector('.fw-assistent-schritt-kopf');
            var text = (wurzel.dataset.stand || 'Schritt {i} von {n}').replace('{i}', hier + 1).replace('{n}', liste.length);
            if (kopf) {
                kopf.innerHTML = '<span class="fw-ueber"></span><h2></h2><p></p>';
                kopf.querySelector('.fw-ueber').textContent = text;
                kopf.querySelector('h2').textContent = akt === pruefen ? pruefTitel : akt.dataset.schritt;
                kopf.querySelector('p').textContent = akt.dataset.schrittText || '';
            }
            if (akt === pruefen) zusammenfassen(liste);
            leisteZeichnen(liste);
            if (stand) stand.textContent = text;
            if (fussStand) fussStand.textContent = text;
            var letzter = hier === liste.length - 1;
            if (zurueck) zurueck.disabled = hier === 0;
            if (weiter) weiter.classList.toggle('hidden', letzter);
            absenden.forEach(function (b) { b.classList.toggle('hidden', !letzter); });
            // Telefon: Die Leiste ist eine waagrechte Zeile — den aktuellen Schritt ins Bild holen (27.10.2026)
            var zeile = leiste.parentElement, aktLi = leiste.children[hier];
            if (zeile && aktLi && zeile.scrollWidth > zeile.clientWidth) {
                var rz = zeile.getBoundingClientRect(), rl = aktLi.getBoundingClientRect();
                zeile.scrollLeft += (rl.left - rz.left) - (zeile.clientWidth - rl.width) / 2;
            }
            wurzel.dispatchEvent(new CustomEvent('fw-assistent:zeige', {
                detail: { index: hier, anzahl: liste.length, schritt: akt, letzter: letzter } }));
            if (!ohneScroll) {
                var oben = wurzel.getBoundingClientRect().top + window.scrollY - 16;
                if (window.scrollY > oben) window.scrollTo({ top: oben, behavior: 'smooth' });
                var erstes = akt.querySelector('input:not([type=hidden]), select, textarea');
                if (erstes && sichtbar(erstes)) setTimeout(function () { try { erstes.focus({ preventScroll: true }); } catch (e) { /* alt */ } }, 50);
            }
        }

        if (weiter) weiter.addEventListener('click', function () { if (pflichtOk(schritte()[hier], true)) zeige(hier + 1); });
        if (zurueck) zurueck.addEventListener('click', function () { zeige(hier - 1); });
        // Enter in einem Feld geht einen Schritt weiter statt abzuschicken
        wurzel.addEventListener('keydown', function (e) {
            if (e.key !== 'Enter' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'BUTTON') return;
            var liste = schritte();
            if (hier < liste.length - 1) { e.preventDefault(); if (pflichtOk(liste[hier], true)) zeige(hier + 1); }
        });
        // Abschicken nur vom letzten Schritt — sonst springt der Browser zu einem
        // ungültigen Feld in einem verborgenen Schritt und meldet nichts Sichtbares.
        if (form) form.addEventListener('submit', function (e) {
            var liste = schritte();
            for (var i = 0; i < liste.length - 1; i++) {
                if (!pflichtOk(liste[i], false)) { e.preventDefault(); zeige(i); pflichtOk(liste[i], true); return; }
            }
        });
        // Schritte, die sich ein- oder ausblenden (z. B. Personenart), zeichnen die Leiste neu
        // Nur wenn sich die MENGE der Schritte ändert — die eigene Klasse `zeigt` löst
        // sonst eine Endlosschleife aus.
        var menge = function () { return schritte().map(function (el) { return alle.indexOf(el); }).join(','); };
        var zuletzt = '';
        var beob = new MutationObserver(function () { var m = menge(); if (m !== zuletzt) { zuletzt = m; zeige(Math.min(hier, schritte().length - 1), true); } });
        alle.forEach(function (el) { beob.observe(el, { attributes: true, attributeFilter: ['class', 'hidden'] }); });

        // Schnittstelle für Seiten mit eigenem Skript (27.10.2026)
        wurzel.fwAssistent = {
            zeige: function (i) { zeige(i); },
            // Öffnet den Schritt, in dem `feld` steht; false, wenn es in keinem sichtbaren steht.
            zeigeFeld: function (feld) {
                var liste = schritte();
                for (var i = 0; i < liste.length; i++) {
                    if (!liste[i].contains(feld)) continue;
                    zeige(i, true);
                    if (feld.scrollIntoView) feld.scrollIntoView({ block: 'center' });
                    try { feld.focus({ preventScroll: true }); } catch (e) { /* alt */ }
                    return true;
                }
                return false;
            },
            hier: function () { return hier; }
        };

        wurzel.classList.add('an');
        // Rückweg vom Server mit Fehlern: beim ersten markierten Feld anfangen
        var start = 0, liste = schritte();
        var fehler = wurzel.querySelector('[aria-invalid="true"]');
        if (fehler) liste.forEach(function (el, i) { if (el.contains(fehler) && !start) start = i; });
        zuletzt = menge();
        zeige(start, true);
    }

    function hilfe() {
        var blase = null, knopf = null;
        function zu() {
            if (blase) { blase.remove(); blase = null; }
            if (knopf) { knopf.setAttribute('aria-expanded', 'false'); knopf = null; }
        }
        function auf(b) {
            zu();
            var quelle = b.nextElementSibling;
            if (!quelle || !quelle.classList.contains('fw-hilfe-text')) return;
            blase = document.createElement('div');
            blase.className = 'fw-hilfe-blase';
            blase.id = 'fwHilfeBlase';
            blase.setAttribute('role', 'tooltip');
            blase.innerHTML = quelle.innerHTML;   // aus dem eigenen Katalog, im Template maskiert
            document.body.appendChild(blase);
            b.setAttribute('aria-expanded', 'true');
            b.setAttribute('aria-describedby', 'fwHilfeBlase');
            knopf = b;
            var r = b.getBoundingClientRect(), w = blase.offsetWidth, h = blase.offsetHeight, rand = 12;
            var links = Math.min(Math.max(rand, r.left + r.width / 2 - w / 2), innerWidth - w - rand);
            var oben = r.bottom + 8;
            if (oben + h > innerHeight - rand && r.top - h - 8 > rand) oben = r.top - h - 8;
            blase.style.left = Math.round(links) + 'px';
            blase.style.top = Math.round(oben) + 'px';
        }
        document.addEventListener('click', function (e) {
            var b = e.target.closest ? e.target.closest('.fw-hilfe-knopf') : null;
            if (b) { e.preventDefault(); e.stopPropagation(); if (knopf === b) zu(); else auf(b); return; }
            if (blase && !blase.contains(e.target)) zu();
        });
        document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && blase) { var k = knopf; zu(); if (k) k.focus(); } });
        window.addEventListener('scroll', zu, { passive: true });
        window.addEventListener('resize', zu);
    }

    function hilfeboxen() {
        document.querySelectorAll('.fw-hilfebox[data-hilfebox]').forEach(function (box) {
            var schluessel = 'fw-hilfebox-' + box.dataset.hilfebox;
            try { if (localStorage.getItem(schluessel) === 'weg') box.classList.add('weg'); } catch (e) { /* ohne Speicher sichtbar */ }
            var zu = box.querySelector('.zu');
            if (zu) zu.addEventListener('click', function () {
                box.classList.add('weg');
                try { localStorage.setItem(schluessel, 'weg'); } catch (e) { /* nur für diese Seite */ }
            });
        });
    }

    // Am Telefon scrollt die Prozessleiste quer — der aktuelle Schritt soll sichtbar sein.
    function prozessleisten() {
        document.querySelectorAll('.fw-prozess').forEach(function (leiste) {
            var hier = leiste.querySelector('.hier');
            if (hier && leiste.scrollWidth > leiste.clientWidth) {
                leiste.scrollLeft = hier.offsetLeft - (leiste.clientWidth - hier.offsetWidth) / 2;
            }
        });
    }

    // Vorschau neben dem Assistenten (27.10.2026): auf schmalen Schirmen ein- und ausklappbar.
    // Der Zustand steht als Klasse `offen` am Panel; das CSS blendet nur unterhalb der
    // Spaltenbreite aus, breit ist die Vorschau immer sichtbar.
    function vorschauen() {
        document.querySelectorAll('.fw-assistent-vorschau [data-vorschau-knopf]').forEach(function (knopf) {
            var panel = knopf.closest('.fw-assistent-vorschau');
            function setzen(offen) {
                panel.classList.toggle('offen', offen);
                knopf.setAttribute('aria-expanded', offen ? 'true' : 'false');
                var t = offen ? knopf.dataset.textVerbergen : knopf.dataset.textZeigen;
                var ziel = knopf.querySelector('.t') || knopf;
                if (t) ziel.textContent = t;
                panel.dispatchEvent(new CustomEvent('fw-assistent:vorschau', { bubbles: true, detail: { offen: offen } }));
            }
            setzen(panel.classList.contains('offen'));
            knopf.addEventListener('click', function () { setzen(!panel.classList.contains('offen')); });
        });
    }

    function start() {
        document.querySelectorAll('.fw-assistent[data-assistent]').forEach(assistent);
        vorschauen();
        hilfe();
        hilfeboxen();
        prozessleisten();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
    window.fwAssistent = assistent;
})();
