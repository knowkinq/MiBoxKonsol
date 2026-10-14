# Değişiklik günlüğü

## [1.2.2] - 2026-10-14

- Windows konsolunda `--version` çıktısının Türkçe karakterlerde hata vermesi düzeltildi.
- ADB bulunmadığında selftest akışının uyarı penceresi açıp beklemesi engellendi.

## [1.2.0] - 2026-10-14

Popüler TV Uygulama Marketi, Çözünürlük & DPI Yöneticisi, Canlı TV Ağ Teşhisi ve Sıfır-Kaydırma Arayüz sürümü.

- **Popüler TV Uygulama Kataloğu & Sideload Merkezi (App Store)**:
  - SmartTube (Kararlı & Beta), Projectivy Launcher, FLauncher, Kodi, VLC, Nova Video Player, Send Files to TV, Aptoide TV, Aurora Store, Button Mapper gibi Android TV için optimize açık kaynak uygulamaları tek tıkla resmi kaynaklarından indirip TV'ye yükleme.
  - Cihazdaki kurulum durumunu canlı denetleme (`✓ TV'de Kurulu` / `Kurulu Değil`), doğrudan TV'de başlatma (`TV'de Aç`) ve yeniden kurma desteği.
  - Kategori ve arama filtreleri, anlık indirme hızı ve bayt ilerleme çubuğu.
- **Ekran Çözünürlüğü ve DPI / Arayüz Ölçeği Yöneticisi**:
  - `Sağlık` sekmesine eklenen özel `Ekran & Çözünürlük` paneli ve `Optimizasyon` kontrolleri.
  - 1080p Full HD, 720p HD (menü ve donanım hızlandırma için ideal), 4K UHD çözünürlükleri arasında tek tıkla geçiş.
  - Arayüz ölçeği (240 DPI kompakt, 280 DPI orta, 320 DPI standart, 360 DPI büyük yazılar) ve fabrika DPI değerine sıfırlama.
  - Kenarları kesilen TV'ler için Ekran Taşması (Overscan) düzeltmesi (15px, 30px, 45px içeri çekme veya sıfırlama).
  - 15 saniyelik otomatik güvenli geri alma sayacı (kullanıcı onaylamazsa çözünürlük otomatik olarak eski haline döner).
- **Canlı TV WiFi ve Ağ Sağlığı Teşhisi**:
  - `Ağ` sekmesine eklenen canlı teşhis kartı: Wi-Fi sinyal kalitesi (RSSI dBm & %), bağlantı link hızı (Mbps) ve frekans (5 GHz / 2.4 GHz).
  - TV kutusundan modeme gerçek zamanlı ping gecikmesi ve paket kaybı testi.
  - Akıllı Türkçe tavsiye motoru (4K yayın uyumluluğu, parazit ve modem mesafesi uyarısı).
- **Arayüz Kararlılığı ve Sıfır-Kaydırma Ergonomisi**:
  - İşlem etkinlik çubuğu (`activity_box`) ana çalışma alanından durum çubuğuna (`QStatusBar`) taşınarak ekran yenilemelerindeki pencere zıplamaları sıfırlandı.
  - `Kumanda` sekmesi kompakt iki sütunlu mimariye geçirilerek 1360×768 çözünürlükte kaydırma çubuğu gereksinimi tamamen ortadan kaldırıldı.
  - `Kurulum` sekmesi 3 alt sekmeye bölünerek modülerleştirildi.
- **Hata Düzeltmeleri & İyileştirmeler (v1.2.1)**:
  - **Pencere Kapanışında Donma / Bekleme Sorunu Giderildi (`main_window.py`, `workers.py`, `adb_engine.py`)**:
    - Arka planda ADB işlemi çalışırken (örneğin ulaşılamayan bir cihaza bağlanma veya sorgulama sürerken) pencerenin `[X]` ile kapatılmak istendiğinde "Çalışan işler durduruluyor; tamamlanınca pencere kapanacak" durumunda sonsuza kadar takılı kalması sorunu tamamen çözüldü.
    - Kapanışa 600ms'lik kesin zaman aşımı bekçisi eklendi; işler durmasa bile pencere güvenle sonlandırılır.
    - Bekleme sırasındayken tekrar `[X]` (Kapat) tuşuna basıldığında beklemeden anında kapanması sağlandı.
    - `AdbEngine.connect` ve tüm worker iş parçacıklarına `cancel_check` iletimi eklenerek soket/ağ düzeyinde bloklanan süreçlerin hemen sonlandırılması sağlandı.
  - **32-Bit (x86) Windows Desteği & Çift Qt Motoru Uyumluluğu (`qt_compat.py`)**:
    - Qt 6 (PySide6) resmi olarak 32-bit Windows binary paketleri sunmadığı için, x86 tabanlı 32-bit Windows sistemlerde uygulamanın sorunsuz çalışmasını sağlayan akıllı `qt_compat` uyumluluk köprüsü eklendi.
    - 64-bit sistemlerde varsayılan `PySide6 (Qt 6)` çalışmaya devam ederken; 32-bit ortamlarda resmi x86 tekerleği bulunan `PyQt5 (Qt 5)` otomatik olarak devreye girip `PySide6` API'sine şimlenir.
    - `requirements.txt` dosyasına PEP 508 mimari belirteçleri ve özel `requirements-x86.txt` eklendi.
    - `build_exe.bat`, `MiBox_Konsol.bat` ve yeni eklenen `build_exe_x86.bat` betikleri sistem/Python mimarisini otomatik tespit ederek 32-bit (`MiBoxKonsol_x86.exe`) veya 64-bit (`MiBoxKonsol_x64.exe`) paketler üretebilir hale getirildi.
    - `diagnostics.py` ve Ayarlar sekmesine mimari (x86/x64) ve aktif Qt motoru tanılama bilgileri eklendi.
  - **Açılışta Otomatik Bağlanmanın Kaldırılması (`main_window.py` & `settings_tab.py`)**:
    - Uygulama ilk açıldığında son hedefe otomatik bağlanmaya çalışma davranışı (`self.on_connect()`) kaldırıldı; cihaz kapalıyken yaşanan zaman aşımı veya bağlantı bekleme donmaları sonlandırıldı.
    - Ayarlar sekmesindeki "Açılışta son hedefe otomatik bağlan" onay kutusu kaldırıldı.
    - Uygulama artık açılışta bağlı cihazları sadece tespit edip açılır kutuda listeler ve bağlanma kontrolünü tamamen kullanıcıya bırakır.
  - **Logcat Temizleme Onarımı (`logcat_tab.py`)**: Logcat sekmesinde "Logu Temizle" tıklandığında ekranın temizlenmemesi ve önbellek satırlarının silinmemesi sorunu çözüldü. Arayüze anında ekranı silen `[Ekranı Temizle]` ve cihaz günlüğünü arka planda temizleyen `[Cihaz Logunu Temizle]` düğmeleri eklendi; modal onay kutusu engeli kaldırılarak akıcı hale getirildi.
  - **Kumanda Sekmesi Tasarımı — Ön Planda Kumanda & Kompakt Sağ Panel (`remote_tab.py`)**:
    - **Ön Planda Geniş ve Ergonomik Kumanda**: Kumanda gövdesi 400px genişliğe getirilerek ekranın ana odak noktası yapıldı. D-Pad yön gezinme takımı 170×170px dairesel forma, yön tuşları 46px'e ve OK tuşu 52px'e büyütüldü. Tüm butonlar 34px yükseklik ve ferah tıklama alanlarıyla gerçek bir fiziksel kumanda hissiyatına kavuşturuldu.
    - **Kompakt Sağ Panel**: Sağ taraftaki uygulama başlatma ve ekran önizleme kartları maksimum 480px genişlikle sınırlandırıldı; devasa boşluk kaplaması engellendi. TV önizleme ekranı kompakt 16:9 çerçeveye (340×192 - 400×225) ayarlandı ve ekran araç çubukları düzenli satırlar halinde toplandı.
    - **Sıfır Taşma ve Kesilme**: Uygulama ve metin girişi kutularındaki metin kırpılmaları giderildi; sayı tuşları katlanabilir akordeon (`🔢 Sayı Tuşları ▾`) ile optimize edildi.
  - **Uygulama Başlatma (`launch_app`)**: `AdbEngine` sınıfına `launch_app` metodu eklendi. Android TV uygulamalarının `LEANBACK_LAUNCHER` ve standart `LAUNCHER` niyetleri taranarak `AttributeError: 'AdbEngine' object has no attribute 'launch_app'` hatası giderildi; TV'de başlatma işlemi arka plan Worker iş parçacığına taşınarak donmalar engellendi.
  - **Komut Güvenlik Kapısı Güncellemesi**: `gate.py` içine `am start` komutu izinli eklendi.
  - **AdbEngine `is_installed` Eksikliği**: Kurulum sonrasında paketin varlığını doğrulayan `is_installed` metodu `AdbEngine` sınıfına eklendi (`pm path <pkg>` sorgusu). `AttributeError: 'AdbEngine' object has no attribute 'is_installed'` hatası ve uygulamanın TV'ye kurulduğu halde tabloda "Kurulu Değil" kalması sorunu tamamen giderildi.
  - **SmartTube & Katalog Paket Eşleşmesi**: SmartTube'un güncel paket adı `org.smarttube.stable` ve `org.smarttube.beta` olarak tanımlandı; geriye dönük uyumluluk için `alt_packages` desteği eklendi.
  - **Otomatik Canlı Senkronizasyon**: Kurulum sekmesine geçildiğinde (`showEvent`) ve kurulum sonrasında (`invalidate_pkg_cache`) paket durumu otomatik taranarak tablo anında güncelleniyor.
  - **Sistem Uygulama Filtre Düğmesi Görsel Yenilemesi (`apps_tab.py`)**: `Uygulamalar` sekmesindeki `Sistem` filtre düğmesi, açık ve kapalı durumları arasında anında fark edilen iki katmanlı modern durum mimarisine geçirildi:
    - *Açıkken (Sistem Dahil):* `✓ Sistem (119)` metni, dolgulu canlı indigo arkaplan (`#38457c`), beyaz kalın yazı (`#ffffff`) ve parlak kenarlık (`#8795ff`).
    - *Kapalıyken (Sistem Gizli):* `○ Sistem: Gizli (119)` metni, saydam arkaplan, kesikli (dashed) kenarlık ve soluk gri metin (`#828c9f`).
    - Duruma göre dinamik Türkçe ipucu (tooltip) ve açık/koyu tema uyumluluğu eklendi.
