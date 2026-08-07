# Katkı Rehberi

Projede iki tür katkı var: **karakter (art) eklemek** ve **kod değiştirmek**. Karakter eklemek kod değişikliği gerektirmez — bu yüzden art tarafında çalışan kişilerin JavaScript'e dokunması gerekmiyor.

## Kurulum

```bash
npm install
```

```bash
npm start
```

## Karakter ekleme akışı

İki yol var. **Elinde tek bir karakter görseli varsa** en kısası PixelLab boru
hattı: animasyonları o üretir, sheet'leri paketler, `meta.json`'ı yazar.

```bash
npm run karakter
```

Argümansız çalıştırınca sorarak ilerler; komut satırından da verilebilir:

```bash
python3 tools/pixellab_karakter.py kedi.png --ad kedi --display-name Kedi
```

Girdi **önden bakan, şeffaf zeminli, native çözünürlükte** tek bir PNG olmalı —
ham AI çıktısını doğrudan verme, önce `pixelart_extract.py`'den geçir. Araç
görseli 8 yöne döndürüp iskelet şablonlarıyla idle (önden) ve yürüyüş (yandan)
animasyonlarını üretir, `characters/<ad>/` altına yazar ve `npm run check`
çalıştırır.

Ücretli: karakter başına 3-4 generation. `--dry-run` üretmeden maliyeti söyler,
`--seed` üretimi tekrarlanabilir yapar. Yarıda kesilirse ödenmiş adımlar
`_data/pixellab/<ad>/durum.json`'a yazıldığı için tekrar çalıştırınca kaldığı
yerden devam eder. Anahtar `.env` içinde `PIXELLAB_API_KEY=` olarak durur.

Karakterin adı ve tarifi sorulur; animasyon şablonları, replikler ve kare
süreleri varsayılan geçer — hepsi sonradan `meta.json`'dan değiştirilebilir.

