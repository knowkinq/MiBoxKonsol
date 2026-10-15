# MiBox Konsol

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg" alt="Python 3.10+"></a>
  <a href="https://wiki.qt.io"><img src="https://img.shields.io/badge/Qt-PySide6%20(x64)%20%7C%20PyQt5%20(x86)-informational.svg" alt="Qt Support"></a>
  <a href="https://www.microsoft.com"><img src="https://img.shields.io/badge/Platform-Windows%20(x64%20%26%20x86)-lightgrey.svg" alt="Windows x64 & x86"></a>
</p>

Xiaomi Mi Box, Mi TV Stick ve tüm Android TV cihazlarını yerel ağ üzerinden (ADB) yönetmek, optimize etmek ve gereksiz sistem uygulamalarından (bloatware) arındırmak için geliştirilmiş modern, açık kaynaklı Windows masaüstü yönetim merkezi.

**Sürüm:** `v1.3.0`

---

## 📸 Ekran Görüntüleri

<table>
  <tr>
    <td width="50%" align="center">
      <img src="docs/screenshots/apps.jpg" alt="Uygulamalar" width="100%"><br>
      <strong>Uygulamalar & Paket Yönetimi</strong>
    </td>
    <td width="50%" align="center">
      <img src="docs/screenshots/remote.jpg" alt="Kumanda" width="100%"><br>
      <strong>Ön Planda Kumanda & Canlı Ekran</strong>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="docs/screenshots/debloat.jpg" alt="Debloat" width="100%"><br>
      <strong>Gelişmiş Debloat & Hazır Profiller</strong>
    </td>
    <td width="50%" align="center">
      <img src="docs/screenshots/health.jpg" alt="Sağlık" width="100%"><br>
      <strong>Cihaz Sağlığı & Donanım Telemetrisi</strong>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="docs/screenshots/files.jpg" alt="Dosyalar" width="100%"><br>
      <strong>Dosyalar & USB Yönetimi</strong>
    </td>
    <td width="50%" align="center">
      <img src="docs/screenshots/install.jpg" alt="Kurulum" width="100%"><br>
      <strong>TV Uygulama Marketi & Sideload</strong>
    </td>
  </tr>
</table>

---

## 🚀 Öne Çıkan Özellikler