- **Test ve Güvenilirlik**:
  - Birim test sayısı 34'e çıkarıldı (100% geçiş, 0.17s).
  - Güvenlik kapısına `wm overscan` ve `am start` izinleri eklendi.

## [1.1.0] - 2026-10-13

Kapsamlı modernizasyon, donanım telemetrisi, etkileşimli kumanda ve gelişmiş optimizasyon sürümü.

- **Etkileşimli Kumanda**:
  - PC ekranı üzerinden fare ile tıklayarak TV'ye dokunma (`input tap`) ve sürükleyerek kaydırma (`input swipe`) desteği.
  - Canlı ekran önizleme modu (2 saniyelik otomatik sessiz yenileme).
  - PC fiziksel klavye yönlendirmesi (Ok tuşları, Enter, Esc/Geri, Home, Menü, Rakamlar).
  - 3x4 sayısal tuş takımı, Son Uygulamalar (App Switcher), TV Giriş ve TV Ayarlar düğmeleri.
- **Donanım ve Sağlık Telemetrisi**:
  - Ekran çözünürlüğü, yenileme hızı (Hz), yoğunluk (DPI) ve bağlı HDMI TV modeli (ör. LG TV).
  - İşlemci/SoC bilgisi (Amlogic S905X4 vb.), CPU çekirdek sayısı, 64-bit ABI ve anlık termal sıcaklık.
