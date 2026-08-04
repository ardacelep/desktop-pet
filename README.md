# Desktop Pet

Masaüstünde dolaşan, şeffaf arka planlı, her zaman üstte duran bir piksel-sanat pet uygulaması. Electron ile yazıldı; macOS ve Windows'ta çalışır.

Pet kendi kendine ekranın altında gezinir, kenara çarpınca döner, sürüklenebilir, tıklayınca konuşur. Karakterler veriyle tanımlanır — yeni bir karakter eklemek için kod yazmak gerekmez.

## Özellikler

- Çerçevesiz, şeffaf, her zaman üstte pencere (macOS'ta `floating` seviyesi, tüm Space'lerde görünür)
- Sprite sheet tabanlı canvas animasyon motoru — piksel sanatı bulanıklaşmadan çizilir
- Durum makinesi: `IDLE → WALKING → IDLE`, `DRAGGING`, `REACTING`
- Rastgele gezinme ve ekran kenarında yön değiştirme
- Sürükle-bırak; bırakıldığı monitörün çalışma alanına (dock/taskbar üstüne) oturur
- Tıklayınca konuşma balonu, karaktere özel cümle repertuarından
- Sağ tık menüsü + sistem tepsisi ikonu
- Son konum ve aktif karakter diske kaydedilir

## Gereksinimler

- Node.js 18+
- npm

## Kurulum ve çalıştırma

```bash
npm install
```

```bash
npm start
```

## Proje yapısı

```
pet/
├── main.js                 # Electron ana süreç: pencere, tray, menü, IPC, kalıcılık
├── preload.js              # contextBridge köprüsü (contextIsolation açık)
├── renderer/
│   ├── index.html
│   ├── pet.css
│   ├── sprite-animator.js  # Sprite sheet → canvas, dt tabanlı kare ilerletme, flip
│   ├── speech-bubble.js    # Konuşma balonu UI'ı
│   └── pet.js              # Durum makinesi, davranış, etkileşimler
├── characters/
│   ├── characters.json     # Sadece varsayılan karakter (nadiren değişir)
│   └── karakter1/
│       ├── idle_spritesheet.png
│       ├── walk_right_spritesheet.png
│       └── meta.json
├── tools/
│   ├── check-characters.js       # Karakter doğrulayıcı (npm run check)
│   ├── pixelart_extract.py       # AI çıktısını gerçek çözünürlüğe indirir
│   ├── pack_sheet.py             # Kareleri hizalayıp sprite sheet yapar
│   ├── test_pixelart_extract.py  # Çıkarıcının regresyon testleri
│   └── test_pack_sheet.py        # Hizalayıcının regresyon testleri
├── assets/                 # Ham/orijinal sprite dosyaları (uygulama bunları okumaz)
└── DESKTOP_PET_PLAN.md     # Mimari plan notları
```

Ana süreç yalnızca pencereyi konumlandırır; pet'in nerede olduğu ve ne yaptığı renderer'daki `Pet` sınıfında tutulur, konum değişiklikleri `pet:move` IPC mesajıyla ana sürece iletilir.

## Yeni karakter ekleme

**Karakterler klasörden otomatik keşfedilir** — `characters/` altında `meta.json` içeren her klasör bir karakterdir. Ortak bir kayıt dosyasına dokunmanız gerekmez, yani iki kişi aynı anda karakter eklerken çakışma yaşamaz.

1. `characters/<karakter-adi>/` klasörü aç, sprite sheet'leri içine koy.
   Sheet'ler **yatay** olmalı: kareler yan yana, her kare kare (kxk) ve arka plan şeffaf.
2. Aynı klasöre bir `meta.json` yaz:

