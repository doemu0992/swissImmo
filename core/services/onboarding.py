"""Eine Organisation entsteht — mit ihrem ersten Inhaber.

DAS PROBLEM, DAS DIESER DIENST LÖST
-----------------------------------
`core/views/fw/benutzer.py` kann Kollegen zu einer Organisation hinzufügen —
es liest dafür `request.organisation`. Wer noch keine Organisation hat, kommt
damit nicht hinein: Um jemanden hinzuzufügen, muss man bereits Mitglied sein.

Diesen Knoten löst genau dieser Dienst, und sonst nichts. Alles danach —
Kollegen einladen, Rollen vergeben — kann die bestehende Benutzerverwaltung.

Gemessen am 20.09.2026: Ausserhalb von Tests und Fixtures legte nur ein
Notbehelf in `core/utils/market_data.py:172` eine Organisation an
(`Organisation.objects.create(firma="Meine Verwaltung")`), und der stammt aus
einem Marktdaten-Update.

DIE HEIKLE STELLE IST NICHT DIE, DIE ICH ERWARTET HATTE
-------------------------------------------------------
`docs/PHASE-3-ONBOARDING.md` entwarf hier einen benannten Ausstieg aus dem
Mandantenkontext (`alle_organisationen`), weil eine Organisation ohne Kontext
entsteht. Beim Bauen stellte sich heraus: **den braucht es nicht.**

Zwei Gründe, beide im Bestand nachgelesen:

1. `Organisation` trägt **keinen** `TenantManager`. Sie IST der Anker, an dem
   der Kontext hängt — ein Filter auf sich selbst wäre zirkulär.
2. `TenantManager` filtert **Lesen**, nicht Schreiben. Der Kommentar in
   `core/tenancy.py` sagt es wörtlich: «Schreiben braucht keinen Kontext,
   Lesen schon», weil ein `create` nichts herausgibt.

Der Entwurf hat den Knoten also überzeichnet. Was bleibt, ist eine ANDERE
Sorgfalt, und sie steht unten bei `_pruefe`.

WAS ER NICHT TUT
----------------
Kein Zahlungsvorgang, keine E-Mail, keine öffentliche Registrierung. Der
Einstieg läuft über den Management-Command `organisation_anlegen`, also über
jemanden mit Zugang zum Server. Das ist Absicht, siehe die Begründung dort.

UND KEINE TESTPHASE
-------------------
Eine frühere Fassung dieses Dienstes setzte `abo_start`/`abo_bis` auf der
Organisation. Beide Felder sind am 21.09.2026 wieder entfernt worden, und
dieser Dienst deshalb mit ihnen. Der Grund ist einer, nicht zwei:

`docs/PLAN-V7.md` §4.1 gibt beiden Angaben eine andere Heimat —
`abo.Abonnement` mit den Feldern für Stufe, Status und «Testphase bis». Zwei
Datumsfelder hier vorweg wären in Phase 3 die zweite Quelle für dieselbe
Auskunft, und zwar die stille: Nichts im Bestand las sie (gemessen vor dem
Entfernen), also hätte auch nichts widersprochen, wenn sie auseinanderlaufen.

WAS DAMIT NICHT MEHR FESTGEHALTEN WIRD, und das ehrlich gesagt:
`Organisation` hat **kein** Feld für ihr Entstehungsdatum. Beim Entfernen
stand als zweite Begründung, `Organisation.erstellt_am` halte den Beginn
ohnehin fest — das war falsch. Das Feld an `crm/models.py:183` gehört zu
`Mitgliedschaft`. Aufgefallen ist es dem Test, nicht dem Lesen.

Mittelbar steht der Zeitpunkt damit in der Mitgliedschaft des ersten
Inhabers, die im selben `atomic`-Block entsteht. Ein eigenes Feld gehört,
wenn es eines braucht, zu `abo.Abonnement` — nicht hierher.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import transaction


class OnboardingFehler(ValueError):
    """Die Angaben tragen nicht — mit einem Satz, der sagt warum."""


def _pruefe(firma: str, benutzername: str, email: str) -> None:
    """Was schiefgehen kann, bevor etwas entsteht.

    DIE EIGENTLICHE SORGFALT LIEGT HIER, nicht beim Mandantenkontext.

    Eine Organisation ist in diesem System der Mandant — der Anker, an dem
    die gesamte Datentrennung hängt. Eine versehentlich angelegte ist kein
    Schönheitsfehler, sondern ein Datensatz, den niemand besitzt und den
    hinterher niemand zuordnen kann. Deshalb scheitert dieser Dienst lieber
    laut, als etwas Halbes anzulegen.
    """
    if not (firma or '').strip():
        raise OnboardingFehler('Ohne Firmennamen entsteht keine Organisation.')
    if not (benutzername or '').strip():
        raise OnboardingFehler('Der erste Inhaber braucht einen Benutzernamen.')
    if not (email or '').strip():
        raise OnboardingFehler(
            'Der erste Inhaber braucht eine E-Mail — sonst gibt es keinen Weg, '
            'sein Passwort zurückzusetzen, und niemanden zu erreichen.')


@transaction.atomic
def organisation_anlegen(firma: str, benutzername: str, email: str,
                         passwort: str | None = None,
                         vorname: str = '', nachname: str = ''):
    """Legt Organisation, Inhaber und Mitgliedschaft an. Gibt beide zurück.

    ALLES ODER NICHTS (`transaction.atomic`): Eine Organisation ohne Inhaber
    wäre genau die Waise, vor der `_pruefe` schützt — nur eine Zeile später
    entstanden. Bricht das Anlegen der Mitgliedschaft ab, darf die
    Organisation nicht zurückbleiben.

    Ein BESTEHENDER Benutzer wird wiederverwendet, nicht überschrieben. Das
    ist der Fall «dieselbe Person arbeitet für zwei Verwaltungen», den
    `crm.Mitgliedschaft` ausdrücklich zulässt (siehe die Begründung am
    Modell). Sein Passwort bleibt, wie es ist.
    """
    from crm.models import Mitgliedschaft, Organisation

    firma = (firma or '').strip()
    benutzername = (benutzername or '').strip()
    email = (email or '').strip()
    _pruefe(firma, benutzername, email)

    Benutzer = get_user_model()

    # `abo_plan` bleibt bewusst auf dem Vorgabewert des Modells (`'pro'`).
    #
    # OFFEN UND BEKANNT: Die bestätigte Struktur aus `docs/MARKT.md` heisst
    # start/team/professional/enterprise — `'pro'` gibt es darin nicht.
    # `docs/PLAN-V7.md` D7 entscheidet, wohin das führt: `abo_plan` entfällt
    # zugunsten von `abo.Abonnement`, und die Marktnamen kommen als Klartext
    # in `core/funktionen.py`. Das ist Phase 3 (E3) und hier absichtlich
    # nicht vorweggenommen: Ein Wert, den `ABO_CHOICES` nicht kennt, wäre
    # schlimmer als der falsche aus der alten Liste, weil ihn keine
    # Auswertung je treffen würde.
    #
    # Solange keine Prüfstelle den Plan abfragt (gemessen: keine — die
    # Stufe kommt heute aus `core/funktionen.py:stufe_von`), hat das keine
    # Wirkung ausser auf der Abo-Seite.
    organisation = Organisation.objects.create(firma=firma)

    benutzer = Benutzer.objects.filter(username__iexact=benutzername).first()
    neu = benutzer is None
    if neu:
        benutzer = Benutzer.objects.create_user(
            username=benutzername, email=email, password=passwort,
            first_name=vorname, last_name=nachname)

    # WARUM `update_or_create` UND NICHT `create`:
    # Ein bestehender Benutzer kann bereits Mitglied dieser Organisation sein,
    # wenn der Command zweimal mit denselben Angaben läuft. Dann soll die
    # Rolle stimmen und kein zweiter Datensatz entstehen.
    #
    # Kein Kontext nötig: `create` liest nichts. `update_or_create` liest
    # zuerst — und genau deshalb steht hier der Kontext der NEUEN
    # Organisation, nicht keiner. Sonst suchte die Abfrage im Kontext des
    # Aufrufers (bei einem Command: keinem) und der `TenantManager` würfe.
    from core.tenancy import organisation_kontext
    with organisation_kontext(organisation):
        mitgliedschaft, _ = Mitgliedschaft.objects.update_or_create(
            benutzer=benutzer, organisation=organisation,
            defaults={'rolle': Mitgliedschaft.ROLLE_INHABER})

    # Die Gruppe trägt die Rechte, die Mitgliedschaft die Zugehörigkeit.
    # `core/views/fw/benutzer.py` hält beide parallel; wer hier nur eines
    # setzt, baut einen Inhaber, der nichts darf.
    from django.contrib.auth.models import Group
    gruppe, _ = Group.objects.get_or_create(name=Mitgliedschaft.ROLLE_INHABER)
    benutzer.groups.add(gruppe)

    return organisation, benutzer, neu
