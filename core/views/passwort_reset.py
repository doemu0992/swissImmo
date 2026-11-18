"""Passwort vergessen mit Bremse.

Djangos `PasswordResetView` verschickt bei jedem POST eine Mail an eine bekannte Adresse. Ohne Bremse lässt sich damit
ein fremdes Postfach fluten oder der Mailversand der Plattform aufbrauchen. Die Bremse zählt je Absender-IP und je
Adresse; über dem Limit passiert nichts, und die Antwort ist dieselbe wie sonst («Mail ist unterwegs»): Wer anfragt,
erfährt weder, ob die Adresse bekannt ist, noch, dass er gebremst wurde.
"""
import hashlib

from django.contrib.auth import views as auth_views
from django.shortcuts import redirect

from core.utils.throttle import client_ip, rate_limit

LIMIT_JE_IP = 10          # Anfragen je Stunde und IP
LIMIT_JE_ADRESSE = 3      # Anfragen je Stunde und Adresse


class PasswortVergessenView(auth_views.PasswordResetView):
    def post(self, request, *args, **kwargs):
        adresse = (request.POST.get('email') or '').strip().lower()
        spur = hashlib.sha256(adresse.encode()).hexdigest()[:24]
        erlaubt_ip = rate_limit(f'pwreset:ip:{client_ip(request)}', LIMIT_JE_IP, 3600)
        erlaubt_adresse = rate_limit(f'pwreset:adr:{spur}', LIMIT_JE_ADRESSE, 3600)
        if not (erlaubt_ip and erlaubt_adresse):
            return redirect(self.success_url or 'password_reset_done')
        return super().post(request, *args, **kwargs)
