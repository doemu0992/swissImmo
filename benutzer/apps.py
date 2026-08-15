from django.apps import AppConfig


class BenutzerConfig(AppConfig):
    # `AutoField`, nicht `BigAutoField` — dasselbe, was `django.contrib.auth`
    # verwendet. Das Modell übernimmt die bestehende Tabelle `auth_user`, deren
    # `id` ein 32-Bit-Integer ist, ebenso die 15 Fremdschlüsselspalten, die
    # darauf zeigen. Mit `BigAutoField` würde das Modell `bigint` behaupten,
    # während in der Datenbank `integer` steht. Auf SQLite bliebe das
    # unsichtbar; beim Wechsel auf PostgreSQL (P1.4) wäre es genau die stille
    # Abweichung zwischen Djangos Zustand und der Datenbank, die dieser Weg
    # vermeiden soll.
    default_auto_field = 'django.db.models.AutoField'
    name = 'benutzer'
    verbose_name = 'Benutzer'
