"""Gibt Formularfeldern einen zugänglichen Namen (DESIGN-27).

DAS PROBLEM

In 47 Vorlagen steht die Beschriftung NEBEN dem Feld, ohne dass beide verbunden sind:

    <div class="fw-feldblock"><label class="fw-label">Jahr</label>
        <select name="jahr" class="fw-feld">…</select></div>

Ein Screenreader liest «Auswahl» statt «Jahr», und ein Klick auf «Jahr» setzt den Fokus nicht ins
Feld. Das Audit vom 28.10.2026 zählte 357 von 994 Feldern ohne Namen.

DIE LÖSUNG, AN EINER STELLE

Nicht 357 Stellen in 47 Vorlagen von Hand: Diese Funktion liest das fertige HTML und verbindet ein
`<label>` ohne `for` mit dem Feld, das unmittelbar darauf folgt (nur Leerraum dazwischen). Sie fasst
nichts an, was schon einen Namen hat, und ändert nichts am Aussehen: Es kommen nur Attribute hinzu.

* Normalfall: `id` am Feld (vorhandene oder erzeugte, je Antwort eindeutig) und `for` am Label.
* Innerhalb eines `<template>` (Alpine `x-for` klont das Markup, eine `id` stünde dann mehrfach
  auf der Seite): `aria-label` mit dem Text des Labels.

Ein Feld mit Platzhalter und ohne Label (Erfassungszeilen, Suchfelder) bekommt den Platzhalter als
`aria-label`.

Was sie nicht erkennt (Feld in einer Tabellenzelle, Label und Feld nicht benachbart), bleibt unbenannt und wird vom Wächter `core/tests/test_feldnamen.py` gemeldet:
Dort gehört ein `aria-label` oder ein richtig gebautes Label in die Vorlage.

Aufgerufen von `core.middleware_feldnamen.FeldnamenMiddleware`.
"""
import html as _html
import re

#: Ein Tag der interessierenden Sorte. Die Attribute dürfen in Anführungszeichen ein `>` enthalten
#: (Alpine: `x-show="a > b"`).
_TAG = re.compile(
    r'<(/?)(label|input|select|textarea|template|script|style)\b((?:[^>"\']|"[^"]*"|\'[^\']*\')*)>',
    re.IGNORECASE)
_LABEL_FOR = re.compile(r'<label\b(?:[^>"\']|"[^"]*"|\'[^\']*\')*?\sfor\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_TAGS_ENTFERNEN = re.compile(r'<[^>]*>')

#: Ohne `<label` und ohne `placeholder` gibt es nichts zu verbinden: Die Seite wird gar nicht erst gelesen.
_MOEGLICH = re.compile(r'<label|placeholder\s*=', re.IGNORECASE)

#: Eingabearten ohne Beschriftungspflicht: Der Wert (Knopf) bzw. nichts (versteckt) ist der Name.
_OHNE_EINGABE = {'hidden', 'submit', 'button', 'reset', 'image'}


def _attribut(attrs, name):
    """Wert eines Attributs (in Anführungszeichen) oder `None`; `data-id` zählt nicht als `id`."""
    treffer = re.search(r'(?<![\w:@.-])' + re.escape(name) + r'\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', attrs, re.IGNORECASE)
    if not treffer:
        return None
    return treffer.group(1) if treffer.group(1) is not None else treffer.group(2)


def _hat_attribut(attrs, name):
    return re.search(r'(?<![\w@.-])' + re.escape(name) + r'(?=[\s=/>]|$)', attrs, re.IGNORECASE) is not None


def _text(inhalt):
    text = _html.unescape(_TAGS_ENTFERNEN.sub(' ', inhalt))
    return re.sub(r'[\s*:]+$', '', ' '.join(text.split()))


def _einfuegen(html, m, einzufuegen):
    """Position vor dem schliessenden `>` bzw. `/>` des Tags `m`."""
    ende = m.end() - 1
    if html[ende - 1] == '/':
        ende -= 1
    return ende, einzufuegen


def feldnamen_ergaenzen(html):
    """Das HTML mit verbundenen Labels. Ohne `<label` kommt es unverändert zurück."""
    if not _MOEGLICH.search(html):
        return html

    mit_for = set(_LABEL_FOR.findall(html))
    kleinschrift = html.lower()
    edits = []                                  # (Position, Text)
    labels = []                                 # Stapel offener Labels
    wartend = None                              # Label ohne for, das gerade geschlossen wurde
    template_tiefe = 0
    zaehler = 0
    pos = 0
    while True:
        m = _TAG.search(html, pos)
        if m is None:
            break
        pos = m.end()
        schliessend, name, attrs = m.group(1) == '/', m.group(2).lower(), m.group(3)
        if name in ('script', 'style'):
            if not schliessend:
                ende = kleinschrift.find('</' + name, pos)
                pos = ende if ende != -1 else len(html)
            continue
        if name == 'template':
            template_tiefe += -1 if schliessend else 1
            template_tiefe = max(template_tiefe, 0)
            continue
        if name == 'label':
            if not schliessend:
                labels.append({'tag': m, 'attrs': attrs, 'felder': 0, 'ab': m.end()})
                wartend = None
            elif labels:
                label = labels.pop()
                wartend = None
                text = _text(html[label['ab']:m.start()])
                if text and not label['felder'] and not _hat_attribut(label['attrs'], 'for'):
                    wartend = {'label': label, 'text': text, 'ende': m.end()}
            continue
        # input / select / textarea
        if schliessend:
            continue
        if name == 'input' and (_attribut(attrs, 'type') or 'text').lower() in _OHNE_EINGABE:
            continue
        if labels:                              # vom Label umschlossen: hat seinen Namen
            labels[-1]['felder'] += 1
            wartend = None
            continue
        ziel, wartend = wartend, None
        if any(_hat_attribut(attrs, a) and (_attribut(attrs, a) or a.startswith(':'))
               for a in ('aria-label', 'aria-labelledby', 'title', ':aria-label', 'x-bind:aria-label')):
            continue
        vorhandene_id = _attribut(attrs, 'id')
        if vorhandene_id and vorhandene_id in mit_for:
            continue
        if ziel is None or html[ziel['ende']:m.start()].strip():
            # Kein Label unmittelbar davor. Steht ein Platzhalter da (Zeilen einer Erfassungstabelle,
            # Suchfelder), ist er der Name: Der Browser nimmt ihn ohnehin als Notbehelf, hier wird er
            # ausdrücklich gesetzt.
            platzhalter = (_text(_attribut(attrs, 'placeholder') or '') if name != 'select' else '')
            if platzhalter:
                edits.append(_einfuegen(html, m, ' aria-label="%s"' % _html.escape(platzhalter, quote=True)))
            continue
        label = ziel['label']
        if template_tiefe:
            edits.append(_einfuegen(html, m, ' aria-label="%s"' % _html.escape(ziel['text'], quote=True)))
            continue
        if _hat_attribut(attrs, ':id') or _hat_attribut(attrs, 'x-bind:id'):
            edits.append(_einfuegen(html, m, ' aria-label="%s"' % _html.escape(ziel['text'], quote=True)))
            continue
        if vorhandene_id:
            feld_id = vorhandene_id
        else:
            zaehler += 1
            feld_id = 'fn-%d' % zaehler
            edits.append(_einfuegen(html, m, ' id="%s"' % feld_id))
        edits.append(_einfuegen(html, label['tag'], ' for="%s"' % _html.escape(feld_id, quote=True)))

    if not edits:
        return html
    for pos_, text in sorted(edits, key=lambda e: e[0], reverse=True):
        html = html[:pos_] + text + html[pos_:]
    return html
