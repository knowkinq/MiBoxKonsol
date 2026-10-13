# Değişiklik Günlüğü

Tüm önemli sürüm değişiklikleri bu dosyada tutulur.
Biçim: [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/)'a dayanır.

## [8.5.0] - 2026-10-12

### Düzeltilen
- **Google TV / Android TV HOME kilidi:** `cmd package set-home-activity`
  hatasız dönse bile `com.google.android.tungsten.setupwraith` cihaz
  "kurulmadı" sayıldığı için HOME'u elinde tutuyordu; doğrulama
  "Dogrulama basarisiz: HOME hala .../.RecoveryActivity" ile düşüyordu.
  Artık `set_home_activity` engeli otomatik çözer:
  `device_provisioned` + `user_setup_complete` = 1 yazılır, HOME'u tutan
  kurulum sihirbazı user 0 için devre dışı bırakılır (`pm disable-user`,
  veri silinmez), ardından HOME yeniden ayarlanıp doğrulanır. Yapılan ek
  adımlar `engine.last_home_notes` üzerinden arayüzde raporlanır.
- Geçersiz HOME bileşeni hâlâ ilk adımda reddedilir (enjeksiyon testi korunur).
- **Filtre etiket/veri ayrımı (8.5.0 regresyonu):** filtre etiketleri
  Türkçeleştirilirken karşılaştırma **etiket metni** üzerinden yapılmıştı;
  motor verisi ASCII (`Kisitli`) ürettiği için
  (a) `Kısıtlı` filtresi **hiç sonuç vermiyordu**,
  (b) `Kaldırılmış` filtresi **kurulu uygulamaları da** listeliyordu.
  Artık etiket (görünen) ve veri (karşılaştırılan) ayrıdır: combo
  `addItem(etiket, veri)` ile kurulur, tüm karşılaştırmalar `currentData()`
  ve `DATA_*` sabitleriyle yapılır. Yazım düzeltmesi filtreyi bozamaz.
  (Regresyon testi: `tests/faz8_ui_filtre_test.py`.)
- **Zaman aşımı mesajı ↔ geçici-hata regex uyumu:** diakritik geçişinde mesaj
  `ADB zaman aşımı (...)` olurken `_TRANSIENT_CONNECT_RE` hâlâ `zaman asimi`
  arıyordu; bu, bağlantı tekrar denemesini sessizce devre dışı bırakırdı.
  Regex artık iki yazımı da tanır (`zaman\s*a[sş][iı]m[iı]`) ve bu bağ
  `tests/faz10_dil_test.py` ile kilitlendi.
- **Türkçe dil tutarlılığı (diakritik geçişi):** 18 modülde ~360 görünen metin
  düzeltildi (`Baglan`→`Bağlan`, `Kisitla`→`Kısıtla`, `Guv...`→`Güv...`).
  Kural: **etiket Türkçe diakritikli, veri ASCII**.
  - Motor verisi (`Kisitli`, `Serbest`, `Evet`, `Hayir`) ve kategori anahtarları
    (`guvenli`, `dokunma`) değişmedi.
  - Durum sütunu `DISPLAY_STATUS` ile çevrilir (`Kisitli` → `Kısıtlı`).
  - `tests/device_scan.py` başlık doğrulaması yeni Türkçe başlıklara güncellendi
    (`Seç`, `Çalışıyor`).
  - `tools/diakritik.py`: token (string sabiti) seviyesinde çalışır; raw/regex
    string'lere ve karşılaştırma satırlarına dokunmaz, `--uygula` olmadan kuru
    çalışır. Son durum: **0 kalıntı**.
- **Testler kullanıcı verisine yazıyordu (veri kirliliği):** `faz2_core_test`
  gerçek `mibox-ayarlar.json` ve gerçek işlem geçmişi dosyasına yazıyordu.
  Sonuç: geçmişin **521 kaydından 520'si `"action": "test"`** olmuş,
  `last_target` ve cihaz geçmişi sahte `10.0.x.y:5555` hedefleriyle dolmuştu
  (uygulama açılınca hedef alanı sahte IP gösteriyordu). Artık:
  - `tests/faz2_core_test.py` config ve geçmiş yollarını **geçici klasöre**
    yönlendirir ve sonunda gerçek dosyaların **değişmediğini doğrular**
    (`OK gercek ayar/gecmis dosyalari korundu`).
  - `tests/faz7_quality_test.py` snapshot testi de geçici dizin kullanır
    (test dosyası kullanıcının snapshot listesinde görünmez).
  - Kirli veri yedeklenerek temizlendi: 520 test kaydı silindi, sahte
    hedefler ayarlardan çıkarıldı, gerçek hedef (`192.0.2.1:5555`) geri
    yazıldı. Yedek: `_arsiv/veri-yedegi-<tarih>/`.
