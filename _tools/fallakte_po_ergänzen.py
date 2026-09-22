#!/usr/bin/env python3
"""Fallakte-Uebersetzungen in die vier Kataloge eintragen.

Die Vorlage `fw/fall_detail.html` tragt jetzt `{% trans %}` und
`{% blocktrans %}`. Diese Skript traegt die passenden Eintraege in
alle vier `.po`-Kataloge ein — gleicher Text, gleiche Struktur,
nur die `msgstr` je Sprache anders.
"""
import pathlib
import re

WURZEL = pathlib.Path('/home/doemun/repos/swissImmo')

#: Alle neuen Eintraege, die die Fallakte mitbringt.
#: Schluessel ist der msgid, Wert ein dict {sprache: msgstr}.
EINTRAEGE = {
    # Einzelstrings
    'Arbeit': {
        'de': 'Arbeit', 'fr': 'Travail', 'it': 'Lavoro', 'en': 'Work',
    },
    'Fall': {
        'de': 'Fall', 'fr': 'Dossier', 'it': 'Pratica', 'en': 'Case',
    },
    'Fallart': {
        'de': 'Fallart', 'fr': 'Type de dossier', 'it': 'Tipo di pratica',
        'en': 'Case type',
    },
    'Akte': {
        'de': 'Akte', 'fr': 'Dossier', 'it': 'Pratica', 'en': 'File',
    },
    'Eröffnet': {
        'de': 'Eröffnet', 'fr': 'Ouvert', 'it': 'Aperto', 'en': 'Opened',
    },
    'Zuständig': {
        'de': 'Zuständig', 'fr': 'Responsable', 'it': 'Responsabile',
        'en': 'Responsible',
    },
    'niemand': {
        'de': 'niemand', 'fr': 'personne', 'it': 'nessuno', 'en': 'nobody',
    },
    'liegengeblieben': {
        'de': 'liegengeblieben', 'fr': 'en souffrance', 'it': 'in sospeso',
        'en': 'stalled',
    },
    'Fortschritt': {
        'de': 'Fortschritt', 'fr': 'Progrès', 'it': 'Progresso',
        'en': 'Progress',
    },
    'Schritte erledigt': {
        'de': 'Schritte erledigt', 'fr': 'Étapes terminées',
        'it': 'Fasi completate', 'en': 'Steps completed',
    },
    'Nächster Schritt': {
        'de': 'Nächster Schritt', 'fr': 'Prochaine étape',
        'it': 'Prossima fase', 'en': 'Next step',
    },
    'ohne Frist': {
        'de': 'ohne Frist', 'fr': "sans échéance", 'it': 'senza scadenza',
        'en': 'without deadline',
    },
    'alle Schritte erledigt': {
        'de': 'alle Schritte erledigt', 'fr': 'toutes les étapes sont terminées',
        'it': 'tutte le fasi sono completate', 'en': 'all steps completed',
    },
    'Letzte Bewegung': {
        'de': 'Letzte Bewegung', 'fr': 'Dernier mouvement',
        'it': 'Ultimo movimento', 'en': 'Last activity',
    },
    'Tage': {
        'de': 'Tage', 'fr': 'Jours', 'it': 'Giorni', 'en': 'Days',
    },
    'meldet sich nach 10 Tagen': {
        'de': 'meldet sich nach 10 Tagen', 'fr': 'se signale après 10 jours',
        'it': 'si segnala dopo 10 giorni', 'en': 'reports after 10 days',
    },
    'meldet sich nach 14 Tagen': {
        'de': 'meldet sich nach 14 Tagen', 'fr': 'se signale après 14 jours',
        'it': 'si segnala dopo 14 giorni', 'en': 'reports after 14 days',
    },
    'Erfasste Zeit': {
        'de': 'Erfasste Zeit', 'fr': 'Temps saisi', 'it': 'Tempo registrato',
        'en': 'Recorded time',
    },
    'min': {
        'de': 'min', 'fr': 'min', 'it': 'min', 'en': 'min',
    },
    'auf diesen Fall gebucht': {
        'de': 'auf diesen Fall gebucht', 'fr': 'imputé à ce dossier',
        'it': 'addebitato a questa pratica', 'en': 'booked to this case',
    },
    'Aufwand erfassen': {
        'de': 'Aufwand erfassen', 'fr': 'Saisir le travail',
        'it': 'Registrare il lavoro', 'en': 'Record effort',
    },
    'Minuten': {
        'de': 'Minuten', 'fr': 'Minutes', 'it': 'Minuti', 'en': 'Minutes',
    },
    'Tätigkeit': {
        'de': 'Tätigkeit', 'fr': 'Activité', 'it': 'Attività', 'en': 'Activity',
    },
    'Telefonat mit Handwerker': {
        'de': 'Telefonat mit Handwerker', 'fr': 'Appel avec artisan',
        'it': 'Telefonta con artigiano', 'en': 'Call with tradesman',
    },
    'Satz CHF/h': {
        'de': 'Satz CHF/h', 'fr': 'Taux CHF/h', 'it': 'Tasso CHF/h',
        'en': 'Rate CHF/h',
    },
    'separat verrechenbar': {
        'de': 'separat verrechenbar', 'fr': 'facturé séparément',
        'it': 'fatturato separatamente', 'en': 'billed separately',
    },
    'Buchen': {
        'de': 'Buchen', 'fr': 'Enregistrer', 'it': 'Registrare', 'en': 'Book',
    },
    'Zum nächsten Schritt →': {
        'de': 'Zum nächsten Schritt →', 'fr': 'Vers la prochaine étape →',
        'it': 'Alla prossima fase →', 'en': 'To the next step →',
    },
    'optional': {
        'de': 'optional', 'fr': 'facultatif', 'it': 'facoltativo',
        'en': 'optional',
    },
    'Erledigt': {
        'de': 'Erledigt', 'fr': 'Terminé', 'it': 'Completato', 'en': 'Done',
    },
    'Für diesen Fall sind keine Schritte angelegt.': {
        'de': 'Für diesen Fall sind keine Schritte angelegt.',
        'fr': 'Aucune étape n\'est définie pour ce dossier.',
        'it': 'Nessuna fase è definita per questa pratica.',
        'en': 'No steps are defined for this case.',
    },
    'Notiz': {
        'de': 'Notiz', 'fr': 'Note', 'it': 'Nota', 'en': 'Note',
    },
    # Blocktrans-Strings (mit Platzhaltern)
    'fällig %(frist)s': {
        'de': 'fällig %(frist)s', 'fr': 'échéance %(frist)s',
        'it': 'scadenza %(frist)s', 'en': 'due %(frist)s',
    },
    'Seit %(tage)s Tagen keine Bewegung': {
        'de': 'Seit %(tage)s Tagen keine Bewegung',
        'fr': 'Aucun mouvement depuis %(tage)s jours',
        'it': 'Nessun movimento da %(tage)s giorni',
        'en': 'No activity for %(tage)s days',
    },
    'Die Verfallsregel hat angeschlagen. Entweder der nächste Schritt wird erledigt, oder der Fall gehört auf «Ruht» — liegenbleiben ist in einem Büro mit drei Personen der teuerste Fehler.': {
        'de': 'Die Verfallsregel hat angeschlagen. Entweder der nächste Schritt wird erledigt, oder der Fall gehört auf «Ruht» — liegenbleiben ist in einem Büro mit drei Personen der teuerste Fehler.',
        'fr': "La règle d'échéance a été déclenchée. Soit l'étape suivante est terminée, soit le dossier doit être mis en pause — laisser traiter est l'erreur la plus coûteuse dans un bureau de trois personnes.",
        'it': 'La regola di scadenza è stata attivata. O la fase successiva viene completata, o la pratica deve essere messa in pausa — lasciare in sospeso è l\'errore più costoso in un ufficio di tre persone.',
        'en': 'The expiry rule has been triggered. Either the next step is completed, or the case should be put on hold — letting it stall is the most expensive error in a three-person office.',
    },
    'Etappe %(nr)s': {
        'de': 'Etappe %(nr)s', 'fr': 'Phase %(nr)s', 'it': 'Fase %(nr)s',
        'en': 'Stage %(nr)s',
    },
    'erledigt %(am)s': {
        'de': 'erledigt %(am)s', 'fr': 'terminé le %(am)s',
        'it': 'completato il %(am)s', 'en': 'completed %(am)s',
    },
    'Frist %(frist)s': {
        'de': 'Frist %(frist)s', 'fr': 'Échéance %(frist)s',
        'it': 'Scadenza %(frist)s', 'en': 'Deadline %(frist)s',
    },
}


