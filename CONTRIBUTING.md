# Katkıda Bulunma Rehberi (Contributing Guide)

MiBox Konsol projesine katkıda bulunmak istediğiniz için teşekkürler! Açık kaynak topluluğunun desteği bu projeyi daha güvenli, kararlı ve yetenekli hale getirmektedir.

---

## 🛠️ Geliştirme Ortamının Kurulması

### 1. Depoyu Klonlayın
```bash
git clone https://github.com/maventra-dev/MiBoxKonsol.git
cd MiBoxKonsol
```

### 2. Sanal Ortam Oluşturun ve Bağımlılıkları Yükleyin
**Windows (64-bit):**
```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**Windows (32-bit x86):**
```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-x86.txt
```

### 3. Uygulamayı Çalıştırma
```cmd
python mibox.py
```
Veya doğrudan çift tıklayarak:
```cmd
MiBox_Konsol.bat
```

---

## 🪟 Başlatma Kontrolü

Pencere ve olay döngüsünün başlatılabildiğini denetleyin:
```cmd
python mibox.py --selftest
```

---

## 🏗️ EXE Derleme

- **64-bit Standalone EXE:** `build_exe.bat`
- **32-bit (x86) EXE:** `build_exe_x86.bat`
- **Klasör Modu (ONEDIR):** `build_exe_onedir.bat`

---

## 📜 Kodlama İlkeleri

- **Geriye Dönük Uyumluluk:** 64-bit (PySide6) ve 32-bit (PyQt5) uyumluluğu her zaman korunmalıdır (`mibox_app/qt_compat.py`).
- **İş Parçacığı (Worker) Disiplini:** Tüm ADB ve ağ işlemleri UI thread'ini bloke etmemek için `BaseWorker` alt sınıflarında çalışmalı ve iptal (`cancel_check`) denetimini desteklemelidir.
- **Güvenlik Kapısı (`gate.py`):** Cihazda çalıştırılan komutlar yetkilendirilmiş ve whitelist kurallarına uygun olmalıdır.
- **Görsel Bütünlük:** Qt temalarında `QGroupBox` ve buton stilleri bozulmamalı, taşma olmadan temiz bir kullanıcı deneyimi sunulmalıdır.
