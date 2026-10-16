# Değişiklik günlüğü

## [1.5.0] - 2026-10-16

- Taşınabilir Windows paketi, Android Platform-Tools 37.0.1 ADB bileşenlerini ve lisans bildirimini içerir; ayrıca ADB kurmak gerekmez.
- Klasörlü kurulum ve kaldırma, uygulamayla birlikte gelen `platform-tools` dosyalarını kullanıcı dosyalarını koruyarak yönetir.

## [1.4.1] - 2026-10-16

- Bağlantı kurulurken ekran bilgisi sorgusu erken uyarı göstermeden bekler; bağlantı tamamlanınca sorgu otomatik başlar.

## [1.4.0] - 2026-10-16

- Başarısız terminal komutlarının standart çıktı ve hata ayrıntıları korunur; komut ve cihaz bilgileri günlüklerde maskeli kalır. Onaysız görüntü ayarı geri alınırken bağlantı kesme ve genel durdurma geri alma işi tamamlanana kadar bekler.
- Durum kaydı içe aktarma ve okuma işlemleri, aşırı büyük JSON dosyalarına karşı dosya ve paket sayısı sınırlarıyla korunur.
- Katalogdan indirilen APK'nin paket kimliği artık manifestin kök özniteliğinden doğrulanır; manifest okunamazsa kurulum başlamaz.
- Gelişmiş komut kapısı, tırnak ve kaçış karakterleriyle gizlenen `adb_enabled 0` ayarını da reddeder.
- Animasyon ölçekleri uygulanırken kısmi başarısızlıkta önceki değerler geri yüklenir ve geri alma doğrulanır.
- İşlem geçmişi dosyası silinemediğinde hata artık kullanıcıya açıkça bildirilir; zaten bulunmayan dosya başarılı temizlik sayılır.

- Favori paket listesi atomik kaydedilir; kayıt başarısızsa önceki liste korunur ve arayüz hatayı gösterir. Bozuk paket adları favoriye eklenmez.

- 30 günden eski günlük ve Scrcpy operasyon kayıtları açılışta temizlenir; en yeni 20 çökme günlüğü korunur.

- Scrcpy başlatma satırındaki cihaz hedefi ve yerel yollar tanılama günlüğüne yazılmadan önce maskelenir.

- Taşınabilir kurulum boş olmayan yabancı hedefi reddeder, açık uygulamayı güncellemez ve kesilen ilk kurulumu güvenli işaretçiyle sürdürür. Kaldırma komutu uzunluk sınırına takılmaz; yalnızca tanınan uygulama dosyaları ile isteğe bağlı MiBox verilerini temizler, başka dosyaları korur ve hata sonrası yeniden denenebilir. Kısayollar yönlendirilmiş Masaüstü konumunda hedef doğrulamasıyla yönetilir.

- Taşınabilir paket temizliği Scrcpy indirmelerini ve geçici verileri de kaldırır; özel karakterli klasör yollarında güvenle çalışır ve hassas dosya silinemezse yayın paketinin oluşturulmasını durdurur.

- Günlük dosyaları ve dışa aktarılan kayıtlarda cihaz hedefleri, eşleştirme bilgileri, TV'ye gönderilen metinler, terminal ve kurulum konsolunda yazılan komutlar, URL'ler, IP adresleri ve mutlak yerel yollar gizlenir. ADB dosya komutlarının yerel ve cihaz üzerindeki yol argümanları maskelenir. Bağlantı günlükleri hedef kimliğini, dışa aktarma kaydı da tam yerel klasör yolunu içermez.

- TV görüntü ayarları sıfırlanırken veya birden fazla değer uygulanırken hata, iptal ya da bağlantı değişikliği olursa çözünürlük ve DPI adımları geri alınır; başlatma ve okuma hataları görünür şekilde bildirilir. Android’in standart ADB komutu mevcut overscan değerini vermediğinde geri alma bu alanı fabrika değerine sıfırlayabilir; onay penceresi bu sınırlamayı açıklar.

