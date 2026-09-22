#!/usr/bin/env python3
"""Minimal .mo-Datei-Ausgenerierer — ohne gettext, nur Standardbibliothek."""
import argparse
import pathlib
import struct


def parse(pfad):
    """Raeumt eine .po auf: msgid -> msgstr. Ignoriert Mehrzahlformen."""
    text = pfad.read_text(encoding='utf-8')
    eintraege = {}
    schluessel = None
    ziel = None
    puffer = {}
    for zeile in text.split('\n'):
        zeile = zeile.strip()
        if zeile.startswith('#') or not zeile:
            continue
        if zeile.startswith('msgid '):
            if schluessel is not None and puffer.get('msgstr'):
                eintraege[schluessel] = puffer['msgstr']
            schluessel = zeile.split('"', 2)[1]
            puffer = {'msgstr': ''}
            ziel = 'msgid'
        elif zeile.startswith('msgstr '):
            puffer['msgstr'] = zeile.split('"', 2)[1]
            ziel = 'msgstr'
        elif zeile.startswith('"'):
            teil = zeile.strip('"')
            if ziel == 'msgid':
                schluessel += teil
            elif ziel == 'msgstr':
                puffer['msgstr'] += teil
    if schluessel is not None and puffer.get('msgstr'):
        eintraege[schluessel] = puffer['msgstr']
    eintraege.pop('', None)
    return eintraege


def schreiben(eintraege, pfad):
    """Schreibt eine .mo — Format Revision 0, ohne Hash-Tabelle."""
    eintraege = {k: v for k, v in eintraege.items() if k}
    sortiert = sorted(eintraege.items())
    n = len(sortiert)
    kopf = 28
    tabelle = 8
    offset_strings = kopf + 2 * n * tabelle

    orig_bytes = []
    trans_bytes = []
    orig_offsets = []
    trans_offsets = []
    pos = offset_strings
    for o, t in sortiert:
        ob = o.encode('utf-8')
        tb = t.encode('utf-8')
        orig_offsets.append((len(ob), pos))
        orig_bytes.append(ob)
        pos += len(ob) + 1
        trans_offsets.append((len(tb), pos))
        trans_bytes.append(tb)
        pos += len(tb) + 1

    with pfad.open('wb') as f:
        f.write(struct.pack('<Iiiiiii',
                            0x950412de, 0, n,
                            kopf, kopf + n * tabelle,
                            0, 0))
        for laenge, offset in orig_offsets:
            f.write(struct.pack('<ii', laenge, offset))
        for laenge, offset in trans_offsets:
            f.write(struct.pack('<ii', laenge, offset))
        for b in orig_bytes:
            f.write(b + b'\x00')
        for b in trans_bytes:
            f.write(b + b'\x00')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('po', type=pathlib.Path)
    parser.add_argument('mo', type=pathlib.Path)
    args = parser.parse_args()
    eintraege = parse(args.po)
    schreiben(eintraege, args.mo)
    print(f'{args.mo}: {len(eintraege)} Eintraege geschrieben.')


if __name__ == '__main__':
    main()
