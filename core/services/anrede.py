"""Der Gruss am Anfang einer Mail: «Guten Tag Herr Muster».

Eine Stelle für alle Mailwege. Kein Platzhalterwort («Mieter»): Ist nichts über
den Empfänger bekannt, steht «Guten Tag» allein. Briefe («Sehr geehrter Herr …»)
bleiben bei `platzhalter.briefanrede`.

Die Sprache setzt der Aufrufer mit `in_sprache` (die des Empfängers) oder gibt sie
als `sprache` mit; hier wird nur übersetzt, nichts geraten.
"""
from django.utils.translation import gettext

from core.services.dokumentsprache import in_sprache

#: Nur diese beiden Werte sind eine Anrede. «Familie», «Firma» oder ein leerer Wert
#: führen zum Gruss mit vollem Namen.
ANREDEN = ('Herr', 'Frau')


def _anrede(wert):
    wert = (wert or '').strip()
    return wert if wert in ANREDEN else ''


def nachname_aus(voller_name):
    """Letztes Wort eines Namens («Anna Meier» -> «Meier»); '' bei leerem Namen."""
    teile = (voller_name or '').split()
    return teile[-1] if teile else ''


def _gruss(anrede, vorname, nachname):
    vorname, nachname = (vorname or '').strip(), (nachname or '').strip()
    if nachname and anrede == 'Herr':
        return gettext('Guten Tag Herr %(name)s') % {'name': nachname}
    if nachname and anrede == 'Frau':
        return gettext('Guten Tag Frau %(name)s') % {'name': nachname}
    voll = f"{vorname} {nachname}".strip()
    if voll:
        return gettext('Guten Tag %(name)s') % {'name': voll}
    return gettext('Guten Tag')


def mail_gruss(anrede='', vorname='', nachname='', firma='', kontaktperson='', sprache=None):
    """«Guten Tag Herr Muster» / «Guten Tag Frau Muster» / «Guten Tag Vorname Nachname» / «Guten Tag».

    - Person mit Anrede Herr oder Frau und Nachname: «Guten Tag Herr Muster».
    - Person ohne bekannte Anrede: «Guten Tag Vorname Nachname».
    - `firma` (Name der Firma, Kunden-Typ Firma): mit `kontaktperson` wird diese
      gegrüsst (die Anrede gilt dann ihr), sonst steht «Guten Tag <Firma>».
    - Nichts bekannt: «Guten Tag».
    """
    def erzeugen():
        a = _anrede(anrede)
        if firma:
            name = firma.strip() if isinstance(firma, str) else ''
            kp = (kontaktperson or '').strip()
            if kp:
                if a:
                    return _gruss(a, '', nachname_aus(kp))
                return gettext('Guten Tag %(name)s') % {'name': kp}
            return gettext('Guten Tag %(name)s') % {'name': name} if name else gettext('Guten Tag')
        return _gruss(a, vorname, nachname)

    if sprache:
        with in_sprache(sprache):
            return erzeugen()
    return erzeugen()


def mieter_gruss(mieter, sprache=None):
    """Gruss an einen `crm.Mieter` (Privatperson mit Anrede, Firma/Verein mit Kontaktperson).

    Die Anrede des Datensatzes gilt nur für eine Privatperson: Bei einer Firma ist sie ein
    Vorgabewert ohne Aussage über die Kontaktperson."""
    if mieter is None:
        return mail_gruss(sprache=sprache)
    if mieter.typ in ('firma', 'verein') and mieter.firmen_name:
        return mail_gruss(firma=mieter.firmen_name, kontaktperson=mieter.kontaktperson, sprache=sprache)
    return mail_gruss(mieter.anrede, mieter.vorname, mieter.nachname, sprache=sprache)


def eigentuemer_gruss(eigentuemer, sprache=None):
    """Gruss an einen `crm.Eigentuemer`.

    Mit Anrede (Herr/Frau) wird die Person gegrüsst: die Kontaktperson, sonst der Eigentümer
    selbst (letztes Wort des Namens als Nachname). Ohne Anrede bleibt es wie bisher bei der
    Kontaktperson bzw. dem Namen oder der Firma."""
    if eigentuemer is None:
        return mail_gruss(sprache=sprache)
    kp = (eigentuemer.kontaktperson or '').strip()
    name = (eigentuemer.firma_oder_name or '').strip()
    a = _anrede(getattr(eigentuemer, 'anrede', ''))
    if a:
        return mail_gruss(a, '', nachname_aus(kp or name), sprache=sprache)
    return mail_gruss(firma=name, kontaktperson=kp, sprache=sprache)


def handwerker_gruss(handwerker, sprache=None):
    """Gruss an einen `crm.Handwerker`: die Kontaktperson, sonst die Firma (der Stamm kennt keine Anrede)."""
    if handwerker is None:
        return mail_gruss(sprache=sprache)
    return mail_gruss(firma=handwerker.firma or '', kontaktperson=handwerker.kontaktperson or '',
                      sprache=sprache)


def benutzer_gruss(benutzer, sprache=None):
    """Gruss an ein Mitglied der Verwaltung: «Guten Tag Vorname Nachname» aus dem Benutzer."""
    if benutzer is None:
        return mail_gruss(sprache=sprache)
    return mail_gruss(vorname=benutzer.first_name, nachname=benutzer.last_name, sprache=sprache)


def eigentuemer_gruss_html(eigentuemer):
    """Der deutsche Gruss an einen Eigentümer, für HTML-Mails maskiert (die Mails der STWEG sind deutsch)."""
    from django.utils.html import escape
    return escape(eigentuemer_gruss(eigentuemer, 'de'))