- Sağlık sorguları ve otomatik başlama kısıtlamasında eski cihaz sonuçları bastırılır; işlem kilidi gerçek tamamlanmaya kadar korunur. Hızlandırma onayı cihaz değişiminde geçersiz olur ve adımlar arasında iptal denetlenir. Okunamayan RAM farkı sıfır kazanç olarak sunulmaz; başlatma hataları kontrolleri kilitli bırakmaz.

- Dosya işlemleri tamamlanma sinyaline kadar kilitli kalır; geciken sonuçlar ve açık menü/dosya pencereleri cihaz değişiminde işlem başlatmaz. İndirilen dosyanın bilinen boyutu geçici dosyayla karşılaştırılır; eşleşmezse mevcut yerel dosya korunur. APK yedekleri yayımlanmadan önce ZIP yapısı, boş olmayan Android manifesti ve dosya içeriklerinin CRC bütünlüğü doğrulanır; geçersiz dosya mevcut yedeğin yerine geçmez. Sonuçlar uygulama bazında hata ve durdurma ayrımıyla gösterilir. Geçici indirme dosyaları Git ve dağıtım dışında tutulur.
- Elle bağlantı başlatılırken eski otomatik yoklama geçersiz kılınır; çalışan işlemler aynı hedefe yeniden bağlantıyla çakışmaz. Bağlanma/kesme iş parçacığı başlatılamazsa kontroller açılır ve hata gösterilir. Kapanış sırasında yoklama durur, geç gelen sonuçlar bağlantıyı yeniden açmaz. Başarılı bağlantı yoklama bekleme süresini sıfırlar. Ağ bağlantısı kesme hatası artık başarılı sonuç gibi gösterilmez; USB cihazında mantıksal ayrılma korunur.
- Ağ taraması durdurulunca yeni tarama önceki iş parçacığının bitmesini bekler; sonuç ve hata sonrası kontroller tamamlanmada açılır. Seçili cihaza bağlantı başlatılırken diğer işlemler ve bağlantı geçişi kontrol edilir; bağlantı başlamadan cihaz geçmişi değiştirilmez. Kablosuz eşleştirmede adres/port ve 6 haneli kod doğrulaması, gizli kod girişi, tek işlem kilidi ve bağlantı portu yönlendirmesi eklendi; başarı için ADB onayı aranır, çıktıdaki kod/adres maskelenir. İş parçacığı başlatma hatasında ortak işlem kaydı temizlenir; bağlantı engeli kalmaz.
- Katalog ve yerel APK kurulumlarının çakışması engellendi; kurulum kontrolleri iş parçacığı bitince açılır. Bağlantı değişiminde katalog indirmesi iptal edilir; kurulum başlamadan iptal tekrar kontrol edilir. Durdurma isteği sırasında zaten tamamlanan kurulum doğrulanır ve açıkça bildirilir. İndirilen APK için ZIP dizini ve boş olmayan Android manifesti kontrol edilir; iptal ağ isteğinden önce ve dosya yayımlanmadan önce de denetlenir. Boyutu bilinmeyen indirmelerde belirsiz ilerleme gösterilir; başlatma komutu sonucu ekranın açıldığı iddiasıyla sunulmaz.
- Durum kaydı alma, fark hesaplama ve uygulama işlemleri başlangıç cihazına bağlandı; eski bağlantının sonuçları yeni cihazda gösterilmez. Uygulama onayında kaynak, hedef ve Android kullanıcısı gösterilir; onaylanan kayıt içeriği işlem boyunca korunur. Durum kaydı ve geçmişten geri alma çakışmaları engellendi; geri alma hatasında bekleyen kuyruk serbest bırakılır. Dışa aktarma doğrulanmış içerikle atomik yapılır, başarısız silme bildirilir.
- Uygulamalar sayfasında paket işlemi, APK yedekleme ve tarama çakışmaları engellendi; kontroller işlem gerçekten bitince açılır. Sağ tık menüsü açıldığı cihazı korur, bağlantı geçişinde işlem başlatmaz. Tekli ve toplu işlemler ortak onay yolunu kullanır; paket/koruma listeleri işlem başlangıcında kopyalanır. APK klasörü oluşturma hataları arka plan işleminde bildirilir.
- Ayar yükleme ve yedek içe aktarmaya ortak tür/aralık doğrulaması eklendi; geçersiz cihaz geçmişi açılışı durdurmaz, metin değerleri yanlışlıkla izinleri açmaz. Cihaz geçmişi tekilleştirilir; yeniden bağlanmada uyandırma tercihi kayda dahil edilir. Ayar ve yedek kaydı benzersiz geçici dosya üzerinden yapılır; başarısız kayıt eski dosyayı korur ve kurtarma engelinin nedeni gösterilir.
- Scrcpy indirme/başlatma ilk cihaza bağlandı; iptalden sonra otomatik açılma ve eşzamanlı indirmeler engellendi. Yeniden indirme önbelleği atlar, mevcut kurulumu korur; klasör kısayolu gerçek kurulum yolunu açar. İndirme boyutu, çıkarılmış dosya doğrulaması ve iptal kontrolleri güçlendirildi; süreç kapanışı izlenir, günlük klasörü yazılamasa da başlatma denenir. İndirilen sürüm ve geçici klasörler Git dışında tutulur.
- Uyku zamanlayıcısı gerçek geçen süreye ve başlangıç cihazına bağlandı; kumanda meşgul diye sessizce atlanan komut ve erken başarı bildirimi düzeltildi. Link ve ekran koruyucu işlemleri cihaz bağlamını korur; ADB çıktısındaki açık hata satırları sıfır çıkış kodunda da hata sayılır. Link hataları özel adresi günlüğe eklemez.
- Video kaydı başlatma arka plana taşındı; başlatma ve aktarım sırasında ikinci kayıt engellendi. Kapanış ve bağlantıyı kesme, kayıt hazırlığını/aktarımını bekler. Aktarım sabit cihaz/motor üzerinden geçici dosyaya yapılır, MP4 doğrulandıktan sonra son adına geçirilir; başarısız aktarımda TV dosyası korunur ve yazma izni varsa yerel kurtarma notu bırakılır. Süre sayacı gerçek geçen süreyi kullanır.
- Kumandada yeniden başlatma, cihaz bilgisi, önbellek temizleme ve APK kurma işlemleri seçildikleri cihaza sabitlendi; onay açıkken bağlantı değişirse işlem yeni cihaza yönlendirilmez. Güç menüsünde normal yeniden başlatmanın yanlış modu kullanması ve uyku/uyandırmanın eksik metot çağırması düzeltildi. Hızlandırmada önbellek temizleme parametresi düzeltildi; başarısız adımlar ve ölçülemeyen RAM kazancı başarı gibi gösterilmez.
- Kumandada sessize alma ve ses sorgulama/ayarlama işlemleri başladıkları cihaz bağlamına sabitlendi. Bağlantı geçişinde yeni komutlar engellenir; geçersiz sonuçlar atılır ve işlem kilitleri serbest bırakılır. Ses okunamazsa eski değer gizlenir. Canlı ekran hatasında otomatik yenileme durur; Kaydet yalnızca geçerli görüntü varken etkinleşir.
- Cihaz seçiminde Türkçe durumlar ve izin/bağlantı yönlendirmeleri eklendi. Başarısız ADB sorgusu boş liste gibi gösterilmez; önceki liste korunur. Başlangıç ve elle yenileme aynı sorgu kilidini kullanır.
- Destek paylaşımı için yalnızca uygulama ve ortam sürümlerini içeren önizlenebilir özet eklendi. Dosya yolları, cihaz bilgileri ve günlükler özete eklenmez; ayarlar, hata çubuğu ve hızlı erişimden açılır.
- Dosya işlemlerine yerel ilerleme ve aktarımı durdurma alanı eklendi. İşlem sürerken hedef klasör gezintisi kilitlenir; tamamlanma ve hata sonrasında kontroller yeniden açılır.
- Yerel APK kuyruğunda yalnızca başarısız ve dosyası mevcut paketleri yeniden deneme eklendi; mevcut kurulum onayı ve seçenekleri korunur.
- Ağ ekranında seçili cihazın adresini kopyalama eklendi; bağlantı ve DNS işlemlerine göre düğmeler güncellenir. DNS durumu ölçülmemiş hız veya reklam engelleme sonucu bildirmez; eksik teşhis sonucu “iyi” olarak gösterilmez.
- Logcat’e yerel Türkçe arama, kayıt sayacı, görünen kayıtları kopyalama ve sabit duraklatılmış görünüm eklendi. Seviye renkleri düzeltildi; okuma hataları boş veya başarılı sonuç gibi gösterilmez. Etiket yazımı ve cihaz günlüğü temizliği sırasındaki işlem çakışmaları engellendi.
- Terminalde komut geçmişi giriş alanıyla sınırlandı; taslak korunur ve geçmiş 100 komutla sınırlıdır. Hazır komutlar dar pencerede satırlara yayılır; açık tema çıktı okunabilirliği ve bağlantı değişimi denetimi iyileştirildi.
- Paket temizliğine Türkçe karakterlere duyarlı olmayan arama ve güvenli başlangıç filtrelerine dönüş eklendi; filtre sıfırlama Android kullanıcısını değiştirmez.
- İşlem günlüğüne Türkçe arama, görünen kayıtları kopyalama ve otomatik kaydırmayı kapatma eklendi; arama ve düzey filtreleri birlikte çalışır.
- Ayarlardaki koruma listesine arama ve paket sayısı eklendi; kaldırma yalnızca görünür bir paket seçiliyken etkinleşir. Tercihlerin kaydedilme biçimi ve destek bilgisindeki yerel yollar açıklanır.
- Başlangıç ekranından adres girişi, cihaz bulma, bağlantı yardımı ve kalıcı geçmiş doğrudan açılır; bağlantı işlemi sürerken özet buna göre güncellenir.
- TV kataloğuna filtre sıfırlama ve uygulama ayrıntıları penceresi eklendi; kurulum durumu sorgusu başarısız olduğunda yeniden deneme açıklanır.
- Bağlantı yardımı eklendi; cihaz ve son adres seçenekleri bağlantı alanının altına alındı. Bağlanma ve bağlantıyı kesme sırasında ilerleme durumu açıklanır.
- Dosya listesine öğe ve bilinen boyut özeti, aktarım alanına seçim ve hedef bilgisi eklendi; boş, yükleniyor ve hata durumları açıklanır.
- Geçmişte arama ve seçim bilgisi eklendi; geri alma seçenekleri kaydın uygunluğuna göre etkinleşir. Durum kayıtlarının kapsamı açıklanır.
- Uygulama listesinde Türkçe karakterlere duyarlı olmayan arama, filtre sıfırlama ve seçim temizleme eklendi. Seçim araçları ile paket işlemleri ayrıldı; seyrek işlemler menüye taşındı. İşlem düğmeleri yalnızca bağlantı ve uygun seçim varken etkinleşir.
- Kumanda ve ekran önizlemesi pencere alanına uyarlanır; tuş yazıları için gereken alan korunur. Bağlantısız ekran açıklamaları ve açık tema görünümü düzenlendi.
- Sağlık özetinde gerçek depolama ve bellek ölçümleri açıklanır; eski ölçüm, eksik sonuç ve bağlantısız durum ayrılır. Bağlantı ve bakım işlemlerinden sonra Yenile düğmesinin kapalı kalması giderildi.
- Yeni Başlangıç ekranı; bağlantı durumu, günlük araçlara kısayollar ve bu oturumdaki son işlemleri bir araya getirir. Sol menü günlük kullanım, bakım ve gelişmiş araçlar sırasıyla düzenlendi.
- Hızlı erişim sonuçları tek tıklamayla açılır. Başlangıç için `Ctrl+Home`, ayarlar için `Ctrl+,` kısayolları eklendi; çakışan sayfa kısayolları giderildi.
- Katalogda bağlantı yokken kurulu değil bilgisi gösterilmez; doğrulanmamış durum ve boş arama sonuçları açıklanır. Kurulum sonrası uygulama başlatma arayüzü bekletmeden ve hedef yeniden kontrol edilerek yapılır.
- Sağlık bölümü, seçilen alt paneli gösteren gezinme ve dar pencerelere uyumlu bilgi kartlarıyla düzenlendi. Görüntü ayarları tek yerde toplandı.
- Görüntü ayarı işlemlerinin çakışması ve geri alma sonrasında eski ölçümlerin görünmesi önlendi; geri alma yalnızca değiştirilen alanlara uygulanır.
- Ağ taramalarında eski sonuçların yeni taramaya karışması giderildi. Bulunan cihazlar, tarandıkları port üzerinden bağlanır.
- DNS ve ağ teşhisi sonuçları cihaz bağlantısı değiştiğinde geçersiz sayılır. Dar pencerelerde ağ kontrolleri uygun satırlara yerleşir.
- EXE için `--version --report-file` desteği eklendi; sürüm paketleme akışında dosya içeriğiyle doğrulanır.
- Hata günlükleri eşzamanlı uygulama örneklerinde birbirinin üzerine yazılmaz. Kurulum bağımlılıklarının mimari seçimleri eşitlendi.
- Uygulamalar, debloat, kumanda, dosyalar, kurulum, geçmiş ve terminalde bağlantı değiştikten sonra eski işlem sonuçlarının kullanılması önlendi.
- Kurulum kataloğunda açıklama, kategori ve geliştirici ayrıntıları her pencere boyutunda korunur; uzun metinler satırlara yayılır. Yerel APK seçenekleri iş parçacığı başlamadan alınır; kapanış sırasında sonuç penceresi açılmaz.
- Logcat başlatılırken arayüzü bekleten bağlantı çağrısı kaldırıldı; üst üste yoklamalar ve eski oturum çıktıları engellendi.
- Snapshot iptali tamamlanan değişikliklerin geçmiş kaydını korur. Korunan depolama köklerinin yeniden adlandırılması ve geçersiz Android kullanıcı kimlikleri engellendi.
- Ayar yedeği içe aktarıldığında tema ve seçenekler arayüze yansıtılır; gelişmiş konsolda ayar değiştiren komutlar da onay ister.

