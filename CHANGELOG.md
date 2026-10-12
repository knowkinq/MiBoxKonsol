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

### Eklenen
- Debloat DB ve "Üretici Artıkları" profiline
  `com.google.android.tungsten.setupwraith` kaydı.
- `tests/faz5_security_test.py` → [12] bölümü: kurulum sihirbazı tanıma,
  HOME paketi çıkarma ve "yalnızca sihirbaz paketi kapatılır" güvenliği
  (89 → 106 iddia).
- `.gitignore` (build/dist/__pycache__/logs/ayar ve snapshot dosyaları).

### Doğrulanmış
- `python -m compileall mibox_app` → temiz.
- `python mibox.py --selftest` → SELFTEST_OK.
- `python tests/run_all.py` → 3 suite yeşil (Faz2 + 106 güvenlik + 47 kalite).

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