- **Dosya adları (VERİ) diakritik aracının hedefi olmaktan çıkarıldı:**
  `mibox-islem-gecmisi.jsonl`, `debloat-kullanici.json` ve varsayılan CSV adı
  ASCII'ye geri alındı (çevrilirse eski geçmiş/favori dosyası bulunamaz).
  Araç artık `os.path.*`, `open()`, `QFileDialog` satırlarını ve uzantılı
  string'leri `DOSYA-YOLU` olarak raporlayıp **atlar**; `faz10` bu adları
  kalıcı olarak korur.

### Değiştirilen
- **Uygulamalar sekmesi filtreleri:** ayrı `Çalışan` / `Kaldırılmış` /
  `Sistem` onay kutuları kaldırıldı; işlevleri tek "Tümü" açılır listesine
  taşındı (`Tümü`, `Kısıtlı`, `Serbest`, `Devre dışı`, `Kaldırılmış`,
  `Çalışan`, `Sistem`). Arama + durum + `Debloat: Tümü` + `CSV` tek satırda,
  `Yenile` alt satırda. `Kaldırılmış` seçimi `show_removed`, `Sistem` seçimi
  `include_system` ayarını kalıcı olarak yönetir (eski kutuların davranışı).
- `AppScanWorker` uygulama sözlüğüne `system` alanı eklendi (APK yolu
  `/system`, `/system_ext`, `/vendor`, `/product`, `/apex`, `/odm`, `/oem`
  altındaysa True).
- **Bağlantı dayanıklılığı:**
  `AdbEngine.connect(target, timeout, deneme=1, bekleme=0.6)` — varsayılan tek
  deneme (etkileşimli "Bağlan" hızlı başarısız olur), arka plan bekçisi
  `deneme=2` verir ve yalnızca **geçici** hatalarda (zaman aşımı, `unable to
  connect`, `no route`, `device offline`) kısa beklemeyle tekrar dener;
  kalıcı hatalarda (geçersiz paket, adb yok, yetki) tekrar denenmez.
  Bekçi aralığı ardışık hatada kademeli uzar: 15 → 30 → 60 sn
  (`watchdog_interval`), başarıda tabana döner. Cihaz uykudayken log/ADB
  gürültüsü biter.
- **Ölü import temizliği:** 11 modülde 28 kullanılmayan import kaldırıldı
  (`apps_tab`, `debloat_tab`, `files_tab`, `history_tab`, `install_tab`,
  `kit.py`, `logcat_tab`, `main_window`, `network_tab`, `remote_tab`,
  `stage_dialog`, `health_tab`).

### Eklenen
- Debloat DB ve "Üretici Artıkları" profiline
  `com.google.android.tungsten.setupwraith` kaydı.
- `tests/faz5_security_test.py` → [12] bölümü: kurulum sihirbazı tanıma,
  HOME paketi çıkarma ve "yalnızca sihirbaz paketi kapatılır" güvenliği
  (89 → 106 iddia).
- `tests/faz8_ui_filtre_test.py` — 17 iddia: etiket/veri ayrımı ve yedi durum
  filtresinin satır sayısı (offline, `QT_QPA_PLATFORM=offscreen`).
- `tests/faz9_dayaniklilik_test.py` — 22 iddia: geçici/kalıcı hata ayrımı,
  bekçi geri çekilmesi, `connect()` sözleşmesi (offline).
- `tests/faz10_dil_test.py` — 81 iddia: dil tutarlılığı bekçisi (etiketler
  diakritikli ve ASCII-Türkçe kalıntısız; veri anahtarları/sabitleri ASCII;
  dosya adları ASCII; zaman aşımı mesajı ↔ regex uyumu).