## [1.3.1] - 2026-10-15

- Açık ve koyu temalar, sol menü, kartlar ve sekmeler ortak lacivert/mor tasarımla yenilendi.
- Kumandaya geniş tıklama alanlı dairesel yön tuşları ve cihazın gerçek ses kademeleri eklendi.
- Sağlık bölümü üç ana sekmede toplandı; bölüm kısayolları ilgili başlığa yönlendirilir.
- Ağ panelindeki başlık çakışmaları, metin alanlarının kırpılması ve katalog düğmelerinin taşması düzeltildi.
- Uygulama listesinde sağ tık artık kutucukları işaretlemez; menüden APK yedekleme yalnızca ilgili uygulamayı hedefler.
- Tema değiştiğinde katalog ve ağ durumu renkleri güncellenir; ekran görüntüleri kişisel veri içermeyen örneklerle yenilendi.

## [1.3.0] - 2026-10-15

Büyük Modernizasyon, Canlı TV Ekranı & Dokunmatik Kontrol, ADB Shell Terminali ve Yeni Özellikler Sürümü.

- Güvenlik ve kararlılık düzeltmeleri: ADB terminali için komut onayı/engelleme, ağ taraması için IPv4 doğrulaması, DNS sunucu adı denetimi ve URL güvenli aktarımı eklendi.
- Windows GitHub sürümü taşınabilir klasör ZIP'i olarak yayımlanır; tek dosyalı EXE'nin geçici klasör oluştururken açılmama sorunu giderildi.
- Ekran kaydı, bağlantı hedefi değişse bile başladığı TV'den aktarılır; uygulama kapanırken kayıt dosyası korunur ve uzak geçici dosya temizlenir.
- Scrcpy ZIP indirmesine sabit sürüm ve resmî SHA-256 doğrulaması, boyut/kaynak/dosya yolu kontrolleri ve geçici klasörde güvenli açma eklendi.
- Stremio, Jellyfin ve AnExplorer katalog APK bağlantıları resmî güncel Android TV indirmelerine taşındı.

