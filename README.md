# MiBox Konsol

Android TV cihazlarını ADB üzerinden yönetmek için Windows masaüstü uygulaması.
Uygulama Python ve PySide6 ile geliştirilmiştir.

**Sürüm: 1.0.0**

## Ekran görüntüleri

<table>
  <tr>
    <td width="50%" align="center">
      <img src="docs/screenshots/apps.jpg" alt="Uygulamalar sayfası" width="100%"><br>
      <strong>Uygulamalar</strong>
    </td>
    <td width="50%" align="center">
      <img src="docs/screenshots/remote.jpg" alt="Kumanda sayfası" width="100%"><br>
      <strong>Kumanda</strong>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="docs/screenshots/debloat.jpg" alt="Debloat sayfası" width="100%"><br>
      <strong>Debloat</strong>
    </td>
    <td width="50%" align="center">
      <img src="docs/screenshots/health.jpg" alt="Sağlık sayfası" width="100%"><br>
      <strong>Cihaz sağlığı</strong>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="docs/screenshots/files.jpg" alt="Dosyalar sayfası" width="100%"><br>
      <strong>Dosyalar</strong>
    </td>
    <td width="50%" align="center">
      <img src="docs/screenshots/install.jpg" alt="Kurulum sayfası" width="100%"><br>
      <strong>APK kurulumu</strong>
    </td>
  </tr>
</table>

## Özellikler

- Yüklü uygulamaları görüntüleme, başlatma, yükleme ve kaldırma
- Paketleri kategorilere göre inceleme ve seçili paketleri yönetme
- Kumanda tuşları, metin gönderme ve ekran görüntüsü alma
- Cihaz bilgileri, sağlık durumu, süreçler ve günlük kayıtlarını inceleme
- Dosya aktarımı, ağdaki ADB cihazlarını tarama ve kurulum kuyruğu
- İşlem geçmişi, geri alma ve cihaz anlık görüntüleri

## Gereksinimler

- Windows 10 veya 11
- Python 3.10 veya üzeri
- Android platform araçlarından ADB (`adb.exe`)
- Android TV'de geliştirici seçenekleri ve ADB hata ayıklaması açık olmalıdır

Uygulama ADB'yi `PATH` üzerinden veya çalıştırılabilir dosyanın yanından bulur.

## Kaynaktan çalıştırma

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python mibox.py
```

İlk açılışta cihazın IP adresini ve ADB bağlantı noktasını girip **Bağlan**'ı
seçin. Kablosuz hata ayıklama eşleştirmesi gerekiyorsa Android TV'nin
geliştirici seçeneklerinden eşleştirmeyi tamamlayın.

## Windows paketi oluşturma

```bat
build_exe.bat
```

Klasör tabanlı paket ve masaüstü kısayolu için:

```bat
build_exe_onedir.bat
kur_onedir.bat
```

## Proje yapısı

- `mibox_app/` — uygulama kaynak kodu
- `tools/` — paketleme yardımcıları
- `MiBoxKonsol.spec` — PyInstaller yapılandırması

Yerel ayarlar, günlükler, anlık görüntüler ve derleme çıktıları Git dışında
tutulur.

## Lisans

Bu proje MIT Lisansı altında sunulur. Ayrıntılar için [`LICENSE`](LICENSE)
dosyasına bakın.
