# MiBox Konsol (Python + PySide6)

Mi Box (MiTV-AFKR0 / Android 14) icin profesyonel GUI yonetim araci.
ADB uzerinden uygulama yonetimi, arka plan kisitlamasi, ADB kumandasi,
kategorili debloat, ag tarayici ve kalici ayarlar.

Surum: v8.5.0

Degisiklik gecmisi: [CHANGELOG.md](CHANGELOG.md)

## Kurulum

```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

ADB gerektirir. Program otomatik bulur (once exe yani, sonra PATH).
Bulunamazsa uyari gosterir; ADB sonradan kurulursa tekrar dener.

### Paketlenmis kurulum (masaustu kisayollu)

```bat
build_exe_onedir.bat   :: onedir paketi uretir (gecici klasor ACMAZ)
kur_onedir.bat         :: %LOCALAPPDATA%\MiBoxKonsol icine kurar + kisayol
```

`kur_onedir.bat` sunlari yapar:
- paketi `%LOCALAPPDATA%\MiBoxKonsol` icine kopyalar (**kullanici verisi
  korunur**: ayar, log, gecmis, snapshot, favori dosyalari uzerine yazilmaz),
- `adb.exe` bulunursa paket yanina kopyalar,
- **Masaustu** ve **Baslat menusu** kisayolu olusturur,
- `kaldir.bat` birakir: kisayollari siler; veriyi de silmek icin `kaldir.bat /veri`,
- kurulum sonunda `--version` + `--selftest` ile **kendini dogrular**
  (temiz kurulumda olusan ayar/log/isaretci dosyalari geri temizlenir).

## Calistirma

```bat
python mibox.py
python -m mibox_app.main
```

Selftest (pencereyi offscreen kurar, cikar):

```bat
set QT_QPA_PLATFORM=offscreen
python mibox.py --selftest
```

## Test (gercek cihaz — sahte veri YOK)

Bu projede sahte/mock/uydurma veri KULLANILMAZ. Tum testler gercek TV'ye
karsi calisir; TV kapaliysa test `DEVICE_FAIL` ile cikar, asla sahte
basari uretilmez.

```bat
python tests/device_test.py            :: tam motor testi (15 kontrol)
python tests/device_test.py 192.0.2.1:5555   :: ozel hedef
python tests/device_scan.py            :: canli tarama + UI akisi
python tests/device_probe.py           :: appops/deviceidle kesfi
```

15 kontrol: baglanti, cihaz bilgisi, detayli liste (147 paket),
APK yol ayristirma, onbellek (soguk/sicak), user0, calisan tespiti,
saglik, snapshot al/fark-yok/sil, bulk-restricted, restrict→dogrula→
unrestrict dongusu (guvenli paket), screenshot PNG, logcat, dosya listesi,
otomatik baslayanlar. Hepsi gecerse `DEVICE_OK` yazar. Her ADB cagrisi
sureli satir olarak ekrana duser (komut izi).

v7.0.0 (elden geçirme):
- **Worker mimarisi**: 11 worker tek `BaseWorker` tabanında; sinyal/hata
  standardı tek noktada (`finished_ok` tek dict, `failed` standart metin).
  `QThread` import'u yalnızca tabanda. ~150 satır tekrar silindi.
- **Tarama hızı**: paket listesi 60 sn önbelleği (`list_packages_detailed`
  `use_cache`); yazma sonrası otomatik geçersizleme. Snapshot/diff her
  zaman gerçeği okur (`use_cache=False`).
- **`bulk_restricted` düzeltmesi**: `RUN_IN_BACKGROUND` + `RUN_ANY_IN_
   BACKGROUND` birleşimi (restrict ikisini de yazıyordu, okuma tekti);
   `No operations.` gibi bilgi satırları filtrelenir.
 - **İzin hatası düzeltmesi**: `granted` yanlış gruba bakıyordu
   (hep False); cihaz testi yakaladı, düzeltildi.

 v8.0.0 (GitHub rakip arastirmasi: ADB AppControl, tvboxtools, TV toolkit):
 - **Kurulum sekmesi**: APK toplu kurma (tek + split `install-multiple`,
   AppControl 'install APKS' esdegeri), kurulum oncesi otomatik snapshot.
 - **HOME Launcher**: kalici HOME ayari (`cmd package set-home-activity`,
   reboot dayanir — tvboxtools yontemi), launcher tarama, mevcut HOME
   gosterme. Stok launcher silinmez, tek tikla geri donulur.
 - **Hizlandirma**: animasyon olcekleri (0/0.5/1) okuma + dogrulamali yazma
   (tvboxtools 'speed up').
 - **Komut Konsolu**: serbest ADB girisi ama **kapili** (tvboxtools
   'command gate'): READ dogrudan, SETTING goster, CHANGE onay sorar,
   wipe/factory/su/bootloader/adb-kapatma **REDDEDILIR**.
 - Test: 40 → 52 (APK kurulum, HOME, animasyon, 6 kapi sinifi).

 v8.1.0 (log devrimi — "Yenile loga dusmuyor" sikayeti):
 - **ADB komut izi**: calistirilan HER ADB komutu Canli Log'a duser
   (`adb shell pm list packages -f -a  412ms`, hata ise `HATA:` ile).
   Yeni **ADB** seviyesi + filtre kutusu (kapatilabilir). `pair` kodu ve
   host maskelenir (`******`), gunluk dosyasina da yazilir.
 - **Is baslangic/bitis**: her worker `▶ Istek: ...` / `▶ ... basladi` /
   `✔ ... bitti (N sn)` / `✘ ... basarisiz` satirlari uretir. Yenile,
   tarama, kurulum, snapshot dahil hicbir is sessiz kalmaz.
 - **Acik niyet loglari**: `_run(desc=...)` ile 60+ istek noktasina
   insan-dili aciklama (örn: `▶ Istek: Saglik Yenile: depolama/RAM/paket
   olculuyor`). Canli logcat yoklamasi kirlilik olmasin diye haric.
 - Test: 52 → 55 (iz cagrisi, pair maskeleme, sure tipi).

  v8.2.0 (log gurultu + tik-crash duzeltmeleri):
  - **pidof sessizligi**: `pidof` negatif sonucu (uygulama calismiyor)
    artik ERROR degil; ne logda kirmizi satir, ne gürültü uretir. Yeni
    **Ayrinti** tiki (varsayilan kapali) acilirsa gri VERBOSE satirlar
    gorunur. Tarama sirasinda 100+ `HATA: exit!=0` satiri biter.
  - **Tik-crash kilitleri**: Tumunu Sec sinyalleri bastirir (147 satirlik
    itemChanged firtinasi biter); Yenile/Islem butonlari mesgulken kilitli
    (cift worker yarisi biter); kapanista worker bekleme + iz kesme.
  - **Filtre kaybi duzeltmesi**: tik ac/kapa sonrasi kayitlar geri geliyor
    (rebuild snapshot'tan cizer); flush yalnizca yeni kayitlari tek
    appendHtml ile basar (tik degisimi 0.2 sn).

  v8.3.0 (elden gecirme — duplicate API, eksik push, guvenlik/kalite):
  - **Duplicate `install_apk` silindi**: motorda ayni metod iki kez tanimliydi
    (ikincisi birinciyi sessizce eziyordu). Tek tanim kaldi
    (`reinstall` parametreli). `install_apks` -> `install_multiple(liste)`
    olarak birlesti (eski ad deprecated alias, calismaya devam eder).
  - **Eksik `push` eklendi**: Dosyalar sekmesi `engine.push` cagiriyordu ama
    metod motorda YOKTU (dosya yukleme calisma zamaninda patlardi). Artik
    hata-dogrulamali `push`/`pull` var.
  - **Hizli kok butonlari geri geldi**: `files_tab` icinde `if False` ile
    olen kod yuzunden kok kisayollari (sdcard/Download/Movies/DCIM) hic
    cizilmiyordu; ayri satira tasindi.
  - **Guvenlik kapisi sikilastirildi**: `rm -rf /system|/vendor|/data|/sdcard`
    varyantlari bosluk/flag farkina bakmaksizin REDDEDILIR.
  - **Atomik ayar yazma**: `Config.save` once `.tmp` yazar, `os.replace` ile
    degistirir (elektrik kesintisinde yari JSON kalmaz).
  - **Snapshot sema dogrulama**: bozuk/eksik alanli snapshot yuklenirken
    erken REDDEDILIR (sonradan `KeyError` ile patlamak yerine).
  - **Ayar yedegi tam kapsama**: disari aktarma artik 13 alanin TAMAMINI
    yazar (eskiden 7 alan kayboluyordu); ice aktarmada tip-dogrulamali.
  - **Hack temizligi**: `health_tab` icindeki `__import__` hack'i normal
    import oldu; `history_tab` cift FlowLayout import'u teke indi.
  - **Test duzeltmesi**: `device_scan` 7 sutun bekler (Aktif sutunu vardi
    ama test 6 sayiyordu); probe/scan hedefi argv ile verilebilir.

  v8.4.0 (kalite + guvenlik fazi; ayrinti CHANGELOG.md):
  - Komut kapisi sertlestirildi; paket/yol/logcat/animasyon/HOME/kullanici
    dogrulamalari motorda zorunlu. Gunluk log dosyasi + logcat dedup.

  v8.5.0 (HOME kilidi duzeltmesi + filtre sadeleştirmesi):
  - **Google TV HOME kilidi cozuldu**: `cmd package set-home-activity`
    hatasiz donse bile cihaz "kurulmamis" sayildigi icin HOME
    `com.google.android.tungsten.setupwraith` uzerinde kaliyordu
    ("Dogrulama basarisiz: HOME hala ..."). Artik engel otomatik cozulur:
    `device_provisioned` + `user_setup_complete` = 1 yazilir, HOME'u tutan
    sihirbaz paketi user 0 icin devre disi birakilir (veri SILINMEZ),
    HOME yeniden ayarlanip DOGRULANIR; ek adimlar arayuzde raporlanir.
  - **Uygulamalar filtreleri tek listede**: ayri `Calisan / Kaldirilmis /
    Sistem` kutulari kaldirildi; hepsi "Tumu" acilir listesinin icinde
    (Tumu, Kisitli, Serbest, Devre disi, Kaldirilmis, Calisan, Sistem).
    Arama + Tumu + Debloat + CSV tek satirda, Yenile alt satirda.
  - Debloat DB + "Uretici Artiklari" profiline
    `com.google.android.tungsten.setupwraith` eklendi.
  - Test: 89 -> 106 guvenlik iddiasi (sihirbaz tanima + kapatma guvenligi).
  - `.gitignore` eklendi (build/dist/log/ayar dosyalari artik depo disi).

Not: `tests/fake_adb.py` (sahte ADB) ve `archive/_smoke.py` (sanal
veri) KALDIRILDI — bu projede uydurma veri yoktur. Tum dogrulama
gercek TV uzerinde `tests/device_test.py` ile yapilir.

## Sekmeler

1. **Uygulamalar** - Tum kurulu uygulamalari listeler. Arama (250 ms
   debounce), tek "Tumu" acilir listesinde filtre (Tumu / Kisitli / Serbest /
   Devre disi / Kaldirilmis / Calisan / Sistem) + Debloat filtresi,
   basliga tiklayarak siralama, coklu secim, kisitla/serbest birak,
   force stop, veri silme, devre disi/aktif etme, kaldirma/geri yukleme,
   split APK dahil APK yedekleme, CSV aktarim, cift tiklama ile detay
   (surum, kurucu, boyut, yol), sag tik menu, otomatik yenileme (N dk).
2. **Kumanda** - ADB keyevent tabanli uzaktan kumanda: Guc, Uyku/Uyan,
   Ses +/-, Sessiz, Oynat/Duraklat, Durdur, Onceki/Sonraki, Geri/Hizli Sar,
   Kayit, D-Pad (Yukari/Asagi/Sol/Sag/OK + ayri D-Pad paneli), Geri,
   Ana Ekran, Menu, Uygulamalar, Ayarlar. Uygulama acma (resolve-activity
   + paket yazma destekli), metin gonderme (Turkce transliterasyonlu),
   genis cihaz bilgisi (RAM, ekran, depolama, pil, Wi-Fi, uptime),
   onizlemeli ekran goruntusu (HD secenegi), yeniden baslatma
   (Sistem/Recovery/Bootloader), onbellek temizleme, APK ve split APK kurma.
3. **Debloat** - Kategorili bloatware veritabani (Guvenli/ Opsiyonel/
   Riskli/ Dokunma/ Favoriler, ~140 kayit: UAD + TV/Xiaomi listeleri).
   Cihazda varlik taramasi, arama filtresi, Durum sutunu
   (Kurulu/Devre disi/Kaldirilmis), riskli kategoride uninstall yerine
   otomatik Akilli Kaldir (disable-oncelikli, UAD politikasi),
   toplu kaldirma/devre disi/geri yukleme, favori ekleme/cikarma (kalici),
   CSV aktarim. **Hazir profiller**: Minimal, Google Diyeti, Gizlilik
   Kalkani, Yayinci Temizligi, Uretici Artıkları — tek tikla uygula,
   yasakli kategori otomatik reddedilir. Her toplu islem oncesi
   **otomatik guvenlik snapshot** alinir.
4. **Saglik** - Depolama/RAM doluluk cubuklari, paket sayilari, tek tikla
   Guvenli Temizlik (yalnizca Guvenli + korumasiz + calismayan paketlerin
   verisi; paket silinmez), trim-caches. **Depolama Avcisi** (Top-15
   klasor), **Uygulama Izinleri** (riskli izin uyarili).
5. **Gecmis** - Kalici islem kaydi (JSONL): ne, ne zaman, hangi yontemle.
   Secili satirlari tek tikla geri al. Snapshot: durumu kaydet, OTA
   sonrasi Farklari Goster/Uygula (UAD-NG yaklasimi).
6. **Logcat** - Canli sistem gunlugu (seviye/etiket filtreli, 3 sn yoklama),
   Cokme Avcisi (FATAL/AndroidRuntime), cihaz tamponu temizleme, kaydetme.
7. **Dosyalar** - sdcard gozat (cift tikla klasore gir), push/pull,
   klasor ac, sil. Hizli kokler + yol cubugu.
8. **Ag** - LAN'da ADB portu acik cihazlari tarar (32 thread, ozel aralik,
   ilerleme cubugu, durdurma). Cift tiklama veya dugme ile hedef yapar.
   Kablosuz eslestirme (`adb pair`) destegi. Subnet otomatik tahmin edilir.
9. **Ayarlar** - Acik/koyu tema (aninda uygulanir), log dosyasi ac/kapa,
   koruma listesi, **Sürüm / Kurulum Bilgisi** paneli (tek kaynak:
   `mibox_app/diagnostics.py` — sürüm, paket modu `kaynak|onefile|onedir`,
   Python/OS, adb yolu, log/ayar/veri yolları; "Panoya Kopyala" ile destek
   için tek tıkla alınır), ayar yedegi disari/ice aktarma (JSON).

Baglanti bekcisi: durum cubugunda canli cevrimici/cevrimdisi gostergesi,
15 sn yoklama, kopunca otomatik yeniden baglanti.

v5.0.0 yenilikleri:
- **Sahne**: tum kaldirma islemleri onceden toplanir, onizleme diyalogunda
  (islem/paket/not tablosu, riskli satir uyarili) onaylanir, tek zincirde
  uygulanir. Debloat sekmesinde Sahne cubugu, profiller onizlemeli calisir.
- **Otomatik baslayanlar** (Saglik): BOOT_COMPLETED dinleyen paketleri
  listeler, secilileri tek tikla kisitlar (acilis hizlandirma).
- **Otomatik bakim** (Saglik): acilis sagligi + onbellek temizligi, son
  calisma zamani kayitli, tek tikla manuel calistirma.
- **Snapshot klonlama** (Gecmis): Dis aktar/Ice aktar ile A cihazinin
  durumunu B cihazina tasi, Uygula ile kur (coklu TV yonetimi).

v6.0.0 (GitHub UAD arastirmasi):
- **UAD removal seviyeleri** (Debloat UAD sutunu): Recommended/Advanced/
  Expert/Unsafe renk kodlu; seviye ve kaynak (Google/Oem/Misc/Aosp/Carrier)
  filtreleri. Kaynak: 0x192/UAD + UAD-NG wiki 'removal'/'list' alanlari.
- **Bağımlılık uyarısı** (UAD neededBy): baska paketlerin ihtiyac duydugu
  paket secilirse islem oncesi uyarir; auto-remove YOK (UAD davranisi).
- **Unlisted filtresi** (UAD): DB de olmayan cihaz paketlerini listeler.
- **Seçim dışa/içe aktarma**: UAD `uad_exported_selection.txt` bicimiyle
  uyumlu; secimi dosyaya kaydet, baska kurulumda ice aktarip isaretle.
- **Multi-user**: `pm list users` taramasi, islem kullanicisi secimi
  (Owner disinda work profili vb.), user bazli kaldirma/dogrulama motoru.
  UAD 'Multi-user support' ozelligi.

## Calisma Prensibi

- **Bulk okuma**: `cmd appops get` ve `pm list packages -f` ile hizli tarama.
  Calisan tespiti `ps -A` ciktisindan tam-eslesme ile yapilir.
- **Koruma listesi**: varsayilan `ar.tvplayer.tv`, `com.spocky.projengmenu`.
- **Kalici ayarlar**: `mibox-ayarlar.json` (hedef, koruma, tema, gecmis,
  otomatik yenileme, HD ekran). Eski `MiBox-*.json` dosyalari okunur.
- **Bilinen adlar**: `mibox-bilinen-uygulamalar.json` (paket -> dost ad).
- **Favoriler**: `debloat-kullanici.json`.
- **Log**: `logs/` klasorunde gunluk dosya + seviyeli canli log.
- **Ekran goruntuleri**: `ekran-goruntuleri/` klasorunde + onizleme.
- **APK yedekleri**: `apk-yedekleri/` klasorunde (split ise alt klasor).
- **Cihaz gecmisi**: son 10 hedef, baglanti cubugundan secilir.

## .exe Olusturma

```bat
pip install pyinstaller
build_exe.bat            :: tek dosya  -> dist\MiBoxKonsol.exe
build_exe_onedir.bat     :: klasor     -> dist-onedir\MiBoxKonsol\MiBoxKonsol.exe
```

`dist\MiBoxKonsol.exe` olusturur. adb.exe dosyasini exe yanina kopyalayin.

**Hangi paket?**
- `build_exe.bat` (onefile): tek dosya, tasimasi kolay. Calisirken `%TEMP%`
  altinda gecici klasor acar.
- `build_exe_onedir.bat` (onedir): klasor halinde, **gecici klasor acmaz** —
  kisitli token/antivirus/temp kisitlamasi olan makinelerde sorunsuz calisir,
  acilisi daha hizlidir. `tools/build_onedir.py` ayni spec'ten uretir
  (exclude/filtre mantigi tek kaynaktan gelir, drift olmaz).

Paketi dogrulama (kaynagi degil, donmus exe'yi test eder):

```bat
dogrula_exe.bat
```

Bu betik `MiBoxKonsol.exe --version` ciktisini (surum + base_dir + log_dir)
ve `--selftest` isaretcisini kontrol eder. onedir pakette bu ikisi de
dogrulanmistir (`SELFTEST_OK`).

**Bilinen durum:** `Could not create temporary directory` hatasi UYGULAMADAN
degil, PyInstaller'in tek-dosya paketleyicisinden gelir: exe, Windows gecici
klasorunde (`%TEMP%`) kendi `_MEI...` klasorunu acamaz (kisitli token, antivirus
veya kilitli temp). Cozum sirasi: (1) **onedir paketi kullanin**
(`build_exe_onedir.bat`), (2) exe'yi baska bir klasore kopyalayip deneyin,
(3) antivirus/Defender istisnasi ekleyin, (4) kaynaktan calistirin
(`MiBox_Konsol.bat`).

## Cihaz Uyku Modu

Eger ADB "cannot connect" diyorsa cihaz uyku modunda olabilir.
Fiziksel kumandayla uyandin ve tekrar baglanin (veya Kumanda >
Uyandir tusunu deneyin).

## Mimari

```
mibox_app/
├── __init__.py       # versiyon + APP_NAME
├── main.py           # giris noktasi
├── adb_engine.py     # ADB motoru (subprocess, bulk okuma, appops, detay)
├── config.py         # Config (JSON kalicilik + gecmis + legacy okuma)
├── debloat_db.py     # kategorili bloatware veritabani + favoriler
├── workers.py        # QThread worker'lar (tarama, aksiyon, yedek)
├── core.py           # Core (engine + config + sinyaller)
└── ui/
    ├── theme.py      # Catppuccin Mocha/Latte QSS
    ├── main_window.py# ana pencere + baglanti + log
    ├── apps_tab.py   # Uygulamalar (detay, export, siralama)
    ├── remote_tab.py # Kumanda (D-pad, onizleme, genis bilgi)
    ├── debloat_tab.py# Debloat (arama, favori, riskli onay)
    ├── network_tab.py# Ag tarayici (aralik, pair, durdurma)
    └── settings_tab.py# Ayarlar (tema, yedek, filtre)
