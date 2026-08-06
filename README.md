# Desktop Pet

Masaüstünde dolaşan, şeffaf arka planlı, her zaman üstte duran bir piksel-sanat pet uygulaması. Electron ile yazıldı; macOS ve Windows'ta çalışır.

Pet kendi kendine ekranın altında gezinir, kenara çarpınca döner, sürüklenebilir, tıklayınca konuşur. Karakterler veriyle tanımlanır — yeni bir karakter eklemek için kod yazmak gerekmez.

## Özellikler

- Çerçevesiz, şeffaf, her zaman üstte pencere (macOS'ta `floating` seviyesi, tüm Space'lerde görünür)
- Sprite sheet tabanlı canvas animasyon motoru — piksel sanatı bulanıklaşmadan çizilir
- Durum makinesi: `IDLE → WALKING → IDLE`, `DRAGGING`, `REACTING`
- Rastgele gezinme ve ekran kenarında yön değiştirme
- **Şeffaf alanlar tıklama geçirgen** — pet'in üstünde olmayan tıklamalar altındaki uygulamaya gider
- Sürükle-bırak; bırakıldığı monitörün çalışma alanına (dock/taskbar üstüne) oturur
- Tıklayınca konuşma balonu, karaktere özel cümle repertuarından
- Sağ tık menüsü + sistem tepsisi ikonu — karakter ve **boyut** değiştirme
- Son konum, aktif karakter ve seçilen boyut diske kaydedilir

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
│   ├── menu.py                   # Tüm araçlar için etkileşimli menü (npm run tools)
│   ├── check-characters.js       # Karakter doğrulayıcı (npm run check)
│   ├── selftest-hittest.js       # Tıklama geçirgenliği testi (npm run check:hittest)
│   ├── pixelart_extract.py       # AI çıktısını gerçek çözünürlüğe indirir
│   ├── split_sheet.py            # Sheet'i tek tek karelere böler
│   ├── pack_sheet.py             # Kareleri hizalayıp sprite sheet yapar
│   ├── grid_ref.py               # Bitmiş sheet'i Gemini'ye ızgara referansı yapar
│   ├── test_pixelart_extract.py  # Çıkarıcının regresyon testleri
│   ├── test_split_sheet.py       # Bölücünün regresyon testleri
│   ├── test_pack_sheet.py        # Hizalayıcının regresyon testleri
│   └── test_grid_ref.py          # Izgara referansının regresyon testleri
├── assets/                 # Ham/orijinal sprite dosyaları (uygulama bunları okumaz)
└── DESKTOP_PET_PLAN.md     # Mimari plan notları
```

Ana süreç yalnızca pencereyi konumlandırır; pet'in nerede olduğu ve ne yaptığı renderer'daki `Pet` sınıfında tutulur, konum değişiklikleri `pet:move` IPC mesajıyla ana sürece iletilir.

### Tıklama geçirgenliği

Pencere sprite'tan büyük olmak zorunda: konuşma balonuna üstte yer gerekiyor ve kare sprite kutusunun kendi boş kenarı var. Ölçüldüğünde pencerenin yalnızca **%6'sı** gerçekten pet'ti; kalan %94 altındaki uygulamalara giden tıklamaları yutuyordu.

Çözüm, pencerenin tıklama geçirgen **başlaması**:

```js
win.setIgnoreMouseEvents(true, { forward: true });
```

`forward: true` sayesinde pencere geçirgenken bile `mousemove` renderer'a ulaşıyor. Renderer her harekette canvas'ın **canlı piksellerini** okuyup imlecin gerçekten opak bir pikselin üstünde olup olmadığına bakıyor ([`isOverSprite`](renderer/pet.js)) ve yalnızca öyleyse pencereyi tıklanabilir yapıyor. Canvas'tan okumak, flip edilmiş yürüyüşte ve animasyonun her karesinde doğru sonucu veriyor — ayrı bir maske tutmaya gerek kalmıyor.

Birkaç piksellik bir pay var: karakter ~40 piksel eninde, kolu birkaç piksel kalınlığında; tam piksel isabeti istemek pet'i yakalamayı zorlaştırırdı. Pay aynı zamanda imleç sprite'a değmeden pencereyi hazır hale getirdiği için hızlı hareket edip hemen tıklayan kullanıcıdaki yarış durumunu da kapatıyor.

Regresyon testi (gerçek fare gerektirmez, sentetik olay enjekte eder):

```bash
npm run check:hittest
```

## Yeni karakter ekleme

**Karakterler klasörden otomatik keşfedilir** — `characters/` altında `meta.json` içeren her klasör bir karakterdir. Ortak bir kayıt dosyasına dokunmanız gerekmez, yani iki kişi aynı anda karakter eklerken çakışma yaşamaz.

1. `characters/<karakter-adi>/` klasörü aç, sprite sheet'leri içine koy.
   Sheet'ler **yatay** olmalı: kareler yan yana, her kare kare (kxk) ve arka plan şeffaf.
2. Aynı klasöre bir `meta.json` yaz:

```json
{
  "displayName": "Arkadaş 2",
  "nativeFrameSize": 88,
  "displayScale": 1,

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
| `nativeFrameSize` | Sprite dosyasındaki kare kutusunun boyutu (piksel) |
| `displayScale` | İstenen ekran çarpanı. Kesirli olabilir; uygulama o ekranda güvenli en yakın değere yuvarlar |
| `flip` | `true` ise kare çizilirken yatay aynalanır — sola yürüyüş için ayrı dosya tutmaya gerek yok |
| `frameDuration` | Kare başına milisaniye |
| `walkSpeed` | Yürüme hızı, saniyede piksel |
| `lines` | Tıklandığında rastgele seçilen cümleler |

### Farklı native boyuttaki karakterler

Karakterler farklı native çözünürlükte çıkabilir; [pixelart_extract.py](tools/pixelart_extract.py) bilerek sabit bir boyuta zorlamıyor (zorlamak düşük kontrastlı küçük detayları yok ediyordu). Boyut normalizasyonu bu yüzden uygulama katmanında.

Kural basit: **ekrandaki boy = native boy × `displayScale`**. Varsayılan 1, yani native çözünürlük neyse ekranda o.

`displayScale` kesirli olabilir, ama hangi kesirlerin bozulmadan çalıştığı **ekrana bağlı**. Bir kaynak pikselin kapladığı fiziksel piksel sayısı `displayScale × devicePixelRatio`; bu tam sayı değilse nearest-neighbor kimi pikseli n, kimini n+1 fiziksel piksel çizer ve 1 piksellik çizgiler eşitsiz kalınlaşır. Ölçüldüğünde `displayScale 1.2` / dpr 2'de dizi `2 2 3 2 3 2 2 3` çıkıyor — %50 kalınlık oynaması.

Bu yüzden uygulama **çalıştığı ekranın `devicePixelRatio` değerini okuyup** istenen ölçeği güvenli olan en yakın değere yuvarlıyor. Güvenli değerler her zaman `k / dpr`:

| devicePixelRatio | nerede | izin verilen ölçekler |
| --- | --- | --- |
| 1 | harici Retina olmayan monitör | 1, 2, 3 … |
| 1.5 | Windows %150 | 0.67, 1.33, 2, 2.67 … |
| 2 | Mac Retina, Windows %200 | 0.5, 1, 1.5, 2, 2.5 … |

Sonuçlar: `1.2` istenirse Retina'da `1.0` kullanılır, `1.3` istenirse `1.5`. Merdiven ekran başına hesaplandığı için pet monitörler arasında sürüklendiğinde ölçek canlı olarak yeniden yuvarlanıyor.

**Boyutu kullanıcı da değiştirebilir:** pet'e sağ tıklayıp **Boyut** menüsünden. Menüdeki seçenekler sabit değil — o anda bulunulan ekranın merdiveninden üretiliyor, yani menüden bozuk bir boyut seçmek mümkün değil. Seçim karakter başına saklanıyor ve `meta.json`'daki `displayScale`'i ezer; **Varsayılana dön** ile geri alınır.

İki pratik sonuç:

- **Retina'da `0.5` bedavaya küçültme.** `0.5 × 2 = 1`, yani kaynak piksel başına tam 1 fiziksel piksel — hiçbir bilgi kaybolmaz, sadece küçük görünür. Altına inmek gerçek kayıp: ölçüldüğünde `0.4`'te 87 satırın 18'i hiç çizilmiyor. Uygulama zaten `k ≥ 1` şartıyla buna izin vermiyor.
- **Aynı karakter farklı makinede farklı boyda görünebilir.** `1.5` isteyen 87px'lik bir karakter Retina'da 130px, 1x monitörde 174px olur (yukarı yuvarlama). Netliği korumak boyut tutarlılığından ödün vermek demek; pixel art için bu takası bilerek yaptık.

Karşılaştırma ölçütü `nativeFrameSize` **değil**, karakterin gerçek boyu: kutu, çapanın etrafına kare kurulduğu için kolunu yana açan bir karakterde boydan büyük çıkar. `npm run check` her karakterin gerçek boyunu yazar ve aralarında %25'ten fazla fark varsa uyarır:

```
✓ ael — Ael  (kutu 87, boy 85px × 1 = ekranda 85px)
✓ karakter1 — Arkadaş 1  (kutu 88, boy 86px × 1 = ekranda 86px)
```

Karakteriniz diğerlerinin yarısı kadar çıktıysa `"displayScale": 2` yazın. 0.5'in katı bir değer seçmek en iyisi — en yaygın ekranda (Retina) tam istediğinizi alırsınız. Aradaki bir değer gerekiyorsa doğru çözüm ölçeklemek değil, sprite'ı hedef ızgara yoğunluğunda yeniden ürettirmek.

### Kare boyutu neden kare?

Motor kareyi kare varsayıyor: [sprite-animator.js](renderer/sprite-animator.js) canvas'ı `frameSize × frameSize` yapıp sheet'ten aynı boyutta dilim alıyor. Karakteriniz 40×95 çıktıysa onu **germeden**, şeffaf pikselle 96×96'ya tamamlayın:

- **yatayda ortalayın** — sola yürüyüş `flip` ile üretiliyor ve aynalama canvas'ın ortasına göre yapılıyor; karakter kutuda ortalı değilse her dönüşte yana zıplar
- **ayakları alt kenara oturtun** — yoksa havada durur

Karakterler arasında ortak bir boyut **zorlamayın**. Native çözünürlük karakterden karaktere değişir (ölçülen bir sette 84, 85, 95, 156) ve hepsini aynı boya getirmek 156 → 95 gibi ondalıklı bir ölçek gerektirir; bu, piksel sanatının bozulmadan sağ çıkamayacağı tek işlemdir. Boy farkı rahatsız ediyorsa doğru yer üretim aşamasıdır: karakteri aynı ızgara yoğunluğunda yeniden ürettirin.

Karakterin **sağa bakıyor** olması gerekir — sola yürüyüş `flip` ile üretilir. Sola bakan bir sheet çizdiyseniz `walk_right`'a `"flip": true`, `walk_left`'e `false` verin.

`characters/characters.json` yalnızca ilk kurulumda hangi karakterle başlanacağını tutar; yeni karakter eklerken bu dosyaya dokunmayın.

## AI ile üretilen sprite'ları hazırlama

Bu bölümdeki araçların hepsi tek bir menüden çalıştırılabilir — komutları ve sırayı ezberlemek istemiyorsanız:

```bash
npm run tools
```

Menü her adımda çalıştırdığı komutu da ekrana basar, yani aşağıdaki CLI'ı öğrenmenin kısa yolu olarak da kullanılabilir.

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
| `--no-crop` | Kenar boşluklarını kırpmaz. Kareleri **elle** yan yana dizecekseniz şart; `pack_sheet.py` kullanıyorsanız gerekmez (o zaten içeriğe göre hizalar) |
| `--no-cleanup` | Leke/delik temizliğini atlar — temizlik gerçek bir detayı yerse |
| `--fill-gaps N` | Silüetin içinde kapalı kalmış, dama renginde, en fazla N piksellik adacıkları şeffaf yapar. Varsayılan kapalı — [aşağıya bakın](#kolla-gövde-arasındaki-kapalı-boşluklar) |
| `--verify` | Çıkarımın kayıpsızlığını ölçüp raporlar (aşağıya bakın) |
| `--debug-dir ./debug` | Ara adımları yazar; `1_izgara.png` tespit edilen ızgarayı orijinalin üstüne çizer, tespit yanlışsa hemen görülür |

Gemini'ye ne söyleyeceğiniz [PROMPTS.md](PROMPTS.md) içinde — hangi kısıtın gerçekten kritik olduğu ve hangisini araçların zaten hallettiği ölçümle ayrılmış durumda.

### Gemini tek bir sheet ürettiyse

Animasyonu tek bir spritesheet olarak ürettirdiyseniz sıra şu — ve **bu sıra önemli**:

Sırayı ve ara dosyaları elle takip etmek istemiyorsanız menüdeki 1 numaralı akış üçünü de doğru sırada çalıştırır:

```bash
npm run tools
```

```bash
python3 tools/pixelart_extract.py sheet_ham.png sheet_native.png
```

```bash
python3 tools/split_sheet.py sheet_native.png -o kareler/ --frames 7 --preview bolme.png
```

```bash
python3 tools/pack_sheet.py kareler/kare_*.png -o walk_right_spritesheet.png --gif onizleme.gif
```

Sezgisel olan sıra (önce böl, sonra her kareyi ayrı çıkar) **yanlış**: ızgara tespiti her kare için bağımsız çalışır ve bir kare 100×100, diğeri 97×97 tespit edilebilir. O noktada kareler farklı piksel ölçeğinde olur ve düzeltmenin tek yolu ölçeklemektir — yani piksel sanatını bozmaktır. Pixel art ızgarası sheet'in tamamında tek bir kafestir; bir kez ölçülünce tüm kareler garantili aynı ölçekte çıkar. Ayrıca dar bir şeritte ızgara tespiti tüm görüntüdekinden daha az veriyle çalışır.

[tools/split_sheet.py](tools/split_sheet.py) kareleri **tamamen boş satır/sütun bantlarından** ayırır — çıkarım sonrası arka plan gerçekten şeffaf olduğu için bu güvenilir bir sinyaldir. 1×N, N×1 ve R×C düzenlerinin hepsi aynı kodla çalışır.

| Seçenek | Ne işe yarar |
| --- | --- |
| `--frames N` | Beklenen kare sayısını doğrular; tutmazsa hata verir (sessizce yanlış bölmez) |
| `--rows R --cols C` | Kareler birbirine değiyorsa eşit bölme — tam ortalaması gerekmez, `pack_sheet` yeniden hizalar |
| `--min-gap N` | Ayırıcı sayılan en kısa boş şerit (varsayılan 1 piksel) |
| `--preview` | Bulunan kare sınırlarını kırmızı çerçeveyle çizer — bölme yanlışsa hemen görünür |

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
  "displayScale": 1
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
npm run test:tools
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

- Pet yalnızca X ekseninde hareket eder; zıplama/düşme gibi dikey fizik yok.
- Çoklu monitör: sürükleyip bıraktığında bulunduğu monitöre uyum sağlar, ama kendi başına yürürken monitörler arası geçmez.

## Yol haritası

- [ ] Dikey fizik (zıplama, kenardan düşme)
- [ ] Yürürken monitörler arası geçiş
- [ ] Ayarlar penceresi (hız, boyut, konuşma sıklığı)
- [ ] Aynı anda birden fazla pet (`createPetWindow` zaten çoğaltmaya uygun)
