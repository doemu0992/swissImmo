"""Zwei-Faktor-Anmeldung: Einrichtung, zweiter Schritt beim Login, Notfallcodes.

DER ENTSCHEIDENDE PUNKT DIESES MODULS

Django meldet mit `login()` an, und ab diesem Aufruf gilt der Benutzer als
authentifiziert — für jede View, jeden Manager, jeden Test. Ein zweiter Faktor,
der **nach** `login()` abgefragt wird, ist deshalb kein zweiter Faktor, sondern
eine Nachfrage: Wer die Zwischenseite umgeht (Adresse direkt eintippen), ist
bereits drin.

Hier läuft es darum anders herum. `zweifaktor_login` prüft Name und Passwort mit
`authenticate()`, ruft `login()` aber **nicht** auf, solange ein Faktor aussteht.
Bis zum richtigen Code steht in der Sitzung nur eine Merknotiz:

    request.session['zf_wartend'] = <benutzer-id>
    request.session['zf_seit']    = <zeitstempel>

Aus dieser Notiz folgt kein einziges Recht. Wer sie hat und den zweiten Schritt
nicht besteht, ist nicht angemeldet — er hat nur eine Sitzung mit einer Zahl
darin.

WARUM DIE NOTIZ VERFÄLLT

`zf_seit` begrenzt sie auf `WARTEFRIST`. Ohne das bliebe ein Rechner, an dem
jemand das Passwort eingegeben und dann aufgegeben hat, beliebig lange im
Zustand «Passwort schon bestanden» — der nächste am selben Gerät bräuchte nur
noch den Code, nicht mehr beides.
"""
import secrets
from functools import wraps

from django.contrib import messages
from django.contrib.auth import authenticate, login as django_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters

from core.models import SicherheitsEreignis, Wiederherstellungscode, ZweiterFaktor
from core.services import totp

#: Wie lange die Merknotiz zwischen Passwort und Code gilt (Sekunden).
WARTEFRIST = 5 * 60

#: So viele Fehlversuche im zweiten Schritt, dann ist die Notiz verbraucht.
#: Ohne Deckel liesse sich ein sechsstelliger Code in Ruhe durchprobieren —
#: eine Million Möglichkeiten sind für ein Skript kein Hindernis.
MAX_VERSUCHE = 5

#: Anzahl und Form der Notfallcodes.
ANZAHL_CODES = 10


def _ip(request):
    weiter = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return (weiter.split(',')[0].strip() if weiter else request.META.get('REMOTE_ADDR')) or None


def _sicherheit(aktion, objekt='', details='', request=None):
    """Ins Betreiberlog schreiben — auch ohne Anmeldung und ohne Mandantenkontext.

    Der Anmeldevorgang hat naturgemäss keine Organisation (siehe
    `SicherheitsEreignis`). Fehler beim Protokollieren dürfen die Anmeldung
    nicht anhalten.
    """
    try:
        SicherheitsEreignis.objects.create(
            aktion=aktion, objekt=objekt[:200], details=details[:2000],
            ip_adresse=_ip(request) if request else None)
    except Exception:                                          # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Schritt 1: Passwort
# ---------------------------------------------------------------------------

@never_cache
@sensitive_post_parameters('password')
def zweifaktor_login(request, template_name='core/login.html'):
    """Ersetzt `auth_views.LoginView` — meldet nur an, wenn kein Faktor aussteht."""
    weiter = request.POST.get('next') or request.GET.get('next') or ''
    if request.method != 'POST':
        return render(request, template_name, {'next': weiter})

    benutzer = authenticate(request,
                            username=request.POST.get('username', ''),
                            password=request.POST.get('password', ''))
    if benutzer is None or not benutzer.is_active:
        # Die Meldung nennt bewusst nicht, WELCHER Teil falsch war.
        return render(request, template_name, {
            'next': weiter,
            'fehler': 'Benutzername oder Passwort stimmt nicht.'}, status=200)

    faktor = ZweiterFaktor.objects.filter(benutzer=benutzer).first()
    if faktor is None or not faktor.ist_aktiv:
        django_login(request, benutzer)
        return redirect(weiter or 'nach_login')

    # Passwort stimmt, Faktor steht aus: NICHT anmelden, nur merken.
    request.session.cycle_key()       # gegen Session Fixation vor dem zweiten Schritt
    request.session['zf_wartend'] = benutzer.pk
    request.session['zf_seit'] = timezone.now().timestamp()
    request.session['zf_versuche'] = 0
    request.session['zf_next'] = weiter
    # Das Projekt hat ZWEI Anmeldeverfahren (`AUTHENTICATION_BACKENDS`:
    # CaseInsensitiveModelBackend und ModelBackend). `authenticate()` merkt
    # sich am Benutzerobjekt, welches gegriffen hat; im zweiten Schritt wird
    # der Benutzer aber frisch aus der Datenbank geladen und trägt die Angabe
    # nicht mehr. `login()` wirft dann:
    #   ValueError: You have multiple authentication backends configured …
    # Deshalb wandert das Verfahren hier durch die Sitzung mit — und zwar
    # dasjenige, das tatsächlich geprüft hat, statt eines geratenen.
    request.session['zf_backend'] = getattr(benutzer, 'backend', '')
    return redirect('zweifaktor_bestaetigen')