```json
{
  "displayName": "Arkadaş 2",
  "nativeFrameSize": 88,
  "displayHeight": 88,

  "idle":       { "file": "idle_spritesheet.png",       "frameSize": 88, "frameCount": 4, "frameDuration": 500 },
  "walk_right": { "file": "walk_right_spritesheet.png", "frameSize": 88, "frameCount": 7, "frameDuration": 120 },
  "walk_left":  { "file": "walk_right_spritesheet.png", "frameSize": 88, "frameCount": 7, "frameDuration": 120, "flip": true },

  "walkSpeed": 42,
  "lines": ["Selam!", "Bir mola versene."]
}
```

3. Doğrula:

```bash
npm run check
```

Karakter, sağ tık menüsündeki **Karakter Değiştir** listesinde otomatik görünür.

### Alanların anlamı

| Alan | Açıklama |
| --- | --- |
| `displayName` | Menüde görünen ad. Yoksa klasör adı kullanılır |
| `nativeFrameSize` | Sprite dosyasındaki kare boyutu (piksel) |
| `displayHeight` | Ekranda görünecek boy. Farklı çözünürlüklü karakterleri aynı boyda göstermek için |
| `flip` | `true` ise kare çizilirken yatay aynalanır — sola yürüyüş için ayrı dosya tutmaya gerek yok |
| `frameDuration` | Kare başına milisaniye |
| `walkSpeed` | Yürüme hızı, saniyede piksel |
| `lines` | Tıklandığında rastgele seçilen cümleler |

`displayHeight` ile `nativeFrameSize` eşit olduğunda piksel sanatı en net görünür; ara ölçekler (ör. 88 → 80) bulanıklaştırır. Ölçek gerekiyorsa tam katlar (176, 44) tercih edin.

### Kare boyutu neden kare?

Motor kareyi kare varsayıyor: [sprite-animator.js](renderer/sprite-animator.js) canvas'ı `frameSize × frameSize` yapıp sheet'ten aynı boyutta dilim alıyor. Karakteriniz 40×95 çıktıysa onu **germeden**, şeffaf pikselle 96×96'ya tamamlayın:

- **yatayda ortalayın** — sola yürüyüş `flip` ile üretiliyor ve aynalama canvas'ın ortasına göre yapılıyor; karakter kutuda ortalı değilse her dönüşte yana zıplar
- **ayakları alt kenara oturtun** — yoksa havada durur

Karakterler arasında ortak bir boyut **zorlamayın**. Native çözünürlük karakterden karaktere değişir (ölçülen bir sette 84, 85, 95, 156) ve hepsini aynı boya getirmek 156 → 95 gibi ondalıklı bir ölçek gerektirir; bu, piksel sanatının bozulmadan sağ çıkamayacağı tek işlemdir. Boy farkı rahatsız ediyorsa doğru yer üretim aşamasıdır: karakteri aynı ızgara yoğunluğunda yeniden ürettirin.

Karakterin **sağa bakıyor** olması gerekir — sola yürüyüş `flip` ile üretilir. Sola bakan bir sheet çizdiyseniz `walk_right`'a `"flip": true`, `walk_left`'e `false` verin.

`characters/characters.json` yalnızca ilk kurulumda hangi karakterle başlanacağını tutar; yeni karakter eklerken bu dosyaya dokunmayın.

## AI ile üretilen sprite'ları hazırlama

Gemini gibi modellerden gelen "pixel art" görselleri doğrudan kullanılamaz: dosya 1024×1024 gelir ama içindeki gerçek pixel art örneğin 100×100'dür (her sanal piksel ~10.24 gerçek piksellik bir blok), üstelik şeffaflık gerçek değildir — arka plana dama deseni **çizilmiştir**.

[tools/pixelart_extract.py](tools/pixelart_extract.py) bunu düzeltir: ızgarayı ondalıklı hassasiyetle tespit edip görseli gerçek çözünürlüğüne indirir ve dama desenini gerçek alfa kanalına çevirir.

```bash
python3 tools/pixelart_extract.py gemini_ciktisi.png characters/kedi/idle_spritesheet.png
```