- **Optimizasyon ve Güvenlik**:
  - **1-Tıkla Süper Hızlandırma (Quick Boost)**: Arka planı temizleyip önbelleği boşaltan, animasyonları 0.5× yapan ve kazanılan RAM miktarını bildiren tek tık bakım.
  - **Özel Güvenli DNS**: Sistem genelinde reklam ve izleyici engelleme için AdGuard DNS (`dns.adguard.com`), Cloudflare DNS ve Google DNS arasında tek tıkla geçiş.
  - Güvenlik kapısı geliştirmeleri: `mkfs` ve dosya sistemi biçimlendirme girişimleri engellendi.
- **Debloat ve Paket Veritabanı**:
  - Xiaomi Android 14/HyperOS TV ve Google TV güncel paketleri veritabanına eklendi.
  - 3 yeni hazır profil: `xiaomi_ultra`, `low_ram` (1GB/2GB bellek tasarrufu), `google_clean` (öneri ve reklam temizliği).
  - 30'dan fazla popüler TV ve IPTV uygulaması için Türkçe dost isim tanımlamaları.
- **Dosya Yöneticisi ve APK Kurulumu**:
  - Cihaza takılı harici USB flash bellekleri (`/storage/XXXX-XXXX`) otomatik algılama ve tek tıkla gezinme.
  - **Cihazda Doğrudan Kur**: TV hafızasındaki veya USB'deki APK'ları PC'ye indirmeden doğrudan kurma.
  - Windows Dosya Gezgini'nden sürükle-bırak (Drag & Drop) ile cihaza dosya yükleme.
  - APK kurulumunda etiket, paket adı, sürüm ve min SDK meta verilerini okuma ve gösterme.
  - Kurulum seçenekleri (`-r` üzerine yaz, `-g` tüm izinleri otomatik ver, `-d` sürüm düşür).
- **Bağlantı & Ayarlar**:
  - Açılışta tek bağlı cihazı otomatik algılama ve isteğe bağlı son cihaza otomatik bağlanma.
  - Ayarlar sekmesinde klavye gezinimi, otomatik izin verme ve otomatik bağlanma tercihleri.
- **Test ve Kararlılık**:
  - Sıfır çökme, temiz iş parçacığı sonlandırma ve derleme doğrulaması.

## [1.0.0] - 2026-10-13

İlk herkese açık sürüm.

- Android TV cihazları için ADB tabanlı masaüstü yönetimi
- Uygulama yönetimi, debloat, kumanda, dosya aktarımı ve APK kurulumu
- Ağ tarama, cihaz sağlık bilgileri, geçmiş ve anlık görüntüler
- Windows için tek dosya ve klasör tabanlı paketleme betikleri