```

## Testler

- `python -m compileall mibox_app mibox.py` - derleme
- `python mibox.py --selftest` (offscreen) - acilis testi
- `python tests/run_all.py` - TUM offline test suite'leri tek komutla:
  - `tests/faz2_core_test.py` - onbellek uretim sayaci, kilitli config, history kilidi
  - `tests/faz5_security_test.py` - guvenlik: komut kapi, paket/yol/etiket dogrulama,
    kok dizin engeli, APK, keyevent, Google TV sihirbaz tanima/kapatma
    (106 iddia, offline)
  - `tests/faz7_quality_test.py` - logcat dedup, onbellegi TTL, Stage mantigi,
    snapshot dogrulama, input sanitize, gate regresyonu (47 iddia, offline)
  - `tests/faz8_ui_filtre_test.py` - Uygulamalar filtreleri: etiket/veri
    ayrimi + 7 durum filtresinin satir sayisi (17 iddia, offline)
  - `tests/faz9_dayaniklilik_test.py` - baglanti dayanikliligi: gecici/kalici
    hata ayrimi, bekci geri cekilmesi 15->30->60 sn (22 iddia, offline)
  - `tests/faz10_dil_test.py` - dil tutarliligi bekcisi: etiketler diakritikli
    ve ASCII-Turkce kalintisiz, veri anahtarlari ve DOSYA ADLARI ASCII
    (81 iddia, offline)
- `python tools/diakritik.py` - dil kurali denetimi/duzeltmesi:
  **etiket Turkce diakritikli, veri ASCII**. Kuru calistirma varsayilan;
  karsilastirma satirlarini ve regex/raw string'leri atlar.
- `dogrula.bat` - TEK TIK tam kapi (5 adim): sozdizimi + selftest + 6 suite +
  kalite taramasi + dil kurali (cikis kodu 0 = hepsi yesil; kirmiziysa teslim yok)
- `dogrula_exe.bat` - DONMUS paket dogrulamasi: **onefile + onedir + kurulu
  kopya**. Her biri icin `--version` ciktisi ve `--selftest` isaretcisi
  kontrol edilir; onefile'in `%TEMP%` kisitlamasi UYARI olarak raporlanir.
- `kur_onedir.bat` - onedir paketi kalici konuma kurar + masaustu/Baslat menusu
  kisayolu olusturur (ayrinti: "Kurulum" bolumu).
- `python tools/kalite_tara.py` - olu import / cakisan tanim / print() / TODO taramasi
- `python mibox.py --version` - surum + frozen/meipass/base_dir/log_dir teshis ciktisi
- `python tests/device_test.py [hedef]` - GERCEK cihaz dogrulamasi (offline suite'ler
  cihaz gerektirmez; sahte veri YOK). Restrict dongusu HOME launcher'ini,
  koruma listesini ve ROM paketlerini atlar; `unrestrict` her durumda calisir.
  Son kosum: **15/15 DEVICE_OK**. `python tests/device_scan.py` → **LIVE_OK**.