- `tools/diakritik.py` — güvenli diakritik düzeltme aracı (kuru çalıştırma
  varsayılan, karşılaştırma satırlarını raporlar, raw/regex string'leri atlar).
- `.gitignore` (build/dist/__pycache__/logs/ayar ve snapshot dosyaları).
- **`--version` / `--bilgi` CLI:** pencere açmadan sürüm + ortam bilgisi
  (`frozen`, `meipass`, `executable`, `base_dir`, `log_dir`, `selftest`
  işaretçi yolu, `cwd`). Paketleme teşhisi için: `MiBoxKonsol.exe --version`.
  `mibox.py` ve `mibox_app/main.py` artık tek `main()` dağıtıcısını kullanır.
- `dogrula.bat` (kaynak doğrulama) ve `dogrula_exe.bat` (donmuş exe doğrulama).
- **ONEDIR paketleme:** `build_exe_onedir.bat` + `tools/build_onedir.py`.
  Üretici, `MiBoxKonsol.spec`'i okuyup yalnızca `EXE(...)` bloğunu
  `EXE+COLLECT` (onedir) bloğuna çevirir; exclude/filtre mantığı tek
  kaynaktan geldiği için iki paket arasında drift olmaz. Çıktı:
  `dist-onedir\MiBoxKonsol\MiBoxKonsol.exe`. Onefile'ın `%TEMP%` altında
  geçici klasör açma zorunluluğu yoktur — kısıtlı makinelerde çalışır.
- **ONEDIR kurulum + kısayol:** `kur_onedir.bat` + `tools/kur_onedir.ps1`.
  Paketi `%LOCALAPPDATA%\MiBoxKonsol` içine kurar (**kullanıcı verisi
  korunur**: ayar/log/geçmiş/snapshot/favori dosyaları üzerine yazılmaz),
  `adb.exe` bulunursa paket yanına kopyalar, **Masaüstü** ve **Başlat menüsü**
  kısayolu oluşturur, `kaldir.bat` bırakır (`/veri` ile veriyi de siler) ve
  kurulum sonunda `--version` + `--selftest` ile kendini doğrular; temiz
  kurulumda oluşan doğrulama artıkları geri temizlenir.
- `tools/kalite_tara.py` — ölü import / aynı dosyada çakışan tanım / `print()` /
  TODO tarayıcısı (`--siki` ile bulgu varsa çıkış kodu 1).
- Git deposu + `.gitattributes` (kaynak LF, `.bat/.ps1` CRLF).

### Doğrulanmış
- `python -m compileall mibox_app tests` → temiz.
- `python mibox.py --selftest` → SELFTEST_OK.
- `python tests/run_all.py` → **6 suite yeşil** (Faz2 + 106 güvenlik + 47 kalite
  + 17 UI filtre + 22 dayanıklılık + 81 dil) → `ALL_TESTS_OK`.
- `python tools/kalite_tara.py --siki` → 0 bulgu.
- `python tools/diakritik.py` (kuru) → 0 kalıntı.
- Testlerden sonra gerçek kullanıcı verisi **değişmemiş** olarak doğrulandı
  (faz2 "gercek ayar/gecmis dosyalari korundu"; snapshot listesi boş).
- **GERÇEK CİHAZ DOĞRULAMASI (13.10.2026, 192.0.2.1:5555):**
  - `python tests/device_test.py` → **15/15 DEVICE_OK** (bağlantı, detaylı liste,
    önbellek soğuk/sıcak, user0, çalışan tespiti, sağlık, snapshot+fark+sil,
    restrict→doğrula→unrestrict→doğrula, ekran görüntüsü PNG, logcat, dosya
    listesi, otomatik başlayanlar).
  - `python tests/device_scan.py` → **LIVE_OK**: başlıklar `['Seç','Uygulama',
    'Paket','Durum','Çalışıyor','Debloat','Aktif']`; özet "Gösterilen: 130 |
    Serbest: 126 | Kısıtlı: 4 | Kaldırılmış: 16 | Debloat DB de: 26" →
    diakritik geçişi, `DISPLAY_STATUS` eşlemesi ve filtre sayıları gerçek
    veriyle doğrulandı. Debloat DB'de eklenen
    `com.google.android.tungsten.setupwraith` cihazda "Güvenli" olarak göründü.
- **`tests/device_test.py` güvenlik sertleştirmesi:** restrict döngüsü artık
  HOME launcher'ını, kullanıcının koruma listesini, zaten kısıtlı paketleri ve
  ROM paketlerini (`/system`, `/vendor`, `/product` …) **atlar**; seçim
  `/data/app` (kullanıcı uygulaması) ile sınırlıdır ve `unrestrict` hata olsa
  bile `finally` ile **mutlaka** çalışır.
- **Tek tık kapı genişletildi:** `dogrula.bat` 5 adım (sözdizimi + selftest +
  6 suite + kalite taraması + dil kuralı); `dogrula_exe.bat` artık
  **onefile + onedir + kurulu kopya** için `--version` + `--selftest`
  doğrular (onefile `%TEMP%` hatası UYARI olarak raporlanır).
- **Kurulum doğrulaması:** `kur_onedir.bat` sonrası kurulu kopyada
  `--version` = `MiBox Konsol v8.5.0` ve `--selftest` = `SELFTEST_OK`;
  `dogrula_exe.bat` → `TAMAM (uyarili)` (yalnızca onefile `%TEMP%` uyarısı);
  `dogrula.bat` → çıkış kodu 0 (274 iddia + kalite 0 bulgu).
- Gerçek cihaz (salt-okunur ölçüm): hedefe bağlantı 0.28 sn; erişilemez
  adreste `deneme=1` → 3.0 sn, `deneme=2` → 6.3 sn (tekrar deneme çalışıyor).
- `MiBoxKonsol.exe` 24,05 MB üretildi. **Not:** Bu oturumda donmuş exe'nin
  çalıştırma testi yapılamadı — `%TEMP%` altında `_MEI...` klasörü açılamıyor
  (`Could not create temporary directory!`); aynı hata 3 satırlık bir
  hello-world onefile exe'de de tekrarlandığı için bunun **oturum/ortam
  kısıtlaması** olduğu kanıtlandı (kaynak çalıştırma ve PowerShell klasör
  açabiliyor). Exe doğrulaması kullanıcı tarafında `dogrula_exe.bat` ile
  yapılır; ayrıntı README ".exe Olusturma" bölümünde.
- **ONEDIR paket uçtan uca doğrulandı:** `dist-onedir\MiBoxKonsol\MiBoxKonsol.exe`
  → `--version` çıkış kodu 0 (`frozen: True`, `base_dir` = paket klasörü) ve
  `--selftest` çıkış kodu 0 + `mibox-selftest-ok.txt` = `SELFTEST_OK`.
  Paket içinde `qwindows/qoffscreen/qminimal` platform eklentileri ve
  `python314.dll` doğrulandı (59,3 MB klasör). Bu, donmuş kod yolunun,
  `--version` teşhisinin ve `BASE_DIR` mantığının çalıştığını kanıtlar;
  onefile'daki hata yalnızca oturumun `%TEMP%` kısıtlamasıdır.


## [8.4.0] - 2026-10-12

### Eklenen
- **Güvenlik katmanı (Faz5):** Komut kapısı (gate) shell metakarakterlerini
  (`; && || | $() \` <>` + CR/LF) reddeder; paket adı, uzak yol, logcat
  seviye/etiket, animasyon ölçeği, HOME bileşeni, kullanıcı id ve APK yolu
  doğrulamaları `adb_engine` içinde zorunlu.
- `tests/faz5_security_test.py` — 89 iddialı offline güvenlik test suite'i.
- `tests/faz7_quality_test.py` — 47 iddialı kalite suite'i: logcat dedup,
  paket önbellek TTL, Stage mantığı, snapshot doğrulama, `sanitize_input_text`,
  gate regresyonu.
- `tests/run_all.py` — tüm offline suite'leri tek komutla çalıştırır.
- `CHANGELOG.md` — bu dosya.

### Değiştirilen
- **Logcat canlı izleme (Faz6):** 3 sn'lik yoklamada aynı 120 satırlık pencere
  tekrar tekrar ekleniyordu; kayan pencere örtüsü (overlap) algısı ile yalnızca
  yeni satırlar eklenir (`dedup_new_lines`).
- **Günlük log dosyası (Faz6):** `_daily_log_path` gün bazlı önbellekli;
  satır başına `makedirs` yok, yazma kilidi thread-güvenli.
- `logcat_dump` seviye doğrulaması tam string (önce `[:1]`'di).
- `set_home_activity` / `set_animator_scales` doğrulama sonrası temizlenmiş
  değeri kullanır.
- README "Testler" bölümü genişletildi (offline suite'ler + cihaz testi ayrımı).

### Düzeltilen
- `install_apk` / `install_multiple`: uzantı, CR/LF/NUL ve dosya varlığı
  kontrolü; toplu kurulumda liste sanitizasyonu + dedup.
- `uninstall_user_id` / `is_uninstalled_for_user_id`: paket + kullanıcı id
  doğrulaması.
- `logcat_crash`: satır sayısı `clamp_lines` ile sınırlı.

### Doğrulanmış
- `python tests/run_all.py` → FAZ2/FAZ5/FAZ7 tümü yeşil (139 iddia).
- `python mibox.py --selftest` → SELFTEST_OK.
- `pyinstaller MiBoxKonsol.spec` → 25.2 MB tek dosya exe, `--selftest` donmuş
  exe üzerinde de SELFTEST_OK; dist'e ayar dosyası sızması yok.

## [8.3.0]
- Faz1–Faz4 modernizasyonu: stabilite, çekirdek önbellek/kilitler, worker
  iptal disiplini, tema/UX tutarlılığı. (Detaylar bu sürümde tutulmadı.)
