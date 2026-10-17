# -*- coding: utf-8 -*-
"""AdbEngine ikili AndroidManifest.xml (AXML) okuyucusu testleri.

Ornek AXML belgeleri test icinde chunk yapisi kurularak insa edilir;
gercek APK, ADB cihazi veya ag kullanilmaz.
"""
import os
import struct
import sys
import types
import warnings
import zipfile

import pytest

from mibox_app.adb_engine import AdbEngine

NO_INDEX = 0xFFFFFFFF


def _patch_androguard(monkeypatch, apk_class):
    package = types.ModuleType('androguard')
    package.__path__ = []
    core = types.ModuleType('androguard.core')
    core.__path__ = []
    apk = types.ModuleType('androguard.core.apk')
    apk.APK = apk_class
    package.core = core
    core.apk = apk
    monkeypatch.setitem(sys.modules, 'androguard', package)
    monkeypatch.setitem(sys.modules, 'androguard.core', core)
    monkeypatch.setitem(sys.modules, 'androguard.core.apk', apk)


def _len8(value):
    """Android AXML uzunluk kodlamasi: 1 bayt, gerekirse 2 bayt."""
    if value < 0x80:
        return bytes([value])
    return bytes([(value >> 8) | 0x80, value & 0xFF])


def _string_pool(strings, utf8=True, style_count=0):
    flags = 0x100 if utf8 else 0
    offsets = []
    data = bytearray()
    for value in strings:
        offsets.append(len(data))
        if utf8:
            raw = value.encode('utf-8')
            data += _len8(len(value)) + _len8(len(raw)) + raw + b'\x00'
        else:
            raw = value.encode('utf-16le')
            data += struct.pack('<H', len(value)) + raw + b'\x00\x00'
    strings_start = 28 + 4 * (len(strings) + style_count)
    body = struct.pack('<IIIII', len(strings), style_count, flags,
                       strings_start, 0)
    body += b''.join(struct.pack('<I', offset) for offset in offsets)
    body += b'\x00' * (4 * style_count)
    body += bytes(data)
    return struct.pack('<HHI', 0x0001, 28, 8 + len(body)) + body


def _node(chunk_type, payload):
    size = 16 + len(payload)
    return struct.pack('<HHIII', chunk_type, 16, size, NO_INDEX, NO_INDEX) \
        + payload


def _start_element(ns, name, attrs=(), attr_start=20):
    payload = struct.pack('<II', ns, name)
    payload += struct.pack('<HHHHHH', attr_start, 20, len(attrs), 0, 0, 0)
    for blob in attrs:
        payload += blob
    return _node(0x0102, payload)


def _attr(name_idx, value_idx, raw=None, vtype=0x03, value_size=8,
          reserved=0, ns=NO_INDEX):
    raw_idx = value_idx if raw is None else raw
    blob = struct.pack('<III', ns, name_idx, raw_idx)
    blob += struct.pack('<HBB', value_size, reserved, vtype)
    blob += struct.pack('<I', value_idx)
    return blob


def _end_element(ns, name):
    return _node(0x0103, struct.pack('<II', ns, name))


def _namespace(ctype, prefix, uri):
    return _node(ctype, struct.pack('<II', prefix, uri))


def _cdata(data_idx, value_idx):
    payload = struct.pack('<I', data_idx)
    payload += struct.pack('<HBB', 8, 0, 0x03)
    payload += struct.pack('<I', value_idx)
    return _node(0x0104, payload)


def _resource_map():
    return struct.pack('<HHI', 0x0180, 8, 12) + b'\x01\x00\x00\x00'


def _document(*chunks):
    size = 8 + sum(len(chunk) for chunk in chunks)
    return struct.pack('<HHI', 0x0003, 8, size) + b''.join(chunks)


def _manual_pool(string_offsets, data, flags=0x100, style_offsets=(),
                 styles_start=0, strings_start=None, declared_count=None):
    """Ham string havuzu: sinir ve hata dallarini hedeflemek icin."""
    count = (declared_count if declared_count is not None
             else len(string_offsets))
    style_count = len(style_offsets)
    start = (28 + 4 * (count + style_count) if strings_start is None
             else strings_start)
    body = struct.pack('<IIIII', count, style_count, flags, start,
                       styles_start)
    body += b''.join(struct.pack('<I', o) for o in string_offsets)
    body += b''.join(struct.pack('<I', o) for o in style_offsets)
    body += data
    return struct.pack('<HHI', 0x0001, 28, 8 + len(body)) + body