def _wartenden_benutzer(request):
    """Der Benutzer aus der Merknotiz — oder `None`, wenn sie fehlt/verfallen ist."""
    pk = request.session.get('zf_wartend')
    seit = request.session.get('zf_seit')
    if not pk or not seit:
        return None
    if timezone.now().timestamp() - float(seit) > WARTEFRIST:
        _notiz_loeschen(request)
        return None
    from benutzer.models import Benutzer

    # Anmeldevorgang: Hier gibt es naturgemäss keinen Mandantenkontext, und der
    # Benutzer ist kein Mandantendatum. Bewusster, benannter Zugriff.
    return Benutzer.objects.filter(pk=pk, is_active=True).first()


def _notiz_loeschen(request):
    for schluessel in ('zf_wartend', 'zf_seit', 'zf_versuche', 'zf_next', 'zf_backend'):
        request.session.pop(schluessel, None)


def _anmelden(request, benutzer):
    """`login()` mit dem Verfahren, das im ersten Schritt geprüft hat."""
    backend = request.session.get('zf_backend') or ''
    weiter = request.session.get('zf_next') or ''
    _notiz_loeschen(request)
    django_login(request, benutzer, backend=backend or None)
    return weiter


# ---------------------------------------------------------------------------
# Schritt 2: Code
# ---------------------------------------------------------------------------

@never_cache
@sensitive_post_parameters('code')
def zweifaktor_bestaetigen(request):
    benutzer = _wartenden_benutzer(request)
    if benutzer is None:
        return redirect('login')

    if request.method != 'POST':
        return render(request, 'core/zweifaktor_bestaetigen.html', {})

    eingabe = (request.POST.get('code') or '').strip()
    faktor = ZweiterFaktor.objects.filter(benutzer=benutzer).first()

    if faktor is not None and faktor.pruefen(eingabe):
        weiter = _anmelden(request, benutzer)
        return redirect(weiter or 'nach_login')

    if _notfallcode_einloesen(benutzer, eingabe):
        weiter = _anmelden(request, benutzer)
        _sicherheit('Notfallcode eingelöst', benutzer.get_username(), request=request)
        offen = Wiederherstellungscode.objects.filter(
            benutzer=benutzer, eingeloest_am__isnull=True).count()
        messages.warning(request,
                         f'Mit Notfallcode angemeldet. Noch {offen} Code(s) übrig — '
                         'bei wenigen übrigen neue erzeugen.')
        return redirect(weiter or 'nach_login')

    versuche = int(request.session.get('zf_versuche', 0)) + 1
    request.session['zf_versuche'] = versuche
    _sicherheit('Zweiter Faktor falsch', benutzer.get_username(),
                f'Versuch {versuche} von {MAX_VERSUCHE}', request=request)
    if versuche >= MAX_VERSUCHE:
        _notiz_loeschen(request)
        return render(request, 'core/zweifaktor_bestaetigen.html', {
            'abgebrochen': True,
            'fehler': 'Zu viele Fehlversuche. Bitte von vorne anmelden.'})
    return render(request, 'core/zweifaktor_bestaetigen.html', {
        'fehler': f'Der Code stimmt nicht ({versuche} von {MAX_VERSUCHE}).'})


def _notfallcode_einloesen(benutzer, eingabe) -> bool:
    """Notfallcode prüfen und verbrauchen. Jeder Code gilt genau einmal."""
    sauber = (eingabe or '').strip().replace(' ', '').replace('-', '').lower()
    if len(sauber) < 8:
        return False
    for kandidat in Wiederherstellungscode.objects.filter(
            benutzer=benutzer, eingeloest_am__isnull=True):
        if check_password(sauber, kandidat.code_hash):
            kandidat.eingeloest_am = timezone.now()
            kandidat.save(update_fields=['eingeloest_am'])
            return True
    return False


# ---------------------------------------------------------------------------
# Einrichtung
# ---------------------------------------------------------------------------

def _neue_codes(benutzer):
    """Zehn neue Notfallcodes: im Klartext zurückgeben, als Hash speichern."""
    Wiederherstellungscode.objects.filter(benutzer=benutzer).delete()
    klartext = []
    for _ in range(ANZAHL_CODES):
        roh = secrets.token_hex(5)            # 10 Zeichen, eindeutig genug
        klartext.append(f'{roh[:5]}-{roh[5:]}')
        Wiederherstellungscode.objects.create(benutzer=benutzer,
                                              code_hash=make_password(roh))
    return klartext