def _eintrag_hinzufuegen(pfad, eintraege):
    """Haengt die neuen Eintraege an eine .po-Datei an."""
    text = pfad.read_text(encoding='utf-8')
    # Pruefen, welche Eintraege schon vorhanden sind
    vorhanden = set()
    for m in re.finditer(r'^msgid "(.+)"$', text, re.MULTILINE):
        vorhanden.add(m.group(1))

    neu = []
    for msgid, uebersetzungen in eintraege.items():
        if msgid in vorhanden:
            continue
        msgstr = uebersetzungen.get(pfad.parent.parent.name, '')
        neu.append(f'\n#: core/templates/fw/fall_detail.html\n'
                   f'msgid "{msgid}"\n'
                   f'msgstr "{msgstr}"')

    if neu:
        # Vor dem letzten Leerzeilen-Block anhaengen
        text = text.rstrip('\n') + '\n' + '\n'.join(neu) + '\n'
        pfad.write_text(text, encoding='utf-8')
        print(f'{pfad}: {len(neu)} neue Eintraege')
    else:
        print(f'{pfad}: keine neuen')


def main():
    for sprache in ('de', 'fr', 'it', 'en'):
        pfad = WURZEL / 'locale' / sprache / 'LC_MESSAGES' / 'django.po'
        _eintrag_hinzufuegen(pfad, EINTRAEGE)


if __name__ == '__main__':
    main()