def _utf16_entries(values):
    """UTF-16 havuz govdesi; 0x8000 ustu uzunluklari iki parcayla kodlar."""
    data = bytearray()
    offsets = []
    for value in values:
        offsets.append(len(data))
        raw = value.encode('utf-16le')
        count = len(value)
        if count >= 0x8000:
            data += struct.pack('<HH', (count >> 16) | 0x8000,
                                count & 0xFFFF)
        else:
            data += struct.pack('<H', count)
        data += raw + b'\x00\x00'
    return offsets, bytes(data)


def _valid_manifest(package='com.example.app', utf8=True, resource_map=False,
                    extra_strings=(), root_name='manifest', root_ns=NO_INDEX,
                    include_package=True):
    strings = [root_name, 'package', package]
    strings.extend(extra_strings)
    name_idx = strings.index(root_name)
    attrs = []
    if include_package:
        attrs.append(_attr(strings.index('package'), strings.index(package)))
    chunks = [_string_pool(strings, utf8=utf8)]
    if resource_map:
        chunks.append(_resource_map())
    chunks.append(_start_element(root_ns, name_idx, attrs))
    chunks.append(_end_element(root_ns, name_idx))
    return _document(*chunks)


class TestPackageFromBinaryManifest:
    def test_gecerli_manifest_paketi_dondurur(self):
        assert AdbEngine._package_from_binary_manifest(
            _valid_manifest()) == 'com.example.app'

    def test_utf16_string_pool_desteklenir(self):
        assert AdbEngine._package_from_binary_manifest(
            _valid_manifest(utf8=False)) == 'com.example.app'

    def test_kaynak_haritasi_atlanir(self):
        assert AdbEngine._package_from_binary_manifest(
            _valid_manifest(resource_map=True)) == 'com.example.app'

    def test_cok_baytli_dizeler_kod_cozulur(self):
        assert AdbEngine._package_from_binary_manifest(
            _valid_manifest(extra_strings=('Uygulama Adı',))) == \
            'com.example.app'

    def test_paket_ozniteligi_yoksa_bos_doner(self):
        assert AdbEngine._package_from_binary_manifest(
            _valid_manifest(include_package=False)) == ''

    def test_gecersiz_paket_adi_bos_doner(self):
        assert AdbEngine._package_from_binary_manifest(
            _valid_manifest(package='9kotu')) == ''

    def test_manifest_olmayan_kok_bos_doner(self):
        assert AdbEngine._package_from_binary_manifest(
            _valid_manifest(root_name='application')) == ''
        strings = ['manifest', 'uri']
        doc = _document(
            _string_pool(strings),
            _namespace(0x0100, NO_INDEX, 1),
            _start_element(1, 0),
            _end_element(1, 0),
            _namespace(0x0101, NO_INDEX, 1))
        assert AdbEngine._package_from_binary_manifest(doc) == ''

    def test_ham_ve_turlu_deger_celisirse_hata(self):
        strings = ['manifest', 'package', 'com.example.app', 'com.other.app']
        doc = _document(
            _string_pool(strings),
            _start_element(NO_INDEX, 0, [
                _attr(1, 2, raw=3)]),
            _end_element(NO_INDEX, 0))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'Conflicting' in str(exc.value)

    def test_ham_deger_yoksa_turlu_deger_kullanilir(self):
        strings = ['manifest', 'package', 'com.example.app']
        doc = _document(
            _string_pool(strings),
            _start_element(NO_INDEX, 0, [_attr(1, 2, raw=NO_INDEX)]),
            _end_element(NO_INDEX, 0))
        assert AdbEngine._package_from_binary_manifest(doc) == 'com.example.app'

    def test_boyut_siniri_asilirsa_hata(self):
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(
                b'\x00' * (8 * 1024 * 1024 + 1))
        assert 'size limit' in str(exc.value)

    def test_bozuk_sihir_reddedilir(self):
        doc = bytearray(_valid_manifest())
        doc[0:2] = struct.pack('<H', 4)
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(bytes(doc))
        assert 'Unsupported AndroidManifest.xml' in str(exc.value)

    def test_belge_sinirlari_dogrulanir(self):
        doc = bytearray(_valid_manifest())
        doc[2:4] = struct.pack('<H', 16)
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(bytes(doc))
        assert 'document bounds' in str(exc.value)

        doc2 = bytearray(_valid_manifest())
        doc2[4:8] = struct.pack('<I', len(doc2) + 4)
        with pytest.raises(ValueError) as exc2:
            AdbEngine._package_from_binary_manifest(bytes(doc2))
        assert 'document bounds' in str(exc2.value)

    def test_kesik_belge_ve_chunk(self):
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(_valid_manifest()[:6])
        assert 'Truncated binary XML document' in str(exc.value)

        # Son chunk'in basligindan sonrasi kesilirse chunk sinirlari asilir.
        full = _valid_manifest()
        doc = bytearray(full[:len(full) - 24 + 4])
        doc[4:8] = struct.pack('<I', len(doc))
        with pytest.raises(ValueError) as exc2:
            AdbEngine._package_from_binary_manifest(bytes(doc))
        assert 'Truncated binary XML chunk' in str(exc2.value)

    def test_chunk_sinirlari_dogrulanir(self):
        doc = bytearray(_valid_manifest())
        doc[12:16] = struct.pack('<I', 10 ** 6)
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(bytes(doc))
        assert 'chunk bounds' in str(exc.value)

    def test_string_pool_ilk_chunk_olmali(self):
        doc = _document(_node(0x0180, b''), _string_pool(['x']))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'must be first' in str(exc.value)

    def test_ikinci_string_pool_reddedilir(self):
        doc = _document(_string_pool(['a']), _string_pool(['b']))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'Unexpected binary XML string pool' in str(exc.value)

    def test_desteklenmeyen_chunk_reddedilir(self):
        doc = _document(_string_pool(['a']), _node(0x0002, b''))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'Unsupported binary XML chunk type' in str(exc.value)

    def test_string_pool_basligi_ve_bayraklari(self):
        doc = bytearray(_valid_manifest())
        doc[10:12] = struct.pack('<H', 24)
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(bytes(doc))
        assert 'string pool header' in str(exc.value)

        doc2 = bytearray(_valid_manifest())
        doc2[24:28] = struct.pack('<I', 0x200)
        with pytest.raises(ValueError) as exc2:
            AdbEngine._package_from_binary_manifest(bytes(doc2))
        assert 'string pool flags' in str(exc2.value)

    def test_stil_verisi_eksikse_hata(self):
        doc = _document(_string_pool(['manifest'], style_count=1))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'style data' in str(exc.value)

    def test_eslesmeyen_kapanis_reddedilir(self):
        strings = ['manifest', 'application']
        doc = _document(
            _string_pool(strings),
            _start_element(NO_INDEX, 0),
            _end_element(NO_INDEX, 1))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'Mismatched' in str(exc.value)

    def test_birden_fazla_kok_reddedilir(self):
        strings = ['manifest']
        doc = _document(
            _string_pool(strings),
            _start_element(NO_INDEX, 0),
            _end_element(NO_INDEX, 0),
            _start_element(NO_INDEX, 0),
            _end_element(NO_INDEX, 0))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'Multiple binary XML root elements' in str(exc.value)

    def test_dengesiz_namespace_reddedilir(self):
        strings = ['uri']
        doc = _document(
            _string_pool(strings),
            _namespace(0x0101, NO_INDEX, 0))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'Unbalanced' in str(exc.value)

    def test_attr_geometrisi_dogrulanir(self):
        strings = ['manifest', 'package', 'com.example.app']
        doc = _document(
            _string_pool(strings),
            _start_element(NO_INDEX, 0, [_attr(1, 2)], attr_start=19),
            _end_element(NO_INDEX, 0))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'Invalid binary XML attributes' in str(exc.value)

    def test_attr_tekrari_reddedilir(self):
        strings = ['manifest', 'package', 'com.example.app']
        doc = _document(
            _string_pool(strings),
            _start_element(NO_INDEX, 0, [_attr(1, 2), _attr(1, 2)]),
            _end_element(NO_INDEX, 0))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'duplicate binary XML attribute' in str(exc.value)

    def test_attr_deger_boyutu_dogrulanir(self):
        strings = ['manifest', 'package', 'com.example.app']
        doc = _document(
            _string_pool(strings),
            _start_element(NO_INDEX, 0, [_attr(1, 2, value_size=4)]),
            _end_element(NO_INDEX, 0))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'attribute value' in str(exc.value)

    def test_attr_string_referansi_dogrulanir(self):
        strings = ['manifest', 'package', 'com.example.app']
        doc = _document(
            _string_pool(strings),
            _start_element(NO_INDEX, 0, [_attr(99, 2)]),
            _end_element(NO_INDEX, 0))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'string reference' in str(exc.value)

    def test_cdata_kok_disinda_reddedilir(self):
        strings = ['manifest', 'metin']
        doc = _document(
            _string_pool(strings),
            _cdata(1, 1))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'text node' in str(exc.value)

    def test_eleman_derinligi_sinirlanir(self):
        strings = ['manifest']
        chunks = [_string_pool(strings)]
        chunks += [_start_element(NO_INDEX, 0)] * 260
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(_document(*chunks))
        assert 'nesting is too deep' in str(exc.value)

    def test_namespace_derinligi_sinirlanir(self):
        strings = ['uri']
        chunks = [_string_pool(strings)]
        chunks += [_namespace(0x0100, NO_INDEX, 0)] * 260
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(_document(*chunks))
        assert 'namespace nesting is too deep' in str(exc.value)


class TestBinaryManifestPoolLimits:
    """Havuz sinirlari, kod cozme hatalari ve chunk dogrulama dallari."""

    def test_string_sayisi_siniri_asilirsa_hata(self):
        doc = _document(_manual_pool([], b'', declared_count=100_001))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'entry limit' in str(exc.value)

    def test_offset_tablosu_chunk_disina_tasarsa_hata(self):
        doc = _document(_manual_pool([0, 0, 0], b'\x00', strings_start=28))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'string pool offsets' in str(exc.value)

    def test_string_verisi_havuzu_asarsa_hata(self):
        doc = _document(_manual_pool([0], b'\x00', strings_start=100))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'string data offset' in str(exc.value)

    def test_stil_verisi_konumu_dogrulanir(self):
        doc = _document(_manual_pool(
            [0], b'\x00\x00', style_offsets=[4], styles_start=40,
            strings_start=36))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'style data offset' in str(exc.value)

    def test_stil_konumu_gecersizse_hata(self):
        doc = _document(_manual_pool(
            [0], b'\x01\x01a\x00' + b'\x00' * 4, style_offsets=[4],
            styles_start=40, strings_start=36))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'style offset' in str(exc.value)

    def test_ayni_offset_yeniden_kod_cozulmez(self):
        doc = _document(_manual_pool([0, 0], b'\x01\x01a\x00'))
        assert AdbEngine._package_from_binary_manifest(doc) == ''

    def test_gecersiz_string_konumu_hata(self):
        doc = _document(_manual_pool([1000], b'\x00'))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'string offset' in str(exc.value)

    def test_dize_icinde_nul_bayti_reddedilir(self):
        doc = _document(_manual_pool([0], b'\x03\x03a\x00b\x00'))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'string content' in str(exc.value)

    def test_cdata_deger_boyutu_dogrulanir(self):
        strings = ['manifest', 'metin']
        bad = _node(0x0104, struct.pack('<I', 1)
                    + struct.pack('<HBB', 4, 0, 0x03)
                    + struct.pack('<I', 1))
        doc = _document(
            _string_pool(strings),
            _start_element(NO_INDEX, 0),
            bad,
            _end_element(NO_INDEX, 0))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'text value' in str(exc.value)

    def test_kesik_uzunluk_alani_hata(self):
        doc = _document(_manual_pool([1], b'\x00\x00'))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'Truncated binary XML value' in str(exc.value)

    def test_sonlandirilmamis_utf8_dize_hata(self):
        doc = _document(_manual_pool([0], b'\x01\x01a'))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'Unterminated' in str(exc.value)

    def test_utf8_uzunluk_uyusmazsa_hata(self):
        doc = _document(_manual_pool([0], b'\x02\x01a\x00'))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'string length' in str(exc.value)

    def test_utf16_hizasiz_dize_hata(self):
        doc = _document(_manual_pool(
            [1], b'\x00' + struct.pack('<H', 1) + b'a\x00' + b'\x00\x00',
            flags=0))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'Misaligned' in str(exc.value)

    def test_sonlandirilmamis_utf16_dize_hata(self):
        doc = _document(_manual_pool(
            [0], struct.pack('<H', 1) + b'a\x00', flags=0))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'Unterminated' in str(exc.value)

    def test_kod_cozulan_toplam_siniri(self):
        # Ortusen iki uzun UTF-16 dizesi toplami 8 MB'i asarsa hata.
        length = 3_000_000
        first = (length >> 16) | 0x8000
        second = length & 0xFFFF
        data = bytearray(b'\x01' * (10 + 2 * length))
        data[0:2] = struct.pack('<H', first)
        data[2:4] = struct.pack('<H', second)
        data[4:6] = struct.pack('<H', first)
        data[6:8] = struct.pack('<H', second)
        data[4 + 2 * length:6 + 2 * length] = b'\x00\x00'
        data[8 + 2 * length:10 + 2 * length] = b'\x00\x00'
        doc = _document(_manual_pool([0, 4], bytes(data), flags=0))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'size limit' in str(exc.value)

    def test_cok_baytli_utf8_uzunluk_desteklenir(self):
        doc = _valid_manifest(extra_strings=('x' * 200,))
        assert AdbEngine._package_from_binary_manifest(doc) == \
            'com.example.app'

    def test_cok_baytli_utf16_uzunluk_desteklenir(self):
        values = ['manifest', 'package', 'com.example.app', 'y' * 0x8000]
        offsets, data = _utf16_entries(values)
        doc = _document(
            _manual_pool(offsets, data, flags=0),
            _start_element(NO_INDEX, 0, [_attr(1, 2)]),
            _end_element(NO_INDEX, 0))
        assert AdbEngine._package_from_binary_manifest(doc) == \
            'com.example.app'

    def test_node_basligi_desteklenmez(self):
        bad = struct.pack('<HHIII', 0x0100, 8, 24, NO_INDEX, NO_INDEX) \
            + struct.pack('<II', NO_INDEX, 0)
        doc = _document(_string_pool(['uri']), bad)
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'node header' in str(exc.value)

    def test_namespace_boyutu_dogrulanir(self):
        bad = _node(0x0100, struct.pack('<II', NO_INDEX, 0) + b'\x00' * 8)
        doc = _document(_string_pool(['uri']), bad)
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'namespace chunk' in str(exc.value)

    def test_namespace_kok_kapanisindan_sonra_reddedilir(self):
        doc = _document(
            _string_pool(['manifest']),
            _start_element(NO_INDEX, 0),
            _end_element(NO_INDEX, 0),
            _namespace(0x0100, NO_INDEX, 0))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'after the root element' in str(exc.value)

    def test_beyan_edilmemis_namespace_reddedilir(self):
        strings = ['manifest', 'http://kotu.example']
        doc = _document(
            _string_pool(strings),
            _start_element(1, 0),
            _end_element(1, 0))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'Undeclared' in str(exc.value)

    def test_xml_namespace_istisnasi_kabul_edilir(self):
        strings = ['manifest', 'http://www.w3.org/XML/1998/namespace']
        doc = _document(
            _string_pool(strings),
            _start_element(1, 0),
            _end_element(1, 0))
        assert AdbEngine._package_from_binary_manifest(doc) == ''

    def test_kaynak_haritasi_gecersiz(self):
        bad = struct.pack('<HHI', 0x0180, 8, 10) + b'\x01\x00'
        doc = _document(_string_pool(['x']), bad)
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'resource map' in str(exc.value)

    def test_ikinci_kaynak_haritasi_reddedilir(self):
        doc = _document(
            _string_pool(['x']), _resource_map(), _resource_map())
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'resource map' in str(exc.value)

    def test_baslangic_elemani_kesik(self):
        bad = _node(0x0102, struct.pack('<II', NO_INDEX, 0) + b'\x00' * 8)
        doc = _document(_string_pool(['manifest']), bad)
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'start element' in str(exc.value)

    def test_paket_ozniteligi_dize_degilse_hata(self):
        strings = ['manifest', 'package']
        doc = _document(
            _string_pool(strings),
            _start_element(NO_INDEX, 0, [_attr(1, 0, vtype=0x10)]),
            _end_element(NO_INDEX, 0))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'not a string' in str(exc.value)

    def test_kapanis_elemani_kok_disi_reddedilir(self):
        doc = _document(_string_pool(['manifest']), _end_element(NO_INDEX, 0))
        with pytest.raises(ValueError) as exc:
            AdbEngine._package_from_binary_manifest(doc)
        assert 'end element' in str(exc.value)

    def test_cdata_eleman_icinde_kabul_edilir(self):
        strings = ['manifest', 'metin']
        doc = _document(
            _string_pool(strings),
            _start_element(NO_INDEX, 0),
            _cdata(1, 1),
            _end_element(NO_INDEX, 0))
        assert AdbEngine._package_from_binary_manifest(doc) == ''


class TestReadApkMetadata:
    def test_gecerli_apk_paketi_okur(self, tmp_path):
        path = tmp_path / 'uygulama.apk'
        with zipfile.ZipFile(str(path), 'w') as zf:
            zf.writestr('AndroidManifest.xml', _valid_manifest())
        info = AdbEngine.read_apk_metadata(str(path))
        assert info['package'] == 'com.example.app'
        assert info['size_bytes'] > 0

    def test_dosya_yoksa_varsayilanlar(self, tmp_path):
        info = AdbEngine.read_apk_metadata(str(tmp_path / 'yok.apk'))
        assert info == {'package': '', 'version_name': '', 'version_code': '',
                        'app_name': '', 'min_sdk': '', 'target_sdk': '',
                        'size_bytes': 0}
        assert AdbEngine.read_apk_metadata('')['package'] == ''

    def test_manifest_yoksa_paket_bos(self, tmp_path):
        path = tmp_path / 'bos.apk'
        with zipfile.ZipFile(str(path), 'w') as zf:
            zf.writestr('classes.dex', b'x')
        info = AdbEngine.read_apk_metadata(str(path))
        assert info['package'] == ''
        assert info['size_bytes'] > 0

    def test_bozuk_manifest_paket_bos(self, tmp_path):
        path = tmp_path / 'bozuk.apk'
        with zipfile.ZipFile(str(path), 'w') as zf:
            zf.writestr('AndroidManifest.xml', b'bu bir axml degil')
        info = AdbEngine.read_apk_metadata(str(path))
        assert info['package'] == ''

    def test_zip_degilse_varsayilanlar(self, tmp_path):
        path = tmp_path / 'sahte.apk'
        path.write_bytes(b'duz metin')
        info = AdbEngine.read_apk_metadata(str(path))
        assert info['package'] == ''
        assert info['size_bytes'] == len(b'duz metin')

    def test_cift_manifest_reddedilir(self, tmp_path):
        path = tmp_path / 'cift.apk'
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with zipfile.ZipFile(str(path), 'w') as zf:
                zf.writestr('AndroidManifest.xml', _valid_manifest())
                zf.writestr('AndroidManifest.xml', _valid_manifest())
        info = AdbEngine.read_apk_metadata(str(path))
        assert info['package'] == ''

    def test_boyut_okunamazsa_sifir_kalir(self, tmp_path, monkeypatch):
        path = tmp_path / 'x.apk'
        path.write_bytes(b'duz')

        def patla(p):
            raise OSError('yok')

        monkeypatch.setattr(os.path, 'getsize', patla)
        info = AdbEngine.read_apk_metadata(str(path))
        assert info['size_bytes'] == 0
        assert info['package'] == ''

    def test_manifest_paketsiz_erken_doner(self, tmp_path):
        path = tmp_path / 'paketsiz.apk'
        with zipfile.ZipFile(str(path), 'w') as zf:
            zf.writestr('AndroidManifest.xml',
                        _valid_manifest(include_package=False))
        info = AdbEngine.read_apk_metadata(str(path))
        assert info['package'] == ''
        assert info['size_bytes'] > 0
        assert info['version_name'] == ''

    def test_androguard_paketi_celiscince_temizlenir(self, tmp_path,
                                                     monkeypatch):
        path = tmp_path / 'uygulama.apk'
        with zipfile.ZipFile(str(path), 'w') as zf:
            zf.writestr('AndroidManifest.xml', _valid_manifest())

        class CelisenApk:
            def __init__(self, path):
                pass

            def get_package(self):
                return 'com.baska.app'

        _patch_androguard(monkeypatch, CelisenApk)
        info = AdbEngine.read_apk_metadata(str(path))
        assert info['package'] == ''
        assert info['version_name'] == ''

    def test_androguard_hatasi_yutulur(self, tmp_path, monkeypatch):
        path = tmp_path / 'uygulama.apk'
        with zipfile.ZipFile(str(path), 'w') as zf:
            zf.writestr('AndroidManifest.xml', _valid_manifest())

        class PatlayanApk:
            def __init__(self, path):
                raise RuntimeError('patladi')

        _patch_androguard(monkeypatch, PatlayanApk)
        info = AdbEngine.read_apk_metadata(str(path))
        assert info['package'] == 'com.example.app'
