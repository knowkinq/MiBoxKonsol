# -*- coding: utf-8 -*-
"""Kalite tarayicisi (offline, cihaz gerektirmez).

Neyi tarar:
  1) KULLANILMAYAN IMPORT: modul icinde adi hic gecmeyen import'lar
  2) AYNI DOSYADA CAKISAN TANIM: ayni isimde iki kez def/class (8.3.0'da
     `install_apk` iki kez tanimliydi ve biri digerini sessizce eziyordu)
  3) TODO/FIXME/XXX isaretleri
  4) mibox_app icinde print() (log yerine print kullanimi)

Kullanim:
    python tools/kalite_tara.py          # rapor
    python tools/kalite_tara.py --siki   # bulgu varsa cikis kodu 1
Cikis kodu: bulgu varsa 1, temizse 0 (yalnizca --siki ile).
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEDEFLER = [os.path.join(ROOT, 'mibox_app'), os.path.join(ROOT, 'tests'),
            os.path.join(ROOT, 'mibox.py')]
ISARETLER = ('TODO', 'FIXME', 'XXX', 'HACK')
_RE_ISARET = {i: re.compile(r'\b' + i + r'\b', re.I) for i in ISARETLER}
# Bu satiri iceren dosyada print() serbest sayilir (CLI/tani ciktilari icin).
PRINT_SERBEST = 'kalite_tara: print-serbest'


def _py_dosyalari(yol):
    if os.path.isfile(yol):
        if yol.endswith('.py'):
            yield yol
        return
    for kok, _dirs, dosyalar in os.walk(yol):
        if '__pycache__' in kok:
            continue
        for d in sorted(dosyalar):
            if d.endswith('.py'):
                yield os.path.join(kok, d)


def _kullanilan_adlar(tree):
    """Modulde gecen tum adlar (Name/Attribute + string icinde gecenler)."""
    adlar = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            adlar.add(node.id)
        elif isinstance(node, ast.Attribute):
            adlar.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # __all__ / getattr('ad') gibi dolayli kullanimlari kacirmamak icin
            for parca in node.value.replace('.', ' ').split():
                adlar.add(parca.strip('\'"(),:'))
    return adlar


def kullanilmayan_importlar(yol, tree, kaynak):
    """[(satir, 'import x', guven)] — guven: 'KESIN' | 'KONTROL'.

    KESIN   = ad, dosyanin HICBIR yerinde (yorum dahil) gecmiyor -> guvenle silinir.
    KONTROL = ad yalnizca yorum/docstring'de geciyor; elle bakilmali.
    """
    kullanilan = _kullanilan_adlar(tree)
    bulgular = []

    def guven(ad, bas, son):
        # ayni adi tasiyan baska bir kullanim metinde var mi?
        # import ifadesinin TUM satirlari (cok satirli import blogu) atlanir.
        import re as _re
        desen = _re.compile(r'\b' + _re.escape(ad) + r'\b')
        for i, txt in enumerate(kaynak.splitlines(), 1):
            if bas <= i <= son:
                continue
            if desen.search(txt):
                return 'KONTROL'
        return 'KESIN'

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                ad = (a.asname or a.name).split('.')[0]
                if ad not in kullanilan:
                    tanim = 'import ' + a.name + (' as ' + a.asname if a.asname else '')
                    bulgular.append((node.lineno, tanim,
                                     guven(ad, node.lineno, node.end_lineno or node.lineno)))
        elif isinstance(node, ast.ImportFrom):
            if node.module == '__future__':
                continue
            modul = '.' * (node.level or 0) + (node.module or '')
            for a in node.names:
                if a.name == '*':
                    continue
                ad = a.asname or a.name
                if ad not in kullanilan:
                    tanim = 'from {} import {}{}'.format(
                        modul, a.name, ' as ' + a.asname if a.asname else '')
                    bulgular.append((node.lineno, tanim,
                                     guven(ad, node.lineno, node.end_lineno or node.lineno)))
    return bulgular


def cakisan_tanimlar(tree):
    """Ayni isimde iki kez tanimlanan modul seviyesi def/class."""
    gorulen = {}
    cakisan = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in gorulen:
                cakisan.append((node.lineno, node.name, gorulen[node.name]))
            else:
                gorulen[node.name] = node.lineno
    return cakisan


def tara():
    rapor = {'import': [], 'cakisma': [], 'isaret': [], 'print': []}
    for hedef in HEDEFLER:
        for yol in _py_dosyalari(hedef):
            rel = os.path.relpath(yol, ROOT)
            try:
                with open(yol, 'r', encoding='utf-8') as f:
                    kaynak = f.read()
            except OSError as e:
                rapor['isaret'].append((rel, 0, 'OKUNAMADI: {}'.format(e)))
                continue
            try:
                tree = ast.parse(kaynak, rel)
            except SyntaxError as e:
                rapor['isaret'].append((rel, e.lineno or 0, 'SOZDIZIMI HATASI: {}'.format(e)))
                continue
            for satir, metin, guven_d in kullanilmayan_importlar(yol, tree, kaynak):
                rapor['import'].append((rel, satir, '[{}] {}'.format(guven_d, metin)))
            for satir, ad, ilk in cakisan_tanimlar(tree):
                rapor['cakisma'].append((rel, satir, '{} (ilk tanim satir {})'.format(ad, ilk)))
            for i, satir in enumerate(kaynak.splitlines(), 1):
                for isaret in ISARETLER:
                    # kelime siniri: 'XXXX==' gibi maskeler isaret sayilmasin
                    if _RE_ISARET[isaret].search(satir):
                        rapor['isaret'].append((rel, i, satir.strip()[:100]))
                        break
            if rel.startswith('mibox_app') and PRINT_SERBEST not in kaynak:
                for node in ast.walk(tree):
                    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                            and node.func.id == 'print'):
                        rapor['print'].append((rel, node.lineno, 'print()'))
    return rapor


def main():
    siki = '--siki' in sys.argv
    rapor = tara()
    basliklar = [('import', 'KULLANILMAYAN IMPORT'),
                 ('cakisma', 'AYNI DOSYADA CAKISAN TANIM'),
                 ('print', 'mibox_app ICINDE print()'),
                 ('isaret', 'TODO/FIXME/SOZDIZIMI')]
    toplam = 0
    for anahtar, baslik in basliklar:
        kayitlar = rapor[anahtar]
        toplam += len(kayitlar)
        print('=' * 66)
        print('{}: {}'.format(baslik, len(kayitlar)))
        print('=' * 66)
        for rel, satir, metin in kayitlar:
            print('  {}:{}  {}'.format(rel, satir, metin))
        if not kayitlar:
            print('  (temiz)')
        print()
    print('TOPLAM BULGU: {}'.format(toplam))
    if siki and toplam:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
