"""Robuste Anmeldung für das Mieter-/Eigentümer-/Team-Login.

Der Benutzername ist bei Portal-Konten die E-Mail-Adresse. Daraus ergeben
sich in der Praxis drei Stolperfallen, die das Standard-``ModelBackend``
nicht abfängt:

1. **Gross-/Kleinschreibung** – Mobilgeräte gross-schreiben den ersten
   Buchstaben automatisch (``Doemu…`` statt ``doemu…``).
2. **Führende/anhängende Leerzeichen** aus Copy-Paste.
3. **Benutzernamen-Kollision** – gehört dieselbe E-Mail bereits einem
   Team-/Admin-Konto, bekommt das neue Mieter-Konto intern einen anderen
   Benutzernamen. Beim Login mit der reinen E-Mail träfe das exakte
   Username-Matching sonst nur das erste (falsche) Konto.

Dieses Backend sammelt daher **alle** Konten, deren Benutzername ODER
E-Mail (case-insensitiv) zur Eingabe passen, und meldet dasjenige an, dessen
Passwort stimmt. Da verschiedene Konten verschiedene Passwörter haben, ist
das eindeutig – die Eingabe landet immer auf dem Konto, dessen Passwort
eingegeben wurde.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class CaseInsensitiveModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return None
        ident = username.strip()
        if not ident:
            return None

        kandidaten = list(UserModel._default_manager.filter(
            Q(username__iexact=ident) | Q(email__iexact=ident)
        )[:10])
        if not kandidaten:
            # Timing-Angriffe erschweren: trotzdem einmal hashen
            UserModel().set_password(password)
            return None

        treffer = [u for u in kandidaten
                   if u.check_password(password) and self.user_can_authenticate(u)]
        if not treffer:
            return None
        # Eindeutig, weil Passwörter je Konto verschieden sind. Bei (sehr
        # unwahrscheinlichem) Gleichstand: aktive Konten und Portal-Konten
        # (mieter_profil/mandant_profil) bevorzugen.
        if len(treffer) > 1:
            treffer.sort(key=lambda u: (
                not u.is_active,
                getattr(u, 'mieter_profil', None) is None and getattr(u, 'mandant_profil', None) is None,
            ))
        return treffer[0]