Gözle kontrol için büyütülmüş bir önizleme:

```bash
python3 tools/pixelart_extract.py girdi.png cikti.png --preview onizleme.png --preview-scale 8
```

Faydalı seçenekler:

| Seçenek | Ne işe yarar |
| --- | --- |
| `--merge-colors N` | AI render'ındaki piksel gürültüsünü baskın tonlara yaslar. Varsayılan kapalı; güvenli değeri `--verify` söyler |
| `--bg-tol N` | Dama rengi toleransı. Varsayılan olarak görselin kenarından **ölçülerek** seçilir; arka plan kaldıysa artırın, karakterin açık renkleri yeniyorsa azaltın |
| `--no-crop` | Kenar boşluklarını kırpmaz. **Aynı karakterin birden fazla karesini çıkarırken şart** — aksi halde her kare kendi içeriğine göre kırpılır ve animasyonda karakter zıplar |
| `--no-cleanup` | Leke/delik temizliğini atlar — temizlik gerçek bir detayı yerse |
| `--fill-gaps N` | Silüetin içinde kapalı kalmış, dama renginde, en fazla N piksellik adacıkları şeffaf yapar. Varsayılan kapalı — [aşağıya bakın](#kolla-gövde-arasındaki-kapalı-boşluklar) |
| `--verify` | Çıkarımın kayıpsızlığını ölçüp raporlar (aşağıya bakın) |
| `--debug-dir ./debug` | Ara adımları yazar; `1_izgara.png` tespit edilen ızgarayı orijinalin üstüne çizer, tespit yanlışsa hemen görülür |

### Animasyon karelerini sprite sheet'e dizme

Bir yürüyüşün karelerini Gemini'ye tek tek ürettirip her birini yukarıdaki gibi çıkardığınızda kareler birbirine göre **kayık** olur: her kare ayrı bir üretim olduğu için karakter tuval içinde farklı yerde durur. Yan yana dizilirse karakter her karede başka yerde görünür ve animasyon **titrer**.

[tools/pack_sheet.py](tools/pack_sheet.py) kareleri içeriğe göre hizalayıp ortak bir kare kutuya yerleştirir:

```bash
python3 tools/pack_sheet.py kare1.png kare2.png kare3.png -o characters/kedi/walk_right_spritesheet.png --gif onizleme.gif
```

Hizalama iki eksende ayrı çalışır:

- **dikeyde ayak çizgisine** — en alt opak satır sabitlenir, karakter yere basar
- **yatayda referans kareyle örtüşmeyi en büyüten kaymayı arayarak** — sınır kutusunun ortasını almak yetmez, çünkü kolunu uzatan karede merkez kayar ve titreme üretir. Örtüşme araması gövde ve başı çakıştırır (piksellerin çoğunluğu oradadır)

Çıktıda her kare için referansla örtüşme yüzdesi raporlanır; düşük çıkan kare işaretlenir. `--gif` ile üretilen önizlemede titreme varsa gözle görürsünüz.

**Ölçekleme asla yapılmaz.** Kareler yalnızca kaydırılır ve şeffaf piksel eklenir. Karelerin native çözünürlüğü farklıysa araç uyarır ama küçültmez — düzeltme yeri üretim aşamasıdır.

Girdilerin kırpılmış olup olmaması fark etmez; hizalama zaten içeriğe göre yapılır. Kareleri elle dizecekseniz `--no-crop` gerekir, `pack_sheet.py` kullanıyorsanız gerekmez.

Sonunda yapıştırmaya hazır `meta.json` bloğu basılır:

```
meta.json icin:
  "walk_right": {"file": "walk_right_spritesheet.png", "frameSize": 95, "frameCount": 7, "frameDuration": 120}
  "nativeFrameSize": 95,
  "displayHeight": 95
```

### Kayıpsızlığı doğrulama

Sonuca güvenmek yerine ölçebilirsiniz:

```bash
python3 tools/pixelart_extract.py girdi.png cikti.png --verify
```

Dört şey raporlar: ızgara gerçekten oturuyor mu (hücre içi varyans, tam sayıya yuvarlanmış ızgarayla karşılaştırmalı), her hücreye tek bir renk atanabiliyor mu, bir hücrede *gerçekten* farklı iki renk çarpışıyor mu, ve kaynağın gürültü tabanı ne kadar.

Üçüncü madde gerçek detay kaybının tek olası kaynağıdır; 0 çıkması çıkarımın kaynağın izin verdiği ölçüde birebir olduğu anlamına gelir.

### Kolla gövde arasındaki kapalı boşluklar

AI bazen kolla gövde arasında 1-3 piksellik bir boşluk bırakır. Boşluk dama renginde, ama **konturun içinde tamamen kapalı** kaldığı için kenardan gelen flood-fill oraya ulaşamaz; ekranda gri bir leke olarak kalır. Boşluk dama karesinden küçük olduğu için içinde desen de görünmez, yalnızca tek bir ton vardır.

`--fill-gaps N` bunu açar ama **varsayılan olarak kapalı, çünkü güvenli bir şekilde otomatikleştirilemiyor.** Ölçülen karakterlerde göz akı `254-255`, damanın açık tonu `253` — aynı renk, ve ikisi de silüetin içinde kapalı birer adacık. Denenen ve yetersiz kalan ayırt ediciler:

| Ölçüt | Neden yetmiyor |
| --- | --- |
| Dama kafesinin geometrisi | Dama, native piksel ızgarasına oturmuyor — kaynak çözünürlükte çizildiği için periyodu hücre boyutunun tam katı değil. Ölçülen uyum %52, yani şansa eşit |
| Adacık boyutu | Ölçülen bir görselde gerçek boşluk 4 piksel, göz akının bir parçası da 4 piksel |
| Komşuların koyuluğu | Boşlukların bir kısmı tene komşu, konturla çevrelenmiş değil |

Uygulanan tek ek güvence: adacığın **kendi rengine yakın bir opak komşusu varsa** dokunulmuyor — o zaman daha büyük bir açık renkli parçanın ucudur (ayakkabının beyaz tabanı gibi), gerçek bir boşluk değil.

Doğru kullanım, önce flag'siz sonra flag'li çalıştırıp ikisini karşılaştırmak:

```bash
python3 tools/pixelart_extract.py girdi.png cikti.png --fill-gaps 4 --preview onizleme.png
```

Silinen her adacık koordinatıyla raporlanır. Ölçülen sonuç: bir karakterde tam olarak istenen iki boşluk açıldı ve başka hiçbir şey bozulmadı; iki karakterde ise göz akının bir pikseli de silindi. Yani bu, karakter başına gözle onaylanacak bir adım.

Boşluk bırakmaması için Gemini'ye talimat vermek işe yarar ama tek başına yetmez: model her seferinde uymaz ve farklı pozlarda (kol gövdeden uzakta) yeni boşluklar çıkar. İyi haber şu ki **büyük boşluk kolay** — dama deseni görünür hale geldiği ve dışarıyla bağlantısı olduğu için script onu zaten temizler. Zor olan tam olarak bu 1-3 piksellik kapalı cep.

### Kaynak gürültüsü ve palet

Çıkarım hiçbir rengi **uydurmaz**: her çıktı pikselinin rengi, kaynakta o konumda aynen bulunan bir renktir (ortalama değil, en sık görülen renk alınır). Yani hücreler arası tüm varyasyon varsayılan olarak korunur — hiçbir şey yumuşatılmaz.

Dama deseninin tonu da sabit varsayılmaz. Ölçülen bir Gemini çıktısında koyu ton görselin ortasındaki bir bantta `231`'den `203`'e inip tekrar yükseliyordu; iki tonu global kabul eden bir eşik o bandı opak bırakıyor, bant karakterin koluna değdiği için "kopuk parça" temizliğine de takılmıyordu. Bu yüzden tonlar her satır ve her sütun için kenar şeridinden ayrı örneklenir. `--verbose` kayma varsa bunu yazar:

```
ton kaymasi: goruntu boyunca en fazla 28 birim — satir/sutun basina yerel ton kullaniliyor
```

Ama AI render'ları düz olması gereken alanlarda bile ±1 seviyesinde rastgele gürültü üretiyor. Bu gözle görülmez, ancak paleti şişirir (örnek görselde 2300 piksele karşı 716 renk). Kasıtlı gölge basamakları bunun çok üstünde olduğu için ikisi ayrıştırılabilir.

`--verify` bunu ölçer ve güvenli bir tolerans önerir — öneri, ölçülen gürültü tavanının iki katıdır, yani yapısı gereği kasıtlı tonal adımlara dokunamaz:

```
4) Kaynak gurultusu: palet 716 renk
   duz bolgelerde sapma: ort 0.54, %95'i <= 2.0  (249 hucre uzerinden)
   -> --merge-colors 4 kullanilsaydi: palet 716 -> 121, piksellerin %34'i hic
      degismezdi, en buyuk kayma 4/255
```

2048×2048 bir görsel ~10-20 saniye sürer (ızgara araması ölçüm yapıyor), 1024×1024 ise ~2 saniye.

Bağımlılık sadece `numpy` ve `pillow`:

```bash
pip3 install numpy pillow
```

Değişiklik yaparsanız regresyon testlerini çalıştırın:

```bash
python3 tools/test_pixelart_extract.py && python3 tools/test_pack_sheet.py
```

## Birlikte geliştirme

Karakter eklemek kod değiştirmeyi gerektirmediği için art ve kod tarafı birbirine karışmaz. Ayrıntılar ve dal/PR akışı için [CONTRIBUTING.md](CONTRIBUTING.md).

## Ayarların saklandığı yer

`electron-store` kullanılır (`activeCharacterId`, `position`):

- macOS: `~/Library/Application Support/desktop-pet/config.json`
- Windows: `%APPDATA%\desktop-pet\config.json`

Pet ekranda kaybolursa bu dosyayı silmek ya da sağ tık → **Ortaya Getir** konumu sıfırlar.

## Paketleme

```bash
npm run dist:mac
```

```bash
npm run dist:win
```

Çıktılar `dist/` altına yazılır. Her platformu kendi işletim sisteminde build etmek en güvenilir yol — macOS'tan Windows build'i almak code signing tarafında sorun çıkarabilir. Cross-platform build gerekiyorsa GitHub Actions gibi bir CI daha uygun.

`build/tray.png` (16×16, şeffaf) eklerseniz tepsi ikonu olarak kullanılır; yoksa macOS menü çubuğunda 🐾 emojisi gösterilir.

## Bilinen sınırlar

- Pencere 200×180; pet'in etrafındaki şeffaf alan altındaki uygulamalara giden tıklamaları yutar. `setIgnoreMouseEvents(true, { forward: true })` bunu çözer ama sürükleme mantığını karmaşıklaştırdığı için şimdilik kullanılmadı.
- Pet yalnızca X ekseninde hareket eder; zıplama/düşme gibi dikey fizik yok.
- Çoklu monitör: sürükleyip bıraktığında bulunduğu monitöre uyum sağlar, ama kendi başına yürürken monitörler arası geçmez.

## Yol haritası

- [ ] Şeffaf alanlarda tıklama geçirgenliği
- [ ] Dikey fizik (zıplama, kenardan düşme)
- [ ] Yürürken monitörler arası geçiş
- [ ] Ayarlar penceresi (hız, boyut, konuşma sıklığı)
- [ ] Aynı anda birden fazla pet (`createPetWindow` zaten çoğaltmaya uygun)
