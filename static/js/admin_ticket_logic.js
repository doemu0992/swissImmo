/* static/js/admin_ticket_logic.js */
document.addEventListener('DOMContentLoaded', function() {
    const $ = django.jQuery;

    function checkVisibility(row) {
        // 1. Suche das Dropdown (Select)
        const select = row.querySelector('select[name$="-typ"]');
        if (!select) return;

        // 2. Suche das Feld "Empfänger Handwerker" (Den ganzen Container)
        // In Unfold ist das meist ein div mit Klasse 'field-empfaenger_handwerker'
        const handwerkerField = row.querySelector('.field-empfaenger_handwerker');

        if (!handwerkerField) return;

        // 3. Die harte Logik
        if (select.value === 'handwerker_mail') {
            // Zeigen: Wir entfernen die Klasse 'hidden', falls sie da ist
            handwerkerField.classList.remove('hidden');
            // Sicherheitshalber Display Style entfernen, falls jQuery noch Reste hinterlassen hat
            handwerkerField.style.display = '';
        } else {
            // Verstecken: Wir fügen die Tailwind-Klasse 'hidden' hinzu. Das gewinnt immer.
            handwerkerField.classList.add('hidden');
        }
    }

    function initListeners() {
        // Suche alle Zeilen (sowohl Tabellen als auch Stacked)
        const rows = document.querySelectorAll('.inline-related, .form-row');

        rows.forEach(function(row) {
            const select = row.querySelector('select[name$="-typ"]');
            if (select) {
                // Initial prüfen
                checkVisibility(row);

                // Event Listener: Wenn sich was ändert
                select.addEventListener('change', function() {
                    checkVisibility(row);
                });
            }
        });
    }

    // Starten
    initListeners();

    // Auch ausführen, wenn man auf "Neue Zeile hinzufügen" klickt
    $(document).on('formset:added', function() {
        initListeners();
    });
});