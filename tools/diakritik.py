# -*- coding: utf-8 -*-
"""TR diakritik duzeltme araci (guvenli, token seviyesinde).

Neden boyle: kor metin degistirme (sed benzeri) VERI sabitlerini de bozar.
Bu arac:
  1) Yalnizca STRING sabitleri icinde calisir (tokenize ile) — kod/identifier
     degismez.
  2) Karsilastirma iceren satirlari ATLAR ve 'KONTROL' olarak listeler
     (`==`, `!=`, `.text()`, `startswith`, `findText`, `itemData` ...).
     Cunku bir etiketle karsilastirma yapiliyorsa iki taraf birlikte
     degismelidir; bu elle yapilir.
  3) KORUNAN sabitler (motorun urettigi VERI degerleri) hic degismez:
     'Kisitli', 'Serbest', 'Evet', 'Hayir', ... (ekranda gosterilecekse
     arayuz DISPLAY_* eslemesiyle cevirir).

Kullanim:
    python tools/diakritik.py            # kuru calistirma (rapor)
    python tools/diakritik.py --uygula   # degisiklikleri yaz
"""
import io
import os
import re
import sys
import tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEDEFLER = [os.path.join(ROOT, 'mibox_app')]

# --- Korunan VERI sabitleri: bunlara dokunulmaz ---------------------------
KORUNAN = {
    'Kisitli', 'Serbest', 'Evet', 'Hayir', '?', '-',
    # Aktif sutununda YAZILAN ve _context_menu'de KARSILASTIRILAN sabit:
    # cevrilirse iki taraf ayrisir (elle DISPLAY eslemesi ile cozulur).
    'Kaldirilmis', 'kaldirilmis',
    'all', 'restricted', 'free', 'disabled', 'removed', 'running', 'system',
    'READ', 'SETTING', 'CHANGE', 'REFUSED',
    'guvenli', 'opsiyonel', 'riskli', 'dokunma',
}

# --- Kelime bazli ceviri tablosu (tam kelime eslesmesi) -------------------
CEVIRI = {
    # baglanti / ana pencere
    'Baglan': 'Bağlan', 'Baglanti': 'Bağlantı', 'Bagli': 'Bağlı',
    'bagli': 'bağlı', 'Baglantida': 'Bağlantıda', 'baglantisi': 'bağlantısı',
    'Gecmis': 'Geçmiş', 'gecmis': 'geçmiş', 'Gecmisi': 'Geçmişi',
    'Cihaz': 'Cihaz', 'Seciliyi': 'Seçiliyi',
    # filtre / liste
    'Kisitla': 'Kısıtla', 'kisitla': 'kısıtla', 'Kisitli': 'Kısıtlı',
    'kisitli': 'kısıtlı', 'kisitlaniyor': 'kısıtlanıyor',
    'Kaldir': 'Kaldır', 'kaldir': 'kaldır', 'Kaldirilmis': 'Kaldırılmış',
    'kaldirilmis': 'kaldırılmış', 'Kaldirilabilir': 'Kaldırılabilir',
    'kaldirilabilir': 'kaldırılabilir', 'Kaldirinca': 'Kaldırınca',
    'Yukle': 'Yükle', 'yukle': 'yükle', 'Yukleme': 'Yükleme',
    'Yukleniyor': 'Yükleniyor', 'Yuklendi': 'Yüklendi',
    'disi': 'dışı', 'Disi': 'Dışı',
    'Sec': 'Seç', 'sec': 'seç', 'Secili': 'Seçili', 'secili': 'seçili',
    'Secimi': 'Seçimi', 'Secim': 'Seçim', 'secim': 'seçim',
    'Secenek': 'Seçenek', 'Secenekler': 'Seçenekler', 'Secildi': 'Seçildi',
    'Secme': 'Seçme', 'secme': 'seçme',
    'Tumu': 'Tümü', 'tumu': 'tümü', 'Tumunu': 'Tümünü', 'Tumunde': 'Tümünde',
    'Calisan': 'Çalışan', 'Calisiyor': 'Çalışıyor', 'calisiyor': 'çalışıyor',
    'calisan': 'çalışan', 'Calistir': 'Çalıştır', 'calistir': 'çalıştır',
    'Calistirilamadi': 'Çalıştırılamadı', 'Calisma': 'Çalışma',
    'Guvenli': 'Güvenli', 'guvenli': 'güvenli', 'Guvenlik': 'Güvenlik',
    'guvenlik': 'güvenlik',
    'Onbellek': 'Önbellek', 'onbellek': 'önbellek', 'Onbellegi': 'Önbelleği',
    'onbellegi': 'önbelleği',
    'Uygulamalari': 'Uygulamaları', 'uygulamalari': 'uygulamaları',
    'Ayarlari': 'Ayarları', 'ayarlari': 'ayarları',
    'Islem': 'İşlem', 'islem': 'işlem', 'Islemler': 'İşlemler',
    'Islemi': 'İşlemi', 'islemleri': 'işlemleri',
    'Goster': 'Göster', 'goster': 'göster', 'Gosterilen': 'Gösterilen',
    'Gosterim': 'Gösterim', 'Gosteriliyor': 'Gösteriliyor',
    'Kullanici': 'Kullanıcı', 'kullanici': 'kullanıcı',
    'Kullanicilar': 'Kullanıcılar', 'Kullanicisi': 'Kullanıcısı',
    'Uyari': 'Uyarı', 'uyari': 'uyarı', 'Uyarisi': 'Uyarısı',
    'Saglik': 'Sağlık', 'saglik': 'sağlık',
    'Kayit': 'Kayıt', 'kayit': 'kayıt', 'Kayitli': 'Kayıtlı',
    'Baslat': 'Başlat', 'baslat': 'başlat', 'Basladi': 'Başladı',
    'basladi': 'başladı', 'Baslatildi': 'Başlatıldı', 'baslatildi': 'başlatıldı',
    'Basarisiz': 'Başarısız', 'basarisiz': 'başarısız',
    'Basarili': 'Başarılı', 'basarili': 'başarılı', 'Basarisiyla': 'Başarısıyla',
    'Izin': 'İzin', 'izin': 'izin', 'Izinler': 'İzinler', 'Izinleri': 'İzinleri',
    'Ipuclu': 'İpucu', 'Ipuclari': 'İpuçları', 'ipucu': 'ipucu',
    'Klasor': 'Klasör', 'klasor': 'klasör', 'Klasoru': 'Klasörü',
    'Klasore': 'Klasöre', 'Klasorden': 'Klasörden',
    'Degis': 'Değiş', 'degis': 'değiş', 'Degistir': 'Değiştir',
    'degistir': 'değiştir', 'Degisiklik': 'Değişiklik', 'degisiklik': 'değişiklik',
    'Guncel': 'Güncel', 'Guncelle': 'Güncelle', 'guncelle': 'güncelle',
    'Guncelleme': 'Güncelleme', 'guncelleme': 'güncelleme',
    'Hizli': 'Hızlı', 'hizli': 'hızlı', 'Hizlandir': 'Hızlandır',
    'Kalici': 'Kalıcı', 'kalici': 'kalıcı',
    'Kucuk': 'Küçük', 'kucuk': 'küçük', 'Kucult': 'Küçült',
    'Onemli': 'Önemli', 'onemli': 'önemli',
    'Ozellik': 'Özellik', 'ozellik': 'özellik', 'Ozel': 'Özel', 'ozel': 'özel',
    'Ozet': 'Özet', 'ozet': 'özet',
    'Onizle': 'Önizle', 'Onizleme': 'Önizleme', 'onizleme': 'önizleme',
    'Sifir': 'Sıfır', 'sifir': 'sıfır', 'Sifirla': 'Sıfırla',
    'Surum': 'Sürüm', 'surum': 'sürüm', 'Surumu': 'Sürümü',
    'Sutun': 'Sütun', 'sutun': 'sütun', 'Sutunlar': 'Sütunlar',
    'Yontem': 'Yöntem', 'yontem': 'yöntem',
    'Yukarida': 'Yukarıda', 'Yuksek': 'Yüksek',
    'asimi': 'aşımı', 'Asimi': 'Aşımı',
    'Adim': 'Adım', 'adim': 'adım', 'Adimda': 'Adımda',
    'Ayrinti': 'Ayrıntı', 'ayrinti': 'ayrıntı', 'Ayrintili': 'Ayrıntılı',
    'Gecersiz': 'Geçersiz', 'gecersiz': 'geçersiz',
    'Gecerli': 'Geçerli', 'gecerli': 'geçerli',
    'Menu': 'Menü', 'menu': 'menü', 'Menude': 'Menüde',
    'Okunamadi': 'Okunamadı', 'okunamadi': 'okunamadı',
    'Olustur': 'Oluştur', 'olustur': 'oluştur', 'Olusturuldu': 'Oluşturuldu',
    'olusturuldu': 'oluşturuldu',
    'Sira': 'Sıra', 'Sirala': 'Sırala', 'sirala': 'sırala',
    'Sure': 'Süre', 'sure': 'süre', 'Sureli': 'Süreli', 'suresi': 'süresi',
    'Yavas': 'Yavaş', 'yavas': 'yavaş',
    'Acik': 'Açık', 'acik': 'açık', 'Aciklama': 'Açıklama',
    'aciklama': 'açıklama', 'Aciklamasi': 'Açıklaması',
    'Ayikla': 'Ayıkla', 'ayikla': 'ayıkla',
    'Dogrula': 'Doğrula', 'dogrula': 'doğrula', 'Dogrulama': 'Doğrulama',
    'dogrulama': 'doğrulama', 'Dogrulandi': 'Doğrulandı',
    'Kullanilir': 'Kullanılır', 'kullanilir': 'kullanılır',
    'Kullaniliyor': 'Kullanılıyor', 'Kullanilamiyor': 'Kullanılamıyor',
    'Yapilir': 'Yapılır', 'yapilir': 'yapılır', 'Yapiliyor': 'Yapılıyor',
    'Yapilamadi': 'Yapılamadı', 'Acilir': 'Açılır', 'Alinir': 'Alınır',
    'Bulunamadi': 'Bulunamadı', 'bulunamadi': 'bulunamadı',
    'Duzenle': 'Düzenle', 'duzenle': 'düzenle',
    'Eslesme': 'Eşleşme', 'Eslestirme': 'Eşleştirme',
    'eslestirme': 'eşleştirme', 'Eslestir': 'Eşleştir',
    'Farkli': 'Farklı', 'farkli': 'farklı',
    'Hazir': 'Hazır', 'hazir': 'hazır',
    'Ilk': 'İlk', 'ilk': 'ilk', 'Ileri': 'İleri', 'Iceri': 'İçeri',
    'Iptal': 'İptal', 'iptal': 'iptal', 'Izle': 'İzle',
    'Kullanildi': 'Kullanıldı', 'kullanildi': 'kullanıldı',
    'Tamamlandi': 'Tamamlandı',
    'Yok': 'Yok', 'Yoksa': 'Yoksa', 'yoksa': 'yoksa',
    'Adet': 'Adet', 'Aralik': 'Aralık', 'aralik': 'aralık',
    'Cevir': 'Çevir', 'cevir': 'çevir',
    'Onay': 'Onay', 'Onayla': 'Onayla',
    'Ileri': 'İleri', 'Geri': 'Geri',
    'Islem': 'İşlem', 'Islevi': 'İşlevi',
    'Uzerinde': 'Üzerinde', 'uzerinde': 'üzerinde',
    'Uzerine': 'Üzerine', 'Uzerinden': 'Üzerinden',
    'Cok': 'Çok', 'cok': 'çok',
    'Cihazin': 'Cihazın', 'cihazin': 'cihazın',
    'Kilitli': 'Kilitli', 'Kilit': 'Kilit',
    'Icin': 'İçin', 'icin': 'için',
    'Icinde': 'İçinde', 'icinde': 'içinde',
    'Ihtiyac': 'İhtiyaç', 'ihtiyac': 'ihtiyaç',
    'Istege': 'İsteğe', 'istege': 'isteğe',
    'Icerik': 'İçerik', 'icerik': 'içerik',
    'Izinli': 'İzinli', 'Onbellekten': 'Önbellekten',
    'Kopyasi': 'Kopyası', 'kopyasi': 'kopyası',
    'Yuzde': 'Yüzde', 'yuzde': 'yüzde',
    'Kalani': 'Kalanı',
    'Bos': 'Boş', 'bos': 'boş',
    'Ac': 'Aç',
    # ikinci dalga: uzun kuyruk (elle bulunan kalanlar)
    'Once': 'Önce', 'once': 'önce', 'Onceki': 'Önceki', 'onceki': 'önceki',
    'Ayni': 'Aynı', 'ayni': 'aynı', 'Ayri': 'Ayrı', 'ayri': 'ayrı',
    'Yapilandirma': 'Yapılandırma', 'Operator': 'Operatör',
    'uyarilari': 'uyarıları', 'uyarisi': 'uyarısı', 'uyarilar': 'uyarılar',
    'Kaldirma': 'Kaldırma', 'kaldirma': 'kaldırma',
    'Birak': 'Bırak', 'birak': 'bırak',
    'dondurulebilir': 'döndürülebilir', 'dondur': 'döndür',
    'baslayin': 'başlayın', 'Baslayin': 'Başlayın',
    'sag': 'sağ', 'Sag': 'Sağ', 'tik': 'tık', 'Tik': 'Tık',
    'Yaklasik': 'Yaklaşık', 'yaklasik': 'yaklaşık',
    'Istatistik': 'İstatistik', 'Bagimsiz': 'Bağımsız',
    'Aktarildi': 'Aktarıldı', 'aktarildi': 'aktarıldı',
    'Yuklenemedi': 'Yüklenemedi', 'Kullanilan': 'Kullanılan',
    'Yazilamadi': 'Yazılamadı', 'Dosyasi': 'Dosyası', 'dosyasi': 'dosyası',
    'Kaldirilamadi': 'Kaldırılamadı', 'Kurulamadi': 'Kurulamadı',
    'Acildi': 'Açıldı', 'Kapatildi': 'Kapatıldı', 'Kapat': 'Kapat',
    'Degistirilemedi': 'Değiştirilemedi', 'Uygulanamadi': 'Uygulanamadı',
    'Uygulandi': 'Uygulandı', 'Baslatilamadi': 'Başlatılamadı',
    'Hatali': 'Hatalı', 'hatali': 'hatalı', 'Yalnizca': 'Yalnızca',
    'yalnizca': 'yalnızca', 'Onerilen': 'Önerilen', 'onerilen': 'önerilen',
    'Oneri': 'Öneri', 'Cihazlari': 'Cihazları', 'cihazlari': 'cihazları',
    'Uygulamayi': 'Uygulamayı', 'uygulamayi': 'uygulamayı',
    'Secmek': 'Seçmek', 'secmek': 'seçmek', 'Secin': 'Seçin', 'secin': 'seçin',
    'Secilmedi': 'Seçilmedi', 'Secilmemis': 'Seçilmemiş',
    'Isaretle': 'İşaretle', 'isaretle': 'işaretle', 'Isaretli': 'İşaretli',
    'Toplamda': 'Toplamda', 'Kullanimi': 'Kullanımı', 'kullanimi': 'kullanımı',
    'Aciklamasi': 'Açıklaması', 'aciklamasi': 'açıklaması',
    'Siralama': 'Sıralama', 'siralama': 'sıralama',
    'Kisayol': 'Kısayol', 'kisayol': 'kısayol',
    'Kisayollari': 'Kısayolları',
    # ucuncu dalga: diff denetiminde gorulen kalanlar
    'Sozluk': 'Sözlük', 'sozluk': 'sözlük',
    'atlandi': 'atlandı', 'Atlandi': 'Atlandı',
    'birakildi': 'bırakıldı', 'Birakildi': 'Bırakıldı',
    'kaldirildi': 'kaldırıldı', 'Kaldirildi': 'Kaldırıldı',
    'gecici': 'geçici', 'Gecici': 'Geçici',
    'atlanan': 'atlanan', 'durduruldu': 'durduruldu',
    'saglandi': 'sağlandı', 'Saglandi': 'Sağlandı',
    'tamamlanamadi': 'tamamlanamadı', 'Tamamlanamadi': 'Tamamlanamadı',
    'kullanilamaz': 'kullanılamaz', 'yapilandirilamadi': 'yapılandırılamadı',
    'okunamayan': 'okunamayan',
}

# Ceviri uygulanmayacak satir kaliplari: KARSILASTIRMA / eslesme arama.
# (.setText gibi saf GORUNTULEME cagrilari burada DEGIL — onlar cevrilmeli.)
KARSILASTIRMA = re.compile(
    r'==|!=|\.text\(\)|startswith|endswith|findText|findData|'
    r'itemData|currentData|currentText|\bassert\b|'
    r'\.startswith|\.endswith|\bin\s+[A-Za-z_]|not in')

KELIME_RE = {k: re.compile(r'\b' + re.escape(k) + r'\b') for k in CEVIRI}

# Regex/desen cagrilari: metni cevirmek davranisi bozabilir, atlanir.
RE_CAGRI = re.compile(r'\bre\.(compile|search|match|fullmatch|findall|finditer|'
                      r'sub|split|escape)\b')


def _hedef_dosyalar():
    for hedef in HEDEFLER:
        for kok, dirs, dosyalar in os.walk(hedef):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for ad in sorted(dosyalar):
                if ad.endswith('.py'):
                    yield os.path.join(kok, ad)


def _satir_no(kaynak, konum):
    return kaynak[:konum].count('\n') + 1


def _cevir_metin(metin):
    """Bir string sabitinin ICERIGINI kelime kelime cevirir."""
    if metin in KORUNAN:
        return metin
    yeni = metin
    for eski, yeni_kelime in CEVIRI.items():
        if eski in yeni:
            yeni = KELIME_RE[eski].sub(yeni_kelime, yeni)
    return yeni


