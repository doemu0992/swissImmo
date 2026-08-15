"""Das Benutzermodell von swissImmo.

Django erlaubt den Wechsel des Benutzermodells nach Produktivgang praktisch
nicht mehr. Deshalb steht dieser Schritt am Anfang der Mandantenfähigkeit und
nicht in ihrer Mitte — siehe `docs/ETAPPE-3-USER-MODEL.md`.

WARUM ``db_table = 'auth_user'``
--------------------------------
Das Modell übernimmt die **bestehende** Tabelle, statt eine neue anzulegen und
die Daten hinüberzukopieren. Der Grund liegt nicht in der Bequemlichkeit,
sondern in den 15 Fremdschlüsselspalten, die in der Datenbank auf ``auth_user``
zeigen.

Beim Kopieren in eine neue Tabelle hätte Djangos Zustand behauptet, diese
Fremdschlüssel zeigten auf das neue Modell — die Datenbank hätte sie aber
weiter auf ``auth_user`` gerichtet. Django erzeugt dafür **von sich aus keine
Operation**, weil sich aus seiner Sicht nichts geändert hat. Die Abweichung
wäre unbemerkt bestehen geblieben und beim PostgreSQL-Umzug mitgewandert.

Mit derselben Tabelle stimmen Zustand und Datenbank überein: Keine Datenzeile
wird bewegt, keine ID ändert sich, kein Passwort-Hash, keine Sitzung, kein
Gruppeneintrag. Der Name der Tabelle ist der kleine Preis dafür — und er ist
ehrlich, es *ist* die Benutzertabelle.

Die Namen der Zwischentabellen für Gruppen und Einzelrechte leitet Django aus
``db_table`` ab; sie heissen also weiterhin ``auth_user_groups`` und
``auth_user_user_permissions``. Nur die Spalte darin folgt dem Modellnamen —
aus ``user_id`` wird ``benutzer_id``. Das ist der einzige Eingriff, den die
Übernahme auf einer Bestandsdatenbank vornimmt; ``manage.py
benutzer_uebernahme`` erledigt ihn.

KEINE ZUSÄTZLICHEN FELDER
-------------------------
Der Bezug zur Organisation gehört in Etappe 4, nicht hierher. Ein Custom User
Model kann später jederzeit Felder bekommen; der Wechsel selbst lässt sich nur
einmal sauber machen. Wer beides zusammenlegt, kann bei einem Fehler nicht mehr
sagen, welcher Teil ihn verursacht hat.
"""
from django.contrib.auth.models import AbstractUser


class Benutzer(AbstractUser):
    """Team-, Eigentümer- und Mieterkonten.

    Erbt unverändert von ``AbstractUser``. Die Rollen hängen weiterhin an den
    Django-Gruppen (siehe ``core/auth.py``) — daran ändert dieser Schritt
    nichts.
    """

    class Meta:
        db_table = 'auth_user'
        verbose_name = 'Benutzer'
        verbose_name_plural = 'Benutzer'