@never_cache
@login_required
@sensitive_post_parameters('code')
def zweifaktor_einrichten(request):
    faktor = ZweiterFaktor.objects.filter(benutzer=request.user).first()
    if faktor is not None and faktor.ist_aktiv:
        return redirect('zweifaktor_uebersicht')

    if faktor is None:
        faktor = ZweiterFaktor.objects.create(benutzer=request.user,
                                              geheimnis=totp.geheimnis_erzeugen())

    if request.method == 'POST':
        if faktor.pruefen(request.POST.get('code', '')):
            faktor.bestaetigt_am = timezone.now()
            faktor.save(update_fields=['bestaetigt_am'])
            codes = _neue_codes(request.user)
            _sicherheit('Zweiter Faktor eingerichtet', request.user.get_username(),
                        request=request)
            return render(request, 'core/zweifaktor_codes.html',
                          {'codes': codes, 'frisch': True})
        fehler = 'Der Code stimmt nicht. Uhrzeit des Telefons prüfen und neu versuchen.'
    else:
        fehler = ''

    konto = request.user.email or request.user.get_username()
    url = totp.einrichtungs_url(faktor.geheimnis, konto)
    return render(request, 'core/zweifaktor_einrichten.html', {
        'qr': totp.qr_svg(url),
        'geheimnis': faktor.geheimnis,
        'fehler': fehler,
        'pflicht_hinweis': _pflicht_fuer(request.user),
    })


@never_cache
@login_required
def zweifaktor_uebersicht(request):
    faktor = ZweiterFaktor.objects.filter(benutzer=request.user).first()
    return render(request, 'core/zweifaktor_uebersicht.html', {
        'faktor': faktor if (faktor and faktor.ist_aktiv) else None,
        'offene_codes': Wiederherstellungscode.objects.filter(
            benutzer=request.user, eingeloest_am__isnull=True).count(),
        'pflicht': _pflicht_fuer(request.user),
    })


@never_cache
@login_required
def zweifaktor_codes_neu(request):
    if request.method != 'POST':
        return redirect('zweifaktor_uebersicht')
    faktor = ZweiterFaktor.objects.filter(benutzer=request.user).first()
    if faktor is None or not faktor.ist_aktiv:
        return redirect('zweifaktor_einrichten')
    codes = _neue_codes(request.user)
    _sicherheit('Notfallcodes neu erzeugt', request.user.get_username(), request=request)
    return render(request, 'core/zweifaktor_codes.html', {'codes': codes, 'frisch': False})


@never_cache
@login_required
@sensitive_post_parameters('password')
def zweifaktor_aus(request):
    """Abschalten — nur gegen das Passwort.

    Ohne diese Rückfrage genügte ein kurz unbeaufsichtigter Bildschirm, um den
    zweiten Faktor zu entfernen; der Schutz liesse sich dann mit genau dem
    Zugang aufheben, gegen den er gerichtet ist.
    """
    if request.method != 'POST':
        return redirect('zweifaktor_uebersicht')
    if _pflicht_fuer(request.user):
        messages.error(request, 'Ihre Verwaltung verlangt den zweiten Faktor — '
                                'er lässt sich nicht abschalten.')
        return redirect('zweifaktor_uebersicht')
    if not request.user.check_password(request.POST.get('password', '')):
        messages.error(request, 'Das Passwort stimmt nicht — nichts geändert.')
        return redirect('zweifaktor_uebersicht')
    ZweiterFaktor.objects.filter(benutzer=request.user).delete()
    Wiederherstellungscode.objects.filter(benutzer=request.user).delete()
    _sicherheit('Zweiter Faktor abgeschaltet', request.user.get_username(), request=request)
    messages.success(request, 'Zwei-Faktor-Anmeldung abgeschaltet.')
    return redirect('zweifaktor_uebersicht')


# ---------------------------------------------------------------------------
# Pflicht
# ---------------------------------------------------------------------------

def _pflicht_fuer(benutzer) -> bool:
    """Verlangt eine der Verwaltungen dieses Kontos den zweiten Faktor?

    ODER, nicht UND: Wer für Verwaltung A arbeitet, die es verlangt, kann sich
    dem nicht dadurch entziehen, dass er auch in Verwaltung B Mitglied ist.

    `alle_organisationen`: Der Aufruf geschieht beim Anmelden und in der
    Middleware, also ohne gesetzten Mandantenkontext — und er fragt bewusst
    ÜBER alle Verwaltungen dieses Kontos.
    """
    if not getattr(benutzer, 'is_authenticated', False):
        return False
    from crm.models import Mitgliedschaft

    return Mitgliedschaft.alle_organisationen.filter(
        benutzer=benutzer, organisation__zweifaktor_pflicht=True).exists()


def zweifaktor_erzwingen(view):
    """Decorator-Variante der Pflicht — für einzelne Einstiegspunkte."""
    @wraps(view)
    def huelle(request, *args, **kwargs):
        if _pflicht_fuer(request.user):
            faktor = ZweiterFaktor.objects.filter(benutzer=request.user).first()
            if faktor is None or not faktor.ist_aktiv:
                return redirect('zweifaktor_einrichten')
        return view(request, *args, **kwargs)
    return huelle
