<div align="center">

# MiBox Konsol

### Android TV cihazlarınızı bilgisayarınızdan yönetin.

Mi Box, Mi TV Stick ve Android TV için ADB tabanlı masaüstü yönetim merkezi. Kumanda, uygulama ve APK yönetimi, cihaz sağlığı, ağ araçları ve güvenli bakım tek bir arayüzde.

[⬇️ Son sürümü indir](https://github.com/maventra-dev/MiBoxKonsol/releases/latest) · [🐞 Hata bildir](https://github.com/maventra-dev/MiBoxKonsol/issues/new) · [✨ Özellik öner](https://github.com/maventra-dev/MiBoxKonsol/issues/new)

<br>

[![Latest Release](https://img.shields.io/github/v/release/maventra-dev/MiBoxKonsol?display_name=tag&sort=semver)](https://github.com/maventra-dev/MiBoxKonsol/releases/latest)
[![Build](https://img.shields.io/github/actions/workflow/status/maventra-dev/MiBoxKonsol/build-release.yml?branch=master&label=Windows%20build)](https://github.com/maventra-dev/MiBoxKonsol/actions/workflows/build-release.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-8b7cf6.svg)](LICENSE)
[![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-2563eb.svg)](https://www.microsoft.com/windows)

</div>

## Ekran görüntüleri

Arayüz görselleri örnek içerik kullanır; gerçek cihaz adresi veya kişisel dosya yolu içermez.

<table>
  <tr>
    <td width="50%" align="center">
      <a href="docs/screenshots/remote.jpg"><img src="docs/screenshots/remote.jpg" alt="MiBox Konsol uzaktan kumanda ve ekran kontrolü" width="100%"></a><br>
      <strong>Kumanda ve canlı ekran kontrolü</strong>
    </td>
    <td width="50%" align="center">
      <a href="docs/screenshots/health.jpg"><img src="docs/screenshots/health.jpg" alt="Android TV sağlık ve cihaz bilgileri" width="100%"></a><br>
      <strong>Cihaz sağlığı ve bakım</strong>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <a href="docs/screenshots/apps.jpg"><img src="docs/screenshots/apps.jpg" alt="Android TV uygulama ve paket yöneticisi" width="100%"></a><br>
      <strong>Uygulama ve paket yönetimi</strong>
    </td>
    <td width="50%" align="center">
      <a href="docs/screenshots/install.jpg"><img src="docs/screenshots/install.jpg" alt="Android TV uygulama kataloğu ve APK kurulumu" width="100%"></a><br>
      <strong>TV uygulama kataloğu ve APK kurulumu</strong>
    </td>
  </tr>
</table>

## Neler yapabilirsiniz?

| Alan | Araçlar |
| --- | --- |
| **Kumanda** | Yön tuşları, ses ve medya kontrolleri, metin gönderme, ekran görüntüsü ve canlı ekran etkileşimi |
| **Uygulamalar** | Kurulu paketleri inceleme, açma, devre dışı bırakma veya kaldırma; APK yedekleme |
| **Kurulum** | Android TV uygulama kataloğu, yerel APK ve bölünmüş APK kurulumu |
| **Sağlık** | Cihaz özeti, donanım ölçümleri, ekran yapılandırması ve arka plan izinleri |
| **Ağ** | ADB cihaz keşfi, kablosuz eşleştirme, Wi-Fi teşhisi ve DNS ayarları |
| **Bakım** | Paket profilleri, durum kaydı ve geri yükleme, dosya aktarımı, Logcat ve gelişmiş terminal |

## İndirme ve kurulum

1. [Son sürüm sayfasından](https://github.com/maventra-dev/MiBoxKonsol/releases/latest) `MiBoxKonsol-Windows-x64.zip` dosyasını indirin.
2. ZIP dosyasının **tüm içeriğini** bir klasöre çıkarın.
3. Klasördeki `MiBoxKonsol.exe` dosyasını çalıştırın. EXE'yi ZIP içinden açmayın veya tek başına başka klasöre taşımayın.
4. TV'de **Geliştirici seçenekleri** ve **USB hata ayıklama** özelliğini açın. Bilgisayar ile TV aynı yerel ağdaysa uygulamadaki cihaz bulma veya kablosuz eşleştirme araçlarını kullanın.

İndirmenin bütünlüğünü kontrol etmek için aynı release sayfasındaki `.sha256` dosyasını kullanabilirsiniz. USB ile bağlanacaksanız TV'yi USB hata ayıklama açıkken bilgisayara bağlayıp TV ekranındaki izin isteğini onaylayın.

## Gereksinimler

- Windows 10 veya Windows 11, 64 bit.
- TV'de ADB hata ayıklama izni. USB veya aynı yerel ağ üzerinden kablosuz bağlantı.
- Kaynaktan çalıştırma için Python 3.10 veya üzeri ve Android Platform Tools (`adb`).

## Kaynaktan çalıştırma

```powershell
git clone https://github.com/maventra-dev/MiBoxKonsol.git
cd MiBoxKonsol
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python mibox.py
```

## Gizlilik ve güvenli kullanım

- Cihaz yönetimi bilgisayarınız ile TV arasındaki ADB bağlantısı üzerinden yapılır. Uygulama telemetri veya reklam içermez.
- Ayarlar, işlem geçmişi, günlükler, APK yedekleri, terminal çıktıları ve ekran görüntüleri bilgisayarınızda tutulur. Dışa aktarılan geçmiş/yedekler ve tam tanılama raporu cihaz adresi, komut çıktısı veya yerel dosya yolu içerebilir; paylaşmadan önce gözden geçirin. **Ayarlar → Paylaşım özeti** kişisel yolları ve cihaz bilgilerini içermez.
- Katalog uygulamaları üçüncü taraflarca yayımlanır. Kurulum öncesinde yayıncıyı ve kaynağı kontrol edin; uygulama APK yayıncı imzasını veya SHA-256 özetini doğrulamaz.
- Katalog indirmeleri ve Scrcpy kurulumu için gerekli dosyalar, uygulama içindeki kaynak bağlantılarından internet üzerinden alınır.
- Paket kaldırma ve sistem ayarı değişiklikleri TV'nin işleyişini etkileyebilir. Ne yaptığınızı bilmediğiniz sistem paketlerini kaldırmayın; işlem öncesindeki açıklamaları ve onayları dikkatle okuyun.

## Katkı ve lisans

Hata bildirmek veya geliştirme önermek için [GitHub Issues](https://github.com/maventra-dev/MiBoxKonsol/issues) sayfasını kullanın. Katkı göndermeden önce [CONTRIBUTING.md](CONTRIBUTING.md) dosyasını inceleyin.

MiBox Konsol, [MIT Lisansı](LICENSE) ile yayımlanır.

<details>
<summary>English overview</summary>

MiBox Konsol is an open-source Windows desktop manager for Xiaomi Mi Box, Mi TV Stick, and Android TV devices. It provides an ADB remote, app and APK management, device health and display tools, network diagnostics, file transfer, and maintenance features.

Download the latest portable Windows x64 ZIP from [GitHub Releases](https://github.com/maventra-dev/MiBoxKonsol/releases/latest), extract the complete archive, and run `MiBoxKonsol.exe`. Enable ADB debugging on your TV and approve the computer connection. The project is licensed under MIT.

</details>