- **Debloat Sekmesi Paket Durumu Senkronizasyon Düzeltmesi**:
  - İlk bağlantı kurulduğunda önceden devre dışı bırakılmış sistem ve kullanıcı paketlerinin "Kurulu" olarak görünmesine yol açan durum aktarımı sorunu düzeltildi; `AppScanWorker` ve `DebloatTab` artık hem kurulu (`present`) hem de devre dışı (`disabled`) paket kümelerini ilk andan itibaren eksiksiz senkronize eder.
- **Kumanda Sekmesi 2 Sütunlu Responsive Düzen**:
  - Kumanda, Canlı TV Ekranı ve Hızlı Başlatıcı alanlarının dar pencerelerde veya DPI ölçekli ekranlarda yatayda taşmasını engelleyen 2 sütunlu, ferah ve modern yerleşim düzeni uygulandı.
- **Canlı TV Ekranı & Dokunmatik Etkileşim (Live Mirroring & Touch)**:
  - Kumanda sekmesine entegre edilen canlı 16:9 TV ekran önizleme alanı (`InteractiveScreenWidget`).
  - **Fareyle Dokunma (Touch/Tap) & Sürükleme (Swipe)**: PC ekranındaki TV görüntüsüne tıklayarak TV'de o koordinata dokunma ve fareyle sürükleyerek kaydırma yapma desteği.
  - **Tek Tıkla Ekran Görüntüsü Kaydetme**: TV ekranını yüksek kalitede anında `.png` olarak bilgisayara kaydetme.
  - **Otomatik Scrcpy Kurulumu ve İndirme Onayı (`scrcpy_manager.py`)**:
    - Bilgisayarda `scrcpy` bulunmadığında kullanıcıdan açık onay istenir; onay verilirse resmî GitHub sürümü arka planda indirilip sürüm numaralı uygulama klasörüne güvenli biçimde kurulur ve canlı ekran başlatılır.
    - Gerçek zamanlı indirme ilerleme penceresi (`QProgressDialog`), iptal desteği ve indirme boyutu/yüzdesi göstergesi eklendi.
    - Scrcpy butonuna sağ tık bağlam menüsü (`QMenu`) eklendi: Hızlı Wi-Fi Modu (4 Mbps), Sessiz Mod (--no-audio), Yeniden İndir/Güncelle ve Scrcpy Klasörünü Aç.
    - ADB sunucu sürümü çakışmalarını önlemek için MiBoxKonsol'un kendi `adb.exe` yolu Scrcpy'ye `ADB` ortam değişkeniyle güvenli biçimde aktarılır.
