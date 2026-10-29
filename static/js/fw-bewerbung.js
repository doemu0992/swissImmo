/* Öffentliche Bewerbung: Absenden an die Schnittstelle und Anzeige der Antwort.
 *
 * Das Formular `#bewerbungForm` (core/templates/core/public_bewerbung_form.html) ist ein
 * Assistent der Anwendung (fw-bausteine.js: Schritte, Pflichtprüfung, Zusammenfassung). Dieses
 * Skript macht drei Dinge:
 *   - zeigt Anstellungsangaben nur für «Angestellt», Tierangaben nur bei «Haustiere» und den
 *     Dateiupload nur, solange der Auszug nicht nachgereicht wird; die Pflicht folgt der Sichtbarkeit;
 *   - sendet an `data-api` (mietprozess/api.py) wie bisher die Vue-Fassung: alle Felder auch
 *     leer, Häkchen als `true`/`false` (ein nicht angehaktes «unbefristet» darf nicht als
 *     «true» verstanden werden), ohne leere Dateifelder;
 *   - zeigt Erfolg oder die Meldung des Servers.
 */
(function () {
    'use strict';
    var form = document.getElementById('bewerbungForm');
    if (!form) return;
    var $ = function (id) { return document.getElementById(id); };
    var fehlerBox = $('bewerbungFehler'), erfolg = $('bewerbungErfolg'), senden = $('bewerbungSenden');

    function umschalten() {
        var angestellt = form.elements.erwerbsstatus.value === 'angestellt';
        var karte = $('bewerbungAngestellt');
        karte.classList.toggle('hidden', !angestellt);
        // Die Pflichtprüfung des Assistenten setzt eine eigene Meldung (setCustomValidity), die bis
        // zur nächsten Eingabe stehen bleibt — wird das Feld unwichtig, muss sie weg, sonst
        // sperrt ein verstecktes Feld das Absenden.
        Array.prototype.forEach.call(karte.querySelectorAll('input[data-pflicht]'), function (f) {
            f.required = angestellt;
            f.setCustomValidity('');
        });

        $('bewerbungTiere').classList.toggle('hidden', !$('b-haustiere').checked);

        var nachreichen = $('b-nachreichen').checked;
        $('bewerbungAuszug').classList.toggle('hidden', nachreichen);
        $('b-auszug').required = !nachreichen;
        $('b-auszug').setCustomValidity('');
    }
    form.addEventListener('change', umschalten);
    umschalten();

    function melden(text) {
        fehlerBox.querySelector('b').textContent = text;
        fehlerBox.classList.remove('hidden');
        fehlerBox.scrollIntoView({ block: 'start', behavior: 'smooth' });
        fehlerBox.focus();
    }

    form.addEventListener('submit', function (e) {
        // Der Assistent hat das Absenden schon angehalten, wenn in einem Schritt etwas fehlt.
        if (e.defaultPrevented) return;
        e.preventDefault();
        fehlerBox.classList.add('hidden');

        var daten = new FormData(form);
        daten.delete('csrfmiddlewaretoken');
        Array.prototype.forEach.call(form.querySelectorAll('input[type=checkbox]'), function (cb) {
            daten.set(cb.name, cb.checked ? 'true' : 'false');
        });
        // Parameter der Schnittstelle, die das Formular nicht abfragt (Zivilstand: EDÖB; die
        // Kontaktpersonen erhebt die Verwaltung später): die Schnittstelle verlangt sie, leer.
        ['zivilstand', 'kontaktperson_vermieter', 'email_vermieter', 'kontaktperson_arbeitgeber',
         'email_arbeitgeber', 'bemerkungen'].forEach(function (n) { if (!daten.has(n)) daten.set(n, ''); });
        ['betreibungsauszug', 'weitere_dokumente'].forEach(function (n) {
            var d = daten.get(n);
            if (d && !d.name) daten.delete(n);
        });
        var token = form.querySelector('[name=csrfmiddlewaretoken]').value;
        senden.disabled = true;
        senden.setAttribute('aria-busy', 'true');

        fetch(form.dataset.api, { method: 'POST', headers: { 'X-CSRFToken': token }, body: daten, credentials: 'same-origin' })
            .then(function (res) {
                return res.text().then(function (text) {
                    var antwort = null;
                    try { antwort = JSON.parse(text); } catch (x) { /* kein JSON: Serverfehler */ }
                    if (antwort === null) { melden(form.dataset.serverfehler); return; }
                    if (res.ok) {
                        form.classList.add('hidden');
                        erfolg.classList.remove('hidden');
                        erfolg.scrollIntoView({ block: 'start', behavior: 'smooth' });
                        erfolg.focus();
                    } else if (res.status === 422) {
                        if (window.console) console.error('Bewerbung, Prüfung der Schnittstelle:', antwort.detail);
                        melden(form.dataset.ungueltig);
                    } else {
                        melden(antwort.error || form.dataset.unbekannt);
                    }
                });
            })
            .catch(function () { melden(form.dataset.netzfehler); })
            .then(function () { senden.disabled = false; senden.removeAttribute('aria-busy'); });
    });
})();