Tarif zorunlu bir alan ama boş geçilebilir (varsayılanı vardır): görseli
üretmiyor, PixelLab'ın karakteri 8 yöne döndürürken neye baktığını anlaması
için. **Dört ayaklı bir karakter üretiyorsan** `--govde` (menüde "iki ayaklı
mı?" sorusu) mutlaka doğru olsun — iskelet ona göre kuruluyor ve yanlış
şablonda yürüyüş animasyonu bozulur.

**Kareleri kendin üretiyorsan** aşağıdaki elle akış geçerli.

Sprite'ları Gemini'ye ürettireceksen prompt'lar [PROMPTS.md](PROMPTS.md) içinde. Ürettiysen, **önce** [tools/pixelart_extract.py](tools/pixelart_extract.py) ile gerçek çözünürlüğe indir — ayrıntı [README](README.md#ai-ile-üretilen-spriteları-hazırlama) içinde. Ham AI çıktısını doğrudan `characters/` altına koyma: dosya 1024×1024 görünür ama içindeki gerçek pixel art çok daha küçüktür ve arka planındaki dama deseni gerçek şeffaflık değildir.

Animasyon karelerini **elle yan yana dizme.** Her kare ayrı bir üretim olduğu için karakter tuval içinde farklı yerde durur; elle dizersen animasyon titrer. [tools/pack_sheet.py](tools/pack_sheet.py) kareleri ayak çizgisine ve gövdeye göre hizalar, ortak kare kutuya oturtur ve `meta.json` bloğunu basar:

```bash
python3 tools/pack_sheet.py kare*.png -o characters/<ad>/walk_right_spritesheet.png --gif onizleme.gif
```

Bir karakterin **tüm kliplerini aynı `--box` değeriyle** paketleyin. pack_sheet kutuyu her klip için ayrı hesaplıyor ve idle 86, walk 87 gibi farklı çıkabiliyor; tek bir `nativeFrameSize` tutmak için önce ikisini de box'sız çalıştırıp gereken en büyük değeri görün, sonra ikisini de `--box <o değer>` ile paketleyin.

Gemini animasyonu **tek bir sheet** olarak ürettiyse önce tüm sheet'i çıkar, sonra [tools/split_sheet.py](tools/split_sheet.py) ile böl — tersi değil. Sebebi [README](README.md#gemini-tek-bir-sheet-ürettiyse) içinde.

Ürettiği GIF'i açıp titreme olup olmadığına bak — PR'a da bu GIF'i ekleyebilirsin.

1. Kendine bir dal aç:

   ```bash
   git checkout -b karakter/<ad>
   ```

2. `characters/<ad>/` klasörünü oluştur, sprite sheet'leri ve `meta.json`'ı koy.
   Formatın tamamı [README](README.md#yeni-karakter-ekleme) içinde.

3. Doğrula — bu adımı atlama, en sık hatalar burada yakalanıyor:

   ```bash
   npm run check
   ```

4. Uygulamayı açıp sağ tık → **Karakter Değiştir** ile kendi karakterini seç, yürüyüşünü ve idle'ını gözle kontrol et.

5. Commit'le ve PR aç.

**Sadece kendi klasörünü ekle.** `characters.json`, `main.js` ya da `renderer/` altındaki dosyalara dokunmadığın sürece kimseyle çakışmazsın — karakterler klasörden otomatik keşfediliyor.

## Sprite kuralları

- Yatay sheet: kareler yan yana, boşluksuz
- Her kare **kare** (kxk) ve arka planı **şeffaf**
- Sheet genişliği tam olarak `frameSize × frameCount` olmalı — 1 piksel şaşarsa animasyon kayar
- Karakter **sağa** baksın; sola yürüyüş `flip` ile üretiliyor
- Karakterin ayakları karenin **alt kenarına** otursun, yoksa ekranda havada durur
- Ekrandaki boy = karakterin native boyu × `displayScale`. Varsayılan 1; karakteriniz diğerlerinin yarısı kadar çıktıysa 2 yazın. Kesirli değer yazabilirsiniz ama **0.5'in katı** olsun — uygulama çalıştığı ekranda güvenli olan en yakın değere yuvarlıyor ve 0.5'in katları en yaygın ekranlarda birebir karşılanıyor. `npm run check` boyları karşılaştırıp aykırı olanı söyler

Klasör adları için küçük harf + ASCII kullan (`karakter2`, `kedi`). macOS büyük/küçük harfe duyarsız ama Linux (ve CI) duyarlı — `Kedi` ile `kedi` orada iki ayrı klasör olur.

## Konuşma balonu asset'leri

Balon `renderer/ui/` altında, **native çözünürlükte** (1x) duruyor. Ölçekleme
uygulamada, karakterle aynı katsayıyla yapılıyor — asset'i büyük çizip
küçültmeyin.

| Dosya | Boyut | Yapı |
| --- | --- | --- |
| `bubble.png` | 32×12 | 9-slice: köşe 5×5, kenar dilimi 22×2 |
| `bubble_tail.png` | 4×5 | aşağı bakan kuyruk; sağa bakan çizilir, kodda flip edilir |

Balon her metin uzunluğuna esnediği için sabit bir resim değil, 9-slice: köşeler
1:1 kalır, **kenarlar ve orta tile edilir** (esnetilmez). Bu yüzden tek kritik
kural şu: kenar dilimleri kendi kendine tekrarlandığında dikiş görünmemeli. En
güvenlisi kenarları düz tutup (1px hat + dolgu) süslemeyi köşelere koymak.

Kuyruğun **en üst satırı gövdenin alt hattını keser**: o satırda hat yerine dolgu
rengi vardır ve kod kuyruğu 1px yukarı, hattın üstüne çizer. Balonun ağzı böyle
açılıyor. Bu yüzden kuyruğun ekranda kapladığı yükseklik asset yüksekliğinden 1
eksik (`kuyrukPay`) ve gövdenin alt kenarında delik **olmamalı** — olsaydı tile
edilirken tekrarlanırdı.

Açılış animasyonu için sprite sheet çizmeyin — her metin uzunluğu ayrı sheet
gerektirirdi. "Pop" efekti kutu boyutunu kare kare değiştirerek kodda üretiliyor
(`speech-bubble.js`, `ACILIS` dizisi).

Boyutları değiştirebilirsiniz: kuyruk yüksekliği asset'ten okunuyor, ama köşe
boyutu `KOSE` sabitinde duruyor — daha kalın köşeli bir balon çizerseniz onu da
güncelleyin. `npm run check:bubble` balonu ölçüp `$TMPDIR/pet-balon*.png` altına
ekran görüntüsü bırakır.

### Metin ve font

Metin `renderer/fonts/PixelifySans.ttf` ile çiziliyor (OFL, lisans yanında).
Font bir outline fontu, gerçek bitmap değil — o yüzden metin native boyutta
çizilip **alfa eşiklemesinden** geçiriliyor, yani çalışma anında bitmap'e
çevriliyor (`pixel-text.js`). Ölçekleme bundan sonra.

Font boyutu 10 native px'e sabit: ölçüldü, 6–8px'te eşikleme sonrası `ı`/`İ`/`ğ`
ayırt edilemiyor. Replikleri yazarken **emoji kullanmayın** — pixel fontta
karşılığı yok.

## Kod değişiklikleri

| Dosya | Sorumluluk |
| --- | --- |
| `main.js` | Pencere, tray, menü (karakter + boyut), IPC, kalıcılık, karakter keşfi |
| `preload.js` | Renderer'a açılan API yüzeyi |
| `renderer/pet.js` | Durum makinesi ve davranış |
| `renderer/sprite-animator.js` | Kare çizimi |
| `renderer/speech-bubble.js` | Konuşma balonu: 9-slice çerçeve, kuyruk, pop animasyonu |
| `renderer/pixel-text.js` | Pixel font metin motoru (satır sarma + alfa eşikleme) |

Renderer'ın Node'a doğrudan erişimi yok (`contextIsolation` açık). Yeni bir ana süreç yeteneği gerekiyorsa `preload.js`'e açıkça eklenmeli.

Kod stili: 2 boşluk girinti, tek tırnak, noktalı virgül. Yorumlar Türkçe ve **niçin**'i anlatsın — ne yaptığı zaten kodda yazıyor.

## Commit ve PR

- Commit mesajı Türkçe, ilk satır 72 karakteri geçmesin, emir kipi:
  `Kedi karakteri ekle`, `Yürüme hızını meta.json'a taşı`
- PR'da karakter eklediysen ekran görüntüsü ya da kısa bir kayıt ekle — sprite'ın gerçekten doğru çizildiğini gözle görmek en hızlı kontrol
- PR açmadan önce `npm run check` yeşil olsun
- Uygulama koduna dokunduysan `npm run check:hittest` de yeşil olsun

## Çakışma çıkarsa

PNG dosyaları ikili; Git bunları birleştiremez. İki kişi aynı sprite'ı düzenlediyse conflict'i elle çözmek yerine hangi sürümün kalacağına karar verin:

```bash
git checkout --ours characters/<ad>/<dosya>.png
```

```bash
git checkout --theirs characters/<ad>/<dosya>.png
```

Herkes kendi klasöründe çalıştığı sürece bu durum pratikte oluşmaz.