- **Canlı TV Ekranı Video Kaydedici (MP4 Screen Recording)**:
  - Kumanda sekmesine entegre edilen `🎥 Video Kaydet` butonu ile TV ekranı anlık olarak MP4 formatında kaydedilir.
  - Canlı süre sayacı (`⏹ Durdur (00:15)`) ve kayıt durdurulduğunda videoyu otomatik bilgisayara (`ekran-videolari/`) aktarıp klasörü açma desteği.
- **Canlı TV Ses Seviyesi Kaydırıcısı (Volume Slider & Mute)**:
  - TV sesini 0-100% aralığında fareyle kaydırarak doğrudan ayarlayan yatay ses çubuğu ve tek tıkla `🔇 Sessiz (Mute)` açma/kapama butonu.
- **Tek Tıkla "⚡ Turbo Hızlandır"**:
  - Arka plandaki atıl işlemleri sonlandırıp (`am kill-all`), tüm uygulama önbelleklerini temizleyen (`pm trim-caches`) ve kazanılan RAM miktarını anlık raporlayan hızlı hızlandırma butonu.
- **Sistem Geneli TV Reklam Engelleyici & Özel DNS (Private DNS)**:
  - Ağ sekmesine eklenen Özel DNS yöneticisi ile tek tıkla `AdGuard DNS` (tüm TV'de reklam engelleme), `Cloudflare DNS` (hızlı & güvenli), `Google DNS` veya özel sunucu adresi ayarlama desteği.
  - Sağlık (Performans ve Bakım) sekmesindeki eski DNS ayar grubu kaldırılarak tüm DNS yönetimi Ağ sekmesinde tek ve gelişmiş bir merkezde toplandı.
- **Gelişmiş Güç & Yeniden Başlatma Menüsü**:
  - `⏻ Güç` butonuna sağ tık menüsü ve 3 saniyede TV arayüzünü yeniden başlatan `⚡ Hızlı Soft Reboot (Zygote)` seçeneği.
- **TV Dosya Yöneticisi Sağ Tık Menüsü & Yeniden Adlandırma (Rename)**:
  - Dosyalara ve klasörlere sağ tıklayarak: Bilgisayara İndir (Pull), TV'de Kur (APK), Tam Yolu Kopyala, Yeniden Adlandır (Rename) ve Sil desteği.
- **Güvenlik Denetimli ADB Terminal Sekmesi (`terminal_tab.py`)**:
  - İzin verilen ADB teşhis komutlarını ve konsol çıktısını görüntüler; ayar veya sistem değişiklikleri onay ister.
  - Yukarı/Aşağı ok tuşlarıyla komut geçmişi (`history`) desteği.
  - Hızlı tek tıkla sistem teşhis düğmeleri (CPU, Meminfo bellek, Disk kullanımı, Pil/Güç, ekran boyutu, ağ rotası, Android model, kullanıcı paketleri, Logcat, Wi-Fi).
  - Terminal komut kapısı: yalnızca izin verilen teşhis komutları çalışır; ayar ve sistem değişiklikleri onay ister, tanınmayan ve tehlikeli komutlar engellenir.
  - Tek tıkla terminal çıktısını panoya kopyalama ve temizleme.
  - `AdbResult` nesnesine geriye dönük uyumlu `returncode` özelliği eklendi ve terminal komutlarının `AttributeError` vermeden sorunsuz çalışması sağlandı.
- **Pano Senkronizasyonu (Clipboard Integration)**:
  - Bilgisayar panosunda kopyalanan metin veya linkleri tek tıkla TV'deki giriş alanına yapıştırma (`PC Panosunu Yapıştır`).
- **Modern Arayüz & Tasarım Sistemi (UI/UX 2.0)**:
  - Windows 11 / Fluent esintili modern koyu ve açık renk paleti (modern indigo vurgusu, yumuşak kenarlıklar, `border-radius: 12px`).
  - Bağlantı çubuğunda canlı **Cihaz Bilgi Rozeti** (`📺 Xiaomi Mi Box S (Android 12)`).
  - Sol gezinme menüsünde (Sidebar) yeni logo banner'ı ve daha ferah sekme yerleşimi.
  - Uygulamalar sekmesinde sık kullanılan eylem butonları (Aç, Durdur, APK Yedekle, Devre Dışı, Aktif, Temizle, Kaldır, Geri Yükle) doğrudan araç çubuğunda erişilebilir hale getirildi.
- **Genişletilmiş TV Uygulama Marketi (`catalog.py`)**:
  - **Stremio Android TV**: Torrent ve debrid destekli popüler film/dizi akış platformu.
  - **Jellyfin Android TV**: Açık kaynaklı kişisel medya sunucu TV istemcisi.
  - **AnExplorer TV File Manager**: TV için çift panelli gelişmiş dosya yöneticisi.
  - **Moonlight Game Streaming**: Bilgisayardaki PC oyunlarını 4K 60/120 FPS TV'ye aktaran açık kaynak oyun istemcisi.
- **Uygulamalar Sekmesi Toplu Seçim ve Bağlam Menüsü (`apps_tab.py`)**:
  - Toplu işlemler için `Tümünü Seç` ve `Ters Çevir` butonları eklendi.
  - Sağ tık menüsüne tek tıkla panoya aktarım için `📋 Paket Adını Kopyala` seçeneği eklendi.
- **Terminal Çıktısını TXT Olarak Dışa Aktarma (`terminal_tab.py`)**:
  - Terminal sekmesine `💾 Kaydet` butonu eklendi; tüm teşhis ve shell çıktıları tek tıkla zaman damgalı `.txt` dosyasına aktarılabilir.
- **Windows Sistem Tepsisi Entegrasyonu (System Tray Icon) & Vektörel TV İkonu (`main_window.py`)**:
  - Windows görev çubuğu ve pencere başlığı için modern vektörel TV simgesi (`line_icon('tv')`) eklendi.
  - Windows bildirim alanına (System Tray) yerleşen TV ikonu ve sağ tık hızlı işlem menüsü: `⚡ Turbo Hızlandır (RAM Temizle)`, `🚀 Scrcpy Ekranını Başlat`, `🎥 Video Kaydını Başlat / Bitir`, `Pencereyi Göster / Gizle` ve `Çıkış`.
  - Uygulama kapandığında sistem tepsisinde artık simge kalıntısı bırakmaz (`tray_icon.hide()`).
- **Uygulama Klavye Kısayolları**:
  - `Ctrl+Shift+B`: Anında Turbo Hızlandır (RAM & önbellek temizleme).
  - `Ctrl+Shift+S`: Tek tuşla Scrcpy ekran yansıtmayı başlat.
  - `Ctrl+Shift+R`: TV ekran video kaydını başlat / durdur.
  - `Ctrl+Shift+T`: ADB Terminal sekmesine anında geçiş yap.
  - `Ctrl+Shift+N`: Ağdaki TV'leri otomatik arama sekmesini aç ve tara.
- **PC'den TV'ye Doğrudan Video ve Bağlantı Başlatma (`_open_url_on_tv`)**:
  - Kumanda sekmesindeki metin veya panodaki YouTube/video/web bağlantılarını tek tıkla (`🌐 Link Aç`) TV'deki varsayılan uygulamada (SmartTube, YouTube, Tarayıcı) açma desteği.
- **TV Akıllı Uyku Zamanlayıcısı (Sleep Timer)**:
  - Kumanda sekmesi Sistem & Güç paneline entegre edilen canlı geri sayımlı uyku zamanlayıcısı (15, 30, 45, 60, 90, 120 dakika). Süre dolduğunda TV'yi otomatik uyku moduna alır.
- **TV Ekranını Karartma & Ekran Koruyucu (Ambient Mode)**:
  - Müzik veya podcast dinlerken TV ekranını kapatma (`🌙 Ekranı Kapat`) ve tek tıkla TV ekran koruyucusunu başlatma (`🖼️ Ekran Koruyucu (Ambient)`).
- **APK Yedek Klasörü Entegrasyonu (`_open_apk_dir`)**:
  - Uygulamalar sekmesine `📁 Yedekler` butonu eklendi; yedekleme tamamlandığında doğrudan klasörü açma seçeneği sunulur.
- **Üst Çubuktan Tek Tıkla Ağda TV Arama (`_jump_to_network_scan`)**:
  - Üst bağlantı çubuğuna eklenen `🔍 Ağda Ara` butonu ile yerel ağdaki (Wi-Fi) açık ADB portlu TV cihazları tek tıkla aranır.
- **Yeni Debloat Profili: Oyun & Emülatör Modu (`gaming_mode`)**:
  - Arka plandaki tüm telemetri, reklam, yazdırma ve medya artıklarını dondurarak işlemci ve RAM'i oyunlara ve emülatörlere tahsis eden özel profil.

## [1.2.3] - 2026-10-14

- Windows EXE'nin açılışta `No module named 'email'` hatası vermesine neden olan PyInstaller dışlama ayarı düzeltildi.
- Yayın derlemesi artık paketlenmiş EXE'yi başlatıp selftest işaretçisini doğruluyor.

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