STIRING_BAS = re.compile(r'^([A-Za-z]*)("""|\'\'\'|"|\')')


def isle(yol, uygula):
    """(degisiklik_sayisi, kontroller) dondurur."""
    with open(yol, 'r', encoding='utf-8') as f:
        kaynak = f.read()
    satirlar = kaynak.splitlines(keepends=True)
    kontroller = []
    degisim = 0
    parcalar = []
    son = 0
    with io.StringIO(kaynak) as akis:
        try:
            tokenlar = list(tokenize.generate_tokens(akis.readline))
        except (tokenize.TokenError, IndentationError) as e:
            return 0, [(os.path.relpath(yol, ROOT), 0, 'SOZDIZIMI: ' + str(e))]
    for tok in tokenlar:
        if tok.type != tokenize.STRING:
            continue
        ham = tok.string
        esle = STIRING_BAS.match(ham)
        if not esle:
            continue
        onek, tirnak = esle.group(1), esle.group(2)
        if len(tirnak) == 3:
            # docstring / blok metin: cevrilmez (diff gurultusu olmasin)
            continue
        if 'f' in onek.lower():
            # f-string: govde tek parca metin degil -> elle bakilir
            continue
        if 'r' in onek.lower():
            # raw string: neredeyse her zaman regex/yol -> DOKUNMA
            continue
        govde = ham[len(onek) + 1:-1]
        yeni_govde = _cevir_metin(govde)
        if yeni_govde == govde:
            continue
        no = tok.start[0]
        satir = satirlar[no - 1] if 0 < no <= len(satirlar) else ''
        if RE_CAGRI.search(satir):
            # regex/desen satiri: metni degistirmek davranisi bozabilir
            continue
        if KARSILASTIRMA.search(satir):
            kontroller.append((os.path.relpath(yol, ROOT), no, satir.strip()[:110]))
            continue
        ofset = sum(len(s) for s in satirlar[:no - 1]) + tok.start[1]
        parcalar.append(kaynak[son:ofset])
        parcalar.append(onek + tirnak + yeni_govde + tirnak)
        son = ofset + len(ham)
        degisim += 1
    if not degisim:
        return 0, kontroller
    parcalar.append(kaynak[son:])
    if uygula:
        with open(yol, 'w', encoding='utf-8', newline='') as f:
            f.write(''.join(parcalar))
    return degisim, kontroller


def main():
    # Konsol kodlamasi (cp1254 vb.) bazi karakterleri basamiyor: bozmadan yaz.
    try:
        sys.stdout.reconfigure(errors='replace')
    except (AttributeError, ValueError):
        pass
    uygula = '--uygula' in sys.argv
    toplam = 0
    tum_kontroller = []
    print('MOD:', 'UYGULA' if uygula else 'KURU CALISTIRMA')
    print('=' * 66)
    for yol in _hedef_dosyalar():
        degisim, kontroller = isle(yol, uygula)
        if degisim:
            print('{:>4} degisiklik  {}'.format(degisim, os.path.relpath(yol, ROOT)))
            toplam += degisim
        tum_kontroller.extend(kontroller)
    print('=' * 66)
    print('TOPLAM STRING DEGISIKLIGI: {}'.format(toplam))
    print('ELLE BAKILACAK (karsilastirma iceren satirlar): {}'.format(len(tum_kontroller)))
    for yol, no, satir in tum_kontroller:
        print('  {}:{}  {}'.format(yol, no, satir))
    return 0


if __name__ == '__main__':
    sys.exit(main())
