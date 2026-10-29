/* Schadenmeldung (öffentlich): Raum und Gegenstand gibt es nur für die Schadensmeldung.
 *
 * Das Formular `#meldungForm` (core/templates/core/schaden_melden.html) ist ein Assistent der
 * Anwendung (fw-bausteine.js). Dieses Skript hängt sich nur an die Wahl des Anliegens:
 *   - Anliegen «Schadensmeldung» (data-schaden="1") → die Schritte «Raum» und «Gegenstand»
 *     erscheinen, deren Auswahl ist Pflicht;
 *   - jedes andere Anliegen → beide Schritte entfallen, ihre Felder werden nicht gesendet;
 *   - je Raum gibt es eine eigene Gegenstandsliste (fieldset[data-raum]); nur die des gewählten
 *     Raums ist sichtbar und aktiv;
 *   - bei einem Gerät (data-geraet="1") erscheinen Marke und Seriennummer (nur im Aushang).
 * Die Werte der Karten sind deutsch (sie werden gespeichert), die Anzeige folgt der Sprache.
 *
 * Ohne Skript stehen alle Schritte untereinander und alles ist wählbar; der Server nimmt es
 * wie bisher an.
 */
(function () {
    'use strict';
    var form = document.getElementById('meldungForm');
    if (!form) return;

    var raumSchritt = document.getElementById('meldungRaum');
    var objektSchritt = document.getElementById('meldungObjekt');
    var geraet = document.getElementById('meldungGeraet');
    var raeume = Array.prototype.slice.call(form.querySelectorAll('input[name="raum"]'));
    var gruppen = Array.prototype.slice.call(form.querySelectorAll('fieldset[data-raum]'));

    function gewaehlt(name) { return form.querySelector('input[name="' + name + '"]:checked'); }

    function anpassen() {
        var kat = gewaehlt('kategorie');
        var schaden = !!kat && kat.getAttribute('data-schaden') === '1';
        raumSchritt.classList.toggle('hidden', !schaden);
        objektSchritt.classList.toggle('hidden', !schaden);
        raeume.forEach(function (r) { r.disabled = !schaden; r.required = schaden; });
        var raum = gewaehlt('raum');
        var raumWert = schaden && raum ? raum.value : '';
        gruppen.forEach(function (g) {
            var an = g.getAttribute('data-raum') === raumWert;
            g.classList.toggle('hidden', !an);
            Array.prototype.forEach.call(g.querySelectorAll('input'), function (i) {
                i.disabled = !an;
                i.required = an;
            });
        });
        if (geraet) {
            var obj = gewaehlt('objekt');
            geraet.classList.toggle('hidden', !(schaden && obj && obj.getAttribute('data-geraet') === '1'));
        }
    }

    form.addEventListener('change', function (e) {
        var n = e.target && e.target.name;
        if (n === 'kategorie' || n === 'raum' || n === 'objekt') anpassen();
    });

    // Antippen einer Karte geht einen Schritt weiter. `detail` ist bei Maus und Finger
    // grösser als 0, bei der Pfeiltaste in der Auswahl 0 — wer mit der Tastatur wählt,
    // springt nicht ungefragt weiter.
    form.addEventListener('click', function (e) {
        var karte = e.target.closest ? e.target.closest('.fw-wahl') : null;
        if (!karte || e.detail === 0) return;
        var weiter = form.querySelector('[data-assistent-weiter]');
        if (!weiter || weiter.classList.contains('hidden')) return;
        // Erst nachdem der Browser die Wahl gesetzt und `change` gefeuert hat.
        setTimeout(function () { weiter.click(); }, 0);
    });

    anpassen();

    // Zurück vom Server mit Fehlern: auf die Zusammenfassung, dort lässt sich jeder Schritt ändern.
    if (form.hasAttribute('data-fehler') && form.fwAssistent) {
        form.fwAssistent.zeige(999);
        var kopf = document.getElementById('meldungFehler');
        if (kopf && kopf.scrollIntoView) kopf.scrollIntoView({ block: 'start' });
    }
})();