### 1. 🛍️ Popüler TV Uygulama Kataloğu & Sideload (App Store)
- Android TV için optimize açık kaynaklı ve popüler uygulamaları tek tıkla resmi kaynaklarından indirip TV'ye yükleme:
  - **Medya & Video:** SmartTube (Kararlı & Beta), Stremio Android TV, Jellyfin Android TV, Kodi Media Center, VLC for Android, Nova Video Player
  - **Arayüz (Launcher):** Projectivy Launcher, FLauncher
  - **Dosya & Araçlar:** Send Files to TV, Button Mapper, AnExplorer TV File Manager
  - **Oyun & Akış:** Moonlight Game Streaming (PC oyunlarını 4K 60/120 FPS TV'ye aktarma)
  - **TV Mağazası:** Aptoide TV, Aurora Store (Google Play Store açık kaynak istemcisi)
- TV'de anlık kurulu olma durumunu denetleme (`✓ TV'de Kurulu`), doğrudan başlatma (`▶ TV'de Aç`) ve yeniden kurma.
- İndirme hızı ve bayt ilerleme göstergeli arka plan iş parçacığı.

### 2. 🎛️ Ön Planda TV Uzaktan Kumandası & Canlı Ekran Etkileşimi
- **Ferah ve Ergonomik Kumanda:** Dairesel D-Pad takımına ve rahat butonlara sahip modern fiziksel kumanda tasarımı.
- **Canlı Ekran Önizleme (Screen Mirroring):** TV ekranını PC üzerinden gerçek zamanlı izleme, fareyle dokunma (tap) ve sürükleme (swipe).
- **Ekran Görüntüsü Yakalama:** Tek tıkla TV ekran görüntüsünü PNG olarak PC'ye kaydetme.
- **Scrcpy Entegrasyonu:** Cihaz ve ağ koşullarına bağlı olarak 60 FPS'e kadar düşük gecikmeli ekran yansıtma.
- **Pano Senkronizasyonu (Clipboard):** Bilgisayarda kopyalanan metin veya linkleri tek tıkla TV'ye yapıştırma.
- **Klavye Yönlendirmesi:** PC klavye yön tuşlarını, Enter (OK), Esc/Backspace ve sayıları TV'ye anında iletme.
- **Hızlı TV Uygulama Başlatıcı:** YouTube/SmartTube, Netflix, Kodi, VLC, Projectivy tek tıkla başlatma.

### 3. ⚡ Güvenlik Denetimli ADB Shell Terminali
- TV üzerinde izin verilen teşhis komutlarını çalıştırın; ayar ve sistem değişiklikleri açık onay ister, tanınmayan ve tehlikeli komutlar engellenir.
- Yukarı/Aşağı ok tuşlarıyla komut geçmişi (History) desteği.
- Hazır tek tıkla sistem teşhis düğmeleri: CPU kullanımı, bellek, disk, pil, ekran boyutu, ağ rotası, cihaz modeli, kullanıcı paketleri, Logcat ve Wi-Fi.

### 4. 🖥️ Ekran Çözünürlüğü, DPI & Overscan Yöneticisi
- **Çözünürlük Değiştirme:** 1080p Full HD, 720p HD (menü ve donanım hızlandırma için ideal), 4K UHD arasında geçiş.
- **Arayüz Ölçeği (DPI):** 240 DPI (Kompakt), 280 DPI, 320 DPI (Standart), 360 DPI (Büyük yazılar).
- **Ekran Kenar Taşması (Overscan):** Kenarları kesilen TV'ler için içeri çekme veya sıfırlama.
- **Güvenlik Sayacı:** Onaylanmayan değişiklikler 15 saniye içinde otomatik olarak fabrika değerlerine geri döner.

### 5. 📶 Canlı TV Wi-Fi & Ağ Sağlığı Teşhisi
- TV kutusunun anlık sinyal gücü (RSSI dBm & %), link bağlantı hızı (Mbps) ve frekans bandı (5 GHz / 2.4 GHz).
- TV kutusundan modeme gerçek zamanlı ping gecikmesi ve paket kaybı testi.
- 4K yayın uyumluluğu ve modem mesafesi analizi sunan akıllı Türkçe tavsiye motoru.

### 6. 🧹 Gelişmiş Debloat & Hazır Profiller
- Android 9-14, Google TV ve Xiaomi HyperOS için güvenli/opsiyonel/riskli paket sınıflandırması.
- **Hazır Profiller:** `xiaomi_ultra`, `low_ram`, `google_clean`, `gaming_mode` (Oyun & Emülatör Modu) ile tek tıkla temizlik.
- Yapılan işlemler öncesinde otomatik anlık yedek (`snapshot`) alarak istenildiği an tek tıkla geri yükleme (rollback).

### 7. ⚡ 1-Tıkla Süper Hızlandırma & Donanım Telemetrisi
- Arka plan önbelleklerini temizler, gereksiz süreçleri sonlandırır, animasyonları 0.5× ölçeğine alarak cihazı ferahlatır.
- CPU/SoC yonga seti, çekirdek sayısı, termal işlemci sıcaklığı, RAM ve depolama doluluk oranları.

### 8. 📁 Dosya Yöneticisi & Özel Güvenli DNS
- TV dahili depolaması ve bağlı USB bellekler arasında dosya transferi, TV'den PC'ye çekme (pull) ve PC'den TV'ye yükleme (push).
- Reklam ve izleyicileri engellemek için AdGuard DNS, Cloudflare DNS ve Google DNS arasında tek tıkla geçiş.

### 9. 🛡️ Güvenlik Kapısı (Command Gate) & Kesintisiz Kapanış
- Cihazı kilitleyebilecek (`mkfs`, `rm -rf /`, `wipe`) tehlikeli komutları engelleyen yetkilendirme katmanı.
- Kapanışta arka plandaki ADB soket süreçlerini bekletmeyen korumalı akıllı çıkış mekanizması.

---

## 💻 Sistem Gereksinimleri

- **İşletim Sistemi:** Windows 10 veya Windows 11.
- **Mimari:** Hem **64-bit (x64)** hem de **32-bit (x86)** Windows sistemleri tam desteklenir.
- **Python:** Python 3.10 veya üzeri (32-bit veya 64-bit)
- **ADB:** Android platform araçlarından ADB (`adb.exe`). Uygulama `PATH` üzerinde veya kendi klasöründe ADB'yi otomatik tespit eder.

---

## 🚀 Hızlı Başlangıç

### 1. Tek Tıkla Çalıştırma (Önerilen)
Depoyu indirdikten sonra doğrudan **`MiBox_Konsol.bat`** dosyasına çift tıklayın. Sistem mimarinizi (x64 veya x86) otomatik tespit eder, gerekli Qt kütüphanesini hazırlar ve uygulamayı açar.

### 2. Kaynaktan Manuel Çalıştırma

**64-bit Windows Sistemler:**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python mibox.py
```

**32-bit (x86) Windows Sistemler:**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-x86.txt
python mibox.py
```

---

## 📦 Çalıştırılabilir (.exe) Oluşturma

PyInstaller ile tek dosya veya taşınabilir klasör paketi oluşturabilirsiniz:

### GitHub'dan hazır Windows paketi

[Son sürümün Releases sayfasından](https://github.com/maventra-dev/MiBoxKonsol/releases/latest) `MiBoxKonsol-Windows-x64.zip` dosyasını indirin ve tamamını bir klasöre çıkarın. Uygulamayı o klasördeki `MiBoxKonsol.exe` dosyasından başlatın; EXE'yi tek başına başka yere taşımayın. Paket, Windows geçici klasöründe açılma gereksinimini kaldıran taşınabilir klasör biçimindedir. İndirme doğrulaması için aynı sayfadaki `.sha256` dosyasını kullanabilirsiniz.

- **Otomatik Mimarili Derleyici (x64 / x86):**
  ```bat
  build_exe.bat
  ```
- **Özel 32-bit (x86) Derleme:**
  ```bat
  build_exe_x86.bat
  ```
- **Klasör Modu (ONEDIR):**
  ```bat
  build_exe_onedir.bat
  ```

---

## 📁 Proje Dizin Yapısı

```
mibox/
├── .github/                  # GitHub Actions CI ve şablonlar
│   ├── workflows/            # CI ve Release otomasyonları
│   └── ISSUE_TEMPLATE/       # Hata ve istek bildirim şablonları
├── mibox_app/                # Çekirdek Python paketi
│   ├── adb_engine.py         # ADB komut motoru ve soket yönetimi
│   ├── catalog.py            # TV uygulama mağazası kataloğu
│   ├── config.py             # Yapılandırma ve kalıcı ayarlar
│   ├── diagnostics.py        # Çevre ve mimari tanı motoru
│   ├── gate.py               # Güvenlik izin kapısı
│   ├── qt_compat.py          # 64-bit (PySide6) / 32-bit (PyQt5) şimi
│   ├── workers.py            # QThread tabanlı arka plan iş parçacıkları
│   └── ui/                   # Qt arayüz bileşenleri ve sekmeler
│       ├── apps_tab.py       # Uygulama yöneticisi
│       ├── debloat_tab.py    # Debloat ve profil sihirbazı
│       ├── display_panel.py  # Ekran çözünürlüğü ve DPI yöneticisi
│       ├── health_tab.py     # Sağlık ve donanım telemetrisi
│       ├── install_tab.py    # TV App Store ve APK yükleyici
│       ├── logcat_tab.py     # Canlı Logcat konsolu
│       ├── main_window.py    # Ana pencere ve navigasyon
│       ├── network_tab.py    # Canlı Wi-Fi teşhisi ve ping
│       ├── remote_tab.py     # Ergonomik TV kumandası ve canlı ekran
│       ├── settings_tab.py   # Ayarlar ve tanı paneli
│       └── theme.py          # Modern koyu/açık tema motoru
├── build_exe.bat             # Otomatik EXE derleyici
├── build_exe_x86.bat         # 32-bit EXE derleyici
├── MiBox_Konsol.bat          # Hızlı başlatıcı
├── mibox.py                  # Giriş noktası
├── pyproject.toml            # Modern paketleme metaverisi
├── requirements.txt          # 64-bit bağımlılıklar
└── requirements-x86.txt      # 32-bit bağımlılıklar
```

---

## 🌐 English Overview

**MiBox Konsol** is an open-source, full-featured desktop management console and debloating toolkit for **Xiaomi Mi Box, Mi TV Stick**, and all **Android TV** devices via ADB over Wi-Fi or USB.

- **TV App Store:** One-click download & installation of top open-source TV apps (SmartTube, Kodi, VLC, Projectivy Launcher, etc.).
- **Hero TV Remote:** Ergonomic 400px physical remote control with a 170px circular D-pad, live screen mirroring (tap & swipe), and PC keyboard pass-through.
- **Resolution & DPI Manager:** Seamless switching between 4K, 1080p, and 720p with overscan correction and a 15-second safety rollback timer.
- **Live Wi-Fi Diagnostics:** Real-time signal strength (RSSI), link speed (Mbps), frequency band (5GHz/2.4GHz), and gateway ping analysis.
- **Advanced Debloater:** Curated safe/optional/critical lists with one-click presets and automatic snapshot restore.
- **Dual Qt Engine Support:** Full native support for **64-bit Windows (PySide6 / Qt 6)** and **32-bit x86 Windows (PyQt5 / Qt 5)** via `qt_compat`.

---

## 🤝 Katkıda Bulunma

Açık kaynak katkılarınızı memnuniyetle kabul ediyoruz! Lütfen katkı göndermeden önce [CONTRIBUTING.md](CONTRIBUTING.md) rehberini inceleyin.

## 📄 Lisans

Bu proje [MIT Lisansı](LICENSE) altında açık kaynak olarak dağıtılmaktadır.
