"""Zugänglicher Name von Formularfeldern, aus fertigem HTML gelesen (DESIGN-27).

Ein Feld hat einen zugänglichen Namen, wenn eines davon zutrifft (in dieser Reihenfolge der
HTML-AAM-Regeln, ohne Platzhalter: Er ist keine Beschriftung, sondern verschwindet beim Tippen):

* `aria-labelledby` verweist auf ein vorhandenes Element mit Text,
* `aria-label` hat Text,
* ein `<label for=ID>` mit Text gehört zur `id` des Feldes,
* ein umschliessendes `<label>` mit Text,
* `title` hat Text (letzter Notbehelf des Browsers).

Nicht geprüft werden Felder ohne Eingabe (`hidden`, Knöpfe) und Felder, die der Browser nicht
anzeigt (`type=hidden`, `disabled` bleibt geprüft: Ein Screenreader liest es trotzdem).
"""
from html.parser import HTMLParser

OHNE_EINGABE = {'hidden', 'submit', 'button', 'reset', 'image'}
STEUERELEMENTE = {'input', 'select', 'textarea'}
#: Elemente, die kein Text-Label tragen und deren Inhalt keine Beschriftung ist.
IGNORIERT_IM_LABEL = {'script', 'style'}


class _Leser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.felder = []                 # {'tag','typ','id','name','klasse','attrs','zeile','label_umschliessend'}
        self.label_fuer = {}             # id -> Text
        self.texte_nach_id = {}          # id -> Text (für aria-labelledby)
        self._labels = []                # Stapel offener <label>: {'for','text','felder'}
        self._ids_offen = []             # Stapel (id, Text-Sammler) für aria-labelledby
        self._skip = 0

    # -- Hilfen ---------------------------------------------------------

    @staticmethod
    def _attrs(attrs):
        return {k: (v if v is not None else '') for k, v in attrs}

    def handle_starttag(self, tag, attrs):
        a = self._attrs(attrs)
        if tag in IGNORIERT_IM_LABEL:
            self._skip += 1
        if a.get('id'):
            self._ids_offen.append((tag, a['id'], []))
        if tag == 'label':
            self._labels.append({'for': a.get('for', ''), 'text': [], 'felder': []})
        if tag in STEUERELEMENTE:
            typ = a.get('type', 'text' if tag == 'input' else tag).lower()
            feld = {'tag': tag, 'typ': typ, 'id': a.get('id', ''), 'name': a.get('name', ''),
                    'klasse': a.get('class', ''), 'attrs': a, 'zeile': self.getpos()[0],
                    'umschlossen': bool(self._labels)}
            self.felder.append(feld)
            for lab in self._labels:
                lab['felder'].append(feld)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in IGNORIERT_IM_LABEL and self._skip:
            self._skip -= 1
        if tag == 'label' and self._labels:
            lab = self._labels.pop()
            text = ' '.join(''.join(lab['text']).split())
            if lab['for'] and text:
                self.label_fuer.setdefault(lab['for'], text)
            for f in lab['felder']:
                if text:
                    f['label_text'] = text
        # offene Elemente mit id: Text beim passenden Ende festhalten (grob: letztes Element mit gleichem Tag)
        for i in range(len(self._ids_offen) - 1, -1, -1):
            if self._ids_offen[i][0] == tag:
                _t, i_d, sammler = self._ids_offen.pop(i)
                self.texte_nach_id[i_d] = ' '.join(''.join(sammler).split())
                break

    def handle_data(self, data):
        if self._skip:
            return
        for lab in self._labels:
            lab['text'].append(data)
        for _t, _i, sammler in self._ids_offen:
            sammler.append(data)


def felder_ohne_namen(text):
    """Liste der Felder in `text` (HTML), die keinen zugänglichen Namen haben."""
    leser = _Leser()
    leser.feed(text)
    leser.close()
    ohne = []
    for f in leser.felder:
        if f['typ'] in OHNE_EINGABE:
            continue
        a = f['attrs']
        if 'hidden' in a:                                   # nicht angezeigt, nicht in der Hilfstechnik
            continue
        if a.get('aria-labelledby') and any(leser.texte_nach_id.get(i) for i in a['aria-labelledby'].split()):
            continue
        if a.get('aria-label', '').strip():
            continue
        if f['id'] and leser.label_fuer.get(f['id']):
            continue
        if f.get('label_text'):
            continue
        if a.get('title', '').strip():
            continue
        ohne.append(f)
    return ohne, len(leser.felder)
