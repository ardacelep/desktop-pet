# Gemini Prompt Rehberi

Karakter ve animasyon üretirken kullanılacak prompt'lar. Her kısıtın **neden** orada olduğu yazılı — çünkü Gemini uzun prompt'ların bir kısmını görmezden geliyor, hangilerinin taviz verilebilir olduğunu bilmek gerekiyor.

Araçların ne yaptığı: [README](README.md#ai-ile-üretilen-spriteları-hazırlama).

## Hangi kısıt gerçekten kritik?

| Kısıt | Neden | Araç düzeltebilir mi |
| --- | --- | --- |
| Tüm sheet **tek bir piksel ızgarasında** çizilmiş olmalı | `pixelart_extract` sheet'in tamamında tek kafes varsayıyor | ✗ |
| Karakterin **ölçeği tüm karelerde aynı** olmalı | Ölçek farkını düzeltmenin tek yolu yeniden örneklemek, yani piksel sanatını bozmak | ✗ |
| Kareler arasında **tamamen boş şerit** olmalı | `split_sheet` kareleri boş satır/sütundan ayırıyor | ✗ |
| **Çerçeve, kare numarası, etiket, yer gölgesi yok** | Hepsi opak piksel; kareye yapışır ya da bölmeyi bozar | ✗ |
| Dama rengi karakterde **hiç bulunmayan** bir renk olmalı | Ölçüldü: gri damada saf beyaz karakter pikselleri yeniyor, magenta damada yenmiyor | kısmen |
| Blok kenarları **keskin** olmalı, yeniden sıkıştırma olmamalı | Yeterince bozulmuş bir render'da ızgara hiç bulunamıyor ve `pixelart_extract` hata verip duruyor | ✗ |
| Filigranın **karakterin üstüne gelmemesi** | Engellenemiyor; prompt'ta konuyu açmak durumu kötüleştiriyor. Tek çare düzende sağ alt hücreyi boş bırakmak | ✗ |
| Karakter **dış kenara değmemeli** | Dama tonları tam o kenar şeridinden öğreniliyor; değerse karakterin konturu "dama tonu" sanılıyor | ✗ |
| Karakterin canvas'ta ortalı olması | `pack_sheet` zaten içerikten hizalıyor | ✓ |
| Kareler arası aynı taban çizgisi | `pack_sheet` ayak çizgisine hizalıyor | ✓ |
| Kareler arası boşluk miktarı | Kırpma ve hizalama hallediyor | ✓ |
| Beyaz/krem kıyafet yasağı | Magenta damayla ölçülen kayıp sıfır — kısıt artık gereksiz | ✓ |

Yani prompt'ta yer alması gereken şey, üstteki sekiz satır. Alttaki dördü eskiden zorunluydu, artık değil; "canvas'ın %85'ini doldurmalı" ya da "beyaz ayakkabı kullanma" gibi maddeleri prompt'a koymak sadece Gemini'nin dikkatini dağıtır.

## Dama rengi: gri değil, magenta

Eski rehber **açık tonlu** dama istiyordu (`#FFFFFF` / `#E0E0E0`); o, eski script nötr gri beklediği için doğruydu. `pixelart_extract` dama rengini kenardan ölçerek buluyor, dolayısıyla artık tersi geçerli: dama, karakterin paletinde **asla bulunmayacak** bir renk olmalı.

Ölçüm (saf beyaz içeren bir karakterle):

| Dama | Arka plan kalıntısı | Yenen karakter pikseli |
| --- | --- | --- |
| `#ffffff` / `#e1e1e1` | 0 | 1 |
| `#ff00ff` / `#c000c0` | 0 | 0 |
| `#b4f0c8` / `#8cd8a8` | 0 | 0 |

Yan fayda: `--fill-gaps` güvenli hale geliyor. Gri damada göz akı (254-255) damanın açık tonundan (253) ayırt edilemiyor ve boşluklarla birlikte siliniyor; magenta damada göz akı damaya 300 birim uzak, yani hiçbir zaman aday olmuyor.

İkinci fayda tolerans payında. Ölçülen bir magenta render'da dama tonları `(184,0,184)` ve `(254,1,252)`, dama karelerinin sınırındaki karışım pikselleri ise `(210,0,211)` — tonlara 27 birim uzak. Magenta damada 36 birimlik tolerans rahatça güvenliyken gri damada 4 bile riskli, çünkü güvenli tolerans tamamen damanın karakter paletine uzaklığına bağlı.

## Render keskinliği: kurtarılamayan tek kusur

Prompt'taki en kolay gözden kaçan teknik madde bu. Diğer kusurların çoğunu araçlar telafi ediyor; yeniden sıkıştırılmış bir render'ı hiçbir şey telafi etmiyor.

`pixelart_extract` önce "bu görsel zaten native mi, yoksa büyütülmüş mü?" diye soruyor. Ölçüt, komşu satır/sütun farklarının biçimi: büyütülmüş pixel art'ta dağılım iki tepeli (blok içi farklar küçük, blok sınırları büyük), native görselde tek tepeli. 53 gerçek dosyada ölçülen aralıklar — büyütülmüş pixel art 0.14–0.29, **ağır yeniden kodlanmış sheet'ler 0.56–0.59**, native pixel art 0.77–1.24, illüstrasyon/fotoğraf 0.86–0.99. Eşik 0.70.

Yani yeniden kodlama görseli tam da karar sınırına doğru itiyor: blok içi gürültü arttıkça görsel giderek "native" gibi görünüyor.

Ölçülen gerçek örnek, 5632×704'lük bir yürüyüş sheet'i (171 700 ayrı renk): oran `(0.520, 0.558)`. Sınıflandırma doğru — büyütülmüş sayılıyor — ama bir sonraki adım tutmuyor:

```
HATA: X ekseninde izgara bulunamadi (en iyi oran 1.40, esik 3.0)
      — gorsel buyutulmus pixel art olmayabilir ya da render cok bozuk olabilir.
```

Bu iyi haber: araç sessizce bozuk çıktı vermek yerine duruyor. Ama dosya yine de kurtarılamıyor — tek çare yeniden ürettirmek.

Pratikte: **çıktı PNG olarak alınmalı**, JPEG'e çevrilmemeli, "enhance"/upscale filtresinden geçirilmemeli, ekran görüntüsüyle yeniden kaydedilmemeli. Blok kenarlarında ara ton olmamalı.

Kontrol etmenin en hızlı yolu, `pixelart_extract`'in bildirdiği native çözünürlük: 2048'lik bir canvas'tan 100×100 civarı bekliyorsanız ve araç size girdiyle aynı ölçüyü söylüyorsa ya da ızgarayı hiç bulamıyorsa, render bozuktur.

### Kusur renk gürültüsü değil, kafes kayması

Sezgi "sıkıştırma gürültüsü" der ama ölçüm başka şey gösterdi. Başarısız bir sheet 32 renge indirgendiğinde bile ızgara skoru 1.71'de kaldı (eşik 3.0) — yani sorun renk sayısı değil.

Asıl ölçüt blok sınırlarının **fazı**: bütün sınırlar aynı kafese mi oturuyor? İki sheet aynı ızgara referansından üretildi, dama deseni ikisinde de birebir aynı (57px kare), ama:

| | ızgara skoru | sınır fazlarının toplanması |
| --- | --- | --- |
| Çalışan sheet | 93.17 | 0.989 — sınırların %99'u tek fazda |
| Bozuk sheet | 1.78 | 0.170 — sınırlar on dilime dağılmış |

Yani arka planın düzenli olması yetmiyor; **karakterin** blok kenarlarının hepsi tek bir kafese oturmalı. Bozuk örnekte karakter, kenarları piksel ızgarasına oturtulmadan çizilmişti — çizgili gömlek gibi ince desenler bu riski artırıyor.

### En sinsi kusur: satırdan satıra ölçek kayması

Ölçülen bir sheet'te ızgaranın **her satırı farklı piksel ölçeğinde** çizilmişti:

| Izgara satırı | Blok | Karakterin native boyu |
| --- | --- | --- |
| 1 | 8.67px | 70px |
| 2 | ~8.0px | 77px |
| 3 | ~7.3px | 83px |

Karakterlerin ekrandaki boyu hepsinde aynıydı (~605px) — değişen şey piksel yoğunluğuydu. Bu yüzden göze hiçbir şey batmıyor; sheet gayet düzgün görünüyor.

Ama tüm sheet için **tek bir kafes yok**. Global tespit haklı olarak reddediyor, tek periyot zorlanınca da üç satırın ikisi yanlış örnekleniyor: gözler lekeye dönüyor, ince desenler tırtıklanıyor.

Çare `--per-frame`: kareler önce ayrılıyor, her birinde ayrı kafes aranıyor (ölçüldü: her karede %100 uyum), sonra hepsi ortak bir native boya indiriliyor.

```bash
python3 tools/pixelart_extract.py sheet.png native.png --per-frame --merge-colors 10
```

Hedef boy, kabul edilebilirlerin **en küçüğü**: büyütmek piksel uydurur ve tam da kaçındığımız düzensiz blokları üretir; küçültmek mod örneklemedir, bilgi atar ama uydurmaz. Yine de kayıp gerçek — en iyisi sheet'i yeniden ürettirmek.

### Kurtarma: `--period`

Düzen biliniyorsa (elinizde native karakter varsa) periyodu elle verebilirsiniz; hücre içi **mod** alındığı için kafes birebir oturmasa da kullanılabilir sonuç çıkıyor:

```bash
python3 tools/pixelart_extract.py sheet.png native.png --period 7.136 --merge-colors 12
```

Periyot = sheet'teki karakter yüksekliği / native karakter yüksekliği. Bu bir onarım değil, mecburiyet çözümü: sonuç ölçülebilir şekilde daha gürültülü olur. Şansınız varsa yeniden ürettirin.

## Düzen: ızgara, tek sıra değil

**Kareleri tek sırada yan yana istemeyin.** 8 kare tek sırada = 8:1 en-boy oranı; bu kadar uzun bir görsel elinize gelene kadar yeniden ölçeklenip sıkıştırılıyor ve piksel ızgarası bunu kaldırmıyor. Ölçülen gerçek bir örnek: 5632×704'lük bir yürüyüş sheet'i **171 700 ayrı renkle** geldi (temiz bir render'da birkaç yüz renk olur) ve ızgara tespiti tamamen başarısız oldu — `pixelart_extract` "X ekseninde izgara bulunamadi" deyip durdu. Dosya kurtarılamadı, yeniden ürettirmek gerekti.

Çare, aynı kareleri ızgaraya dizmek — canvas kareye yakın kalıyor:

| Kare sayısı | İstenecek düzen | Canvas |
| --- | --- | --- |
| 4 | 2 satır × 2 sütun | kare |
| 6 | 2 satır × 3 sütun | kareye yakın |
| 8 | 2 satır × 4 sütun | 2:1 |
| 9 | 3 satır × 3 sütun | kare |

Gemini kare canvas'ta daha tutarlı çalışıyor; dikey/portre canvas istendiğinde karakteri sıkıştırıp ölçeği kareler arasında oynatıyor. `split_sheet.py` R×C ızgarayı zaten destekliyor (ölçüldü: 2×4 ızgara, 8 kare, okuma sırası korunuyor), o yüzden ızgara istemenin bizim tarafta hiçbir maliyeti yok.

Motorun beklediği **yatay şerit** endişe konusu değil: onu `pack_sheet` üretiyor ve o dosya küçük olduğu için (ör. 256×32) sıkıştırma sorunu yaşamıyor. Izgara yalnızca Gemini'den ALIRKEN gerekli.

**Bunun bedeli çözünürlük.** Tek kare üretiminde 2048'lik canvas'tan ~95 piksel boyunda karakter çıkıyor; 2×2 ızgarada her kareye 1024 düşüyor, yani yaklaşık yarısı. Karşılığında kareler **birbiriyle tutarlı** oluyor — kareleri tek tek ürettirmenin en büyük sorunu buydu: her üretim karakteri biraz farklı ölçekte çiziyor ve ölçek farkını araç düzeltemiyor. Detay mı tutarlılık mı sorusunun cevabı karaktere göre değişir; ikisini de deneyip `pixelart_extract`'in bildirdiği native çözünürlüğe bakın.

---

## 1. Temel karakter (buradan başlayın)

Her şeyin referansı bu görsel: walk ve idle sheet'leri buna bakarak üretiliyor, dolayısıyla buradaki bir hata sonraki her adıma taşınıyor. Fotoğraftan üretiyorsanız **8-10 fotoğrafı birlikte** verin — tek fotoğrafla üretilen karakterin kimliği (saç, gözlük, kıyafet tercihi) kareler arasında oynuyor.

```
Sana bu kişinin 8-10 farklı fotoğrafını veriyorum. Bunları tek tek değil, BİRLİKTE
analiz ederek tutarlı bir karakteristik profil çıkar, sonra bu profile göre tam
vücut bir pixel art karakter üret.

ADIM 1 — ANALİZ
Tüm fotoğrafları karşılaştırarak, farklı açı/ışık/ifadelerde bile DEĞİŞMEYEN,
kişiyi tanımlayan özellikleri belirle:
- Saç rengi, uzunluğu ve modeli
- Yüz yapısı: gözlük var mı, sakal/bıyık modeli
- Genel vücut yapısı (uzun/kısa, ince/dolgun)
- Fotoğraflarda tekrar eden kıyafet tarzı veya renk tercihi
- Sabit aksesuarlar (gözlük modeli, küpe, saat, yaka kartı)
Çelişen detaylarda en sık tekrar edeni ya da en ayırt edici olanı seç.

ADIM 2 — KARAKTER
- Poz: tam vücut, ÖNDEN görünüm, ayakta, nötr duruş. Kollar gövdenin yanında.
- Stil: chunky/blocky 16-bit oyun karakteri estetiği, basitleştirilmiş detaylar.
- Orantı: chibi, 2-3 baş boyu (büyük kafa, küçük gövde).
- Palet: 16-24 renk, net koyu kontur.
- Fotoğraftaki en belirgin 2-3 özelliği abartarak/stilize ederek yansıt.
- İki ayak da AYNI yatay çizgiye otursun.

ARKA PLAN — DAMA DESENİ
- Şeffaflığı göstermek için dama (checkerboard) deseni kullan; renkleri TAM OLARAK
  #FF00FF ve #C000C0 olsun.
- Bu iki magenta tonu karakterin HİÇBİR yerinde kullanılmamalı.
- Dama tüm görsel boyunca AYNI iki renkte kalsın: gradyan, gölge, vinyet, ışık
  kayması ya da renk kayması EKLEME.
- Dama karesinin kenarı, karakterin piksel bloğunun tam katı olsun (örneğin bir
  dama karesi = 2 piksel bloğu) ve dama karakterle AYNI ızgaraya hizalansın.

RENDER KESKİNLİĞİ — EN KRİTİK TEKNİK MADDE
- Gerçek pixel art: her piksel bloğu TEK bir düz renk, kenarları keskin.
- Anti-aliasing, yumuşak geçiş, gradyan, bulanıklık, yumuşak gölge ya da yarı
  saydam piksel YOK. Blok kenarlarında ara ton olmayacak.
- Tüm görsel TEK bir piksel ızgarasında çizilsin; blok boyutu her yerde aynı.
- Çıktı PNG olsun. JPEG'e çevirme, yeniden sıkıştırma, "enhance"/upscale ya da
  keskinleştirme filtresi uygulama.

GÖRSELDE BULUNMAYACAKLAR
- Yer gölgesi, zemin çizgisi, platform, yansıma.
- Çerçeve, kenarlık, başlık, etiket, yazı, renk paleti şeridi.
- Karakterden KOPUK hiçbir parça olmasın; silüet tek parça olsun.

- Kolla gövde arasında 1-2 piksellik minik boşluklar bırakma: kol ya gövdeye
  değsin ya da arada en az 4 piksellik net bir açıklık olsun.

Canvas kare (1:1) ve olabilecek en yüksek çözünürlükte olsun.
Çıktıyı PNG olarak ver.
```

Bu prompt'ta **kasıtlı olarak bulunmayan** iki eski madde var. "Karakter canvas'ın en az %85'ini doldursun" gereksiz: `pixelart_extract` kenar boşluğunu kırpıyor, `pack_sheet` de hizalıyor. "Beyaz/krem kıyafet kullanma" da gereksiz: o kısıt gri damanın beyaz pikselleri yemesi yüzünden vardı, magenta damayla ölçülen kayıp sıfır. İkisini de prompt'a geri koymak Gemini'nin dikkatini gerçekten kritik olan maddelerden dağıtıyor.

Karakteri işleyip `characters/` altına koymak için: [README](README.md#yeni-karakter-ekleme).

---

## 2. Walk cycle spritesheet — sıfırdan (4 kare, 2×2)

Gemini'nin yürüyüş döngüsünü sıfırdan tutturması zor; bu prompt bir deneme değeri taşıyor ama sonuç tatmin etmezse [3. bölümdeki](#3-hazır-sheet-üzerinde-karakter-değiştirme-walk-için-önerilen-yol) poz-referanslı yöntem belirgin şekilde daha güvenilir.

```
Ekteki pixel art karakteri referans alarak, YÜRÜME animasyonunun 4 karesini TEK bir
görselde, 2x2 ızgara halinde üret.

YERLEŞİM
- Kare canvas (1:1), olabilecek en yüksek çözünürlükte.
- 2 satır x 2 sütun. Okuma sırası: sol üst = 1. kare, sağ üst = 2. kare,
  sol alt = 3. kare, sağ alt = 4. kare.
- Kareler arasında ve ızgaranın dışında, KARAKTERE AİT HİÇBİR PİKSEL BULUNMAYAN,
  tamamen arka plan olan boş şeritler bırak. Şerit genişliği bir karenin en az
  onda biri kadar olsun.
- Çerçeve, ayırıcı çizgi, kare numarası, etiket, başlık ya da yazı EKLEME.
- Karakterin altına yer gölgesi ya da zemin çizgisi ÇİZME. Karakter dışında hiçbir
  şey olmayacak.

ARKA PLAN
- Şeffaflığı göstermek için dama (checkerboard) deseni kullan; renkleri tam olarak
  #FF00FF ve #C000C0 (magenta) olsun.
- Bu iki renk karakterin hiçbir yerinde KULLANILMAMALI.
- Dama deseni tüm görsel boyunca AYNI iki renkte kalsın; gölge, gradyan, vinyet
  ya da renk kayması ekleme.

ÖLÇEK — EN KRİTİK MADDE
- Karakterin ölçeği dört karede de BİREBİR aynı olmalı: kafa yüksekliği, gövde
  genişliği, bacak uzunluğu, gözlük boyutu — hepsi aynı sayıda piksel.
- Değişen tek şey uzuvların POZİSYONU olacak. Karakteri kareler arasında
  büyütme, küçültme, yakınlaştırma.
- Tüm sheet aynı piksel ızgarasında çizilsin: bir karedeki "piksel" bloğu ile
  diğerindeki aynı boyutta olmalı.

POZLAR (yandan görünüm, karakter SAĞA bakıyor)
Her kareyi aşağıdaki gibi, mutlak olarak çiz. "Öncekinin aynası" diye düşünme,
her kareyi sıfırdan tarif edildiği gibi çiz.

1. kare — Temas: Sağ bacak (izleyiciye yakın olan, açık tonlu) öne uzanmış,
   topuk yere değiyor. Sol bacak (uzak olan, koyu tonlu) geride, parmak ucunda.
   Sağ kol geride, sol kol önde.
2. kare — Geçiş: Sağ bacak dikey, tüm ağırlık onda, yere tam basıyor. Sol bacak
   dizden bükülü, ayak yerden kalkmış, sağ bacağın yanından geçiyor. Gövde en
   yüksek noktada. Kollar gövdenin yanında, neredeyse dikey.
3. kare — Temas: Sol bacak (uzak olan, koyu tonlu) öne uzanmış, topuk yere
   değiyor. Sağ bacak (yakın olan, açık tonlu) geride, parmak ucunda.
   Sol kol geride, sağ kol önde.
4. kare — Geçiş: Sol bacak dikey, tüm ağırlık onda. Sağ bacak dizden bükülü,
   ayak yerden kalkmış, sol bacağın yanından geçiyor. Gövde en yüksek noktada.
   Kollar gövdenin yanında.

Uzak taraftaki kol ve bacağı biraz daha koyu tonda çiz ki hangi uzvun önde
olduğu anlaşılsın.

ÇİZİM KURALLARI
- Gerçek pixel art: her piksel bloğu tek düz renk, kenarları keskin. Yumuşak
  geçiş, anti-aliasing, gradyan, bulanıklık ya da yarı saydam piksel YOK.
- Çıktı PNG olsun. JPEG'e çevirme, yeniden sıkıştırma, "enhance"/upscale ya da
  keskinleştirme filtresi uygulama.
- Sınırlı palet (16-24 renk), net koyu kontur.
- Karakterin tasarımı (saç, gözlük, sakal, kıyafet, aksesuarlar, renkler)
  referanstakiyle birebir aynı kalmalı.
- Kolla gövde arasında 1-2 piksellik minik boşluklar bırakma: kol ya gövdeye
  değsin ya da arasında en az 4 piksellik net bir açıklık olsun.

Çıktıyı yüksek çözünürlüklü PNG olarak ver.
```

## 3. Hazır sheet üzerinde karakter değiştirme (walk için önerilen yol)

Sıfırdan walk cycle üretimi Gemini'de güvenilir değil: model ayna-simetrik pozları tutturamıyor, çoğu denemede aynı pozu tekrarlıyor. Çalışan yol, **pozu üretmeyi modelden almak** — animasyonu doğru olan hazır bir sheet'i poz referansı verip yalnızca karakteri değiştirtmek.

### Önce referansı ızgaraya çevirin

Referansı **şerit** verip çıktıyı **ızgara** istemek ölçülebilir şekilde kötü sonuç veriyor: model aynı anda hem yeniden dizmek hem karakter değiştirmek zorunda kalıyor ve poza ayırdığı dikkat azalıyor — bir denemede alt satırdaki dört kare birbirinin neredeyse aynısı çıktı. Referansı zaten istediğiniz düzende verin, o yükü ortadan kaldırın:

```bash
python3 tools/grid_ref.py characters/ael/walk_right_spritesheet.png -o izgara_referans.png
```

Araç üç şeyi birden hallediyor: kareleri ızgaraya diziyor, magenta damayı çiziyor ve **sağ alt hücreyi boş bırakıyor** (nedeni aşağıda). 8 kare için 3×3 seçiyor, dokuzuncu hücre boş kalıyor.

### Filigran: konuyu hiç açmayın

Gemini köşeye parıltı (✦) işaretini koyuyor ve bu **engellenemiyor**. Ölçülen bir üretimde tam karakterin şortunun üzerine geldi; orada kurtarılamaz, çünkü kopuk olmadığı için leke temizliği yakalayamıyor ve rengi karakterin gri tonlarıyla aynı ailede olduğu için renk ölçütü de ayırt edemiyor.

Prompt'ta filigrandan **hiç söz etmeyin** — ne yasak olarak, ne de "gerekiyorsa şuraya koy" diye. İkisi de denendi ve ikisi de ters tepti: yasaklayınca yine koydu, yer gösterince köşeye fazladan siyah damalı bir işaret daha ekledi (o işaret hem sağ hem alt kenara değiyordu, yani dama tonu öğrenmeyi de bozuyordu). Konuyu açmak modelin dikkatini oraya çekiyor.

Çare tamamen düzende: sağ alt hücre boş bırakılıyor, işaret oraya düşüyor ve çıkarımda zararsız kalıyor. `grid_ref.py` bunu kendiliğinden yapıyor, prompt'ta tek kelime etmeye gerek yok.

### Dış kenar payı da şart

Kareler arasındaki boşluk yetmiyor, **ızgaranın dışında da** pay gerekiyor. Ölçüldü: bir Gemini çıktısında karakterlerin ayakları tuvalin alt kenarına değiyordu (alt 8 piksellik şeridin %28'i karakter). `pixelart_extract` dama tonlarını tam o kenar şeridinden öğrendiği için ayakkabı konturu `#000000` üçüncü bir "dama tonu" sanıldı, tolerans 3 yerine 60 seçildi ve karakter yendi — çıktı 26×15'e düştü. Alta pay eklenince aynı dosyada tonlar düzeldi.

### Prompt

```
Sana İKİ referans veriyorum:
  (A) POZ REFERANSI — animasyonu doğru olan, IZGARA düzeninde bir sprite sheet.
  (B) KARAKTER REFERANSI — kullanmanı istediğim karakter.

GÖREV
(A)'daki her karenin POZUNU birebir koru, ama karakteri (B)'deki karakterle
DEĞİŞTİR. Yani iskelet/hareket (A)'dan, görünüm (B)'den gelecek.

- (A)'daki uzuv açıları, gövde eğimi, ayakların yere göre konumu, hangi karede
  hangi bacağın önde olduğu — hepsi aynı kalacak.
- (B)'deki saç, yüz, gözlük, sakal, kıyafet, aksesuarlar, renk paleti — hepsi
  birebir taşınacak.
- (A)'daki karakterin kıyafetinden, saç renginden, vücut oranından HİÇBİR ŞEY
  sızmayacak. (A) yalnızca poz kaynağı.

DÜZEN — (A) İLE BİREBİR AYNI
- (A)'nın ızgara düzenini AYNEN koru: aynı satır sayısı, aynı sütun sayısı,
  aynı kare sırası. Yeniden dizme, sıkıştırma, tek sıraya alma YOK.
- (A)'da BOŞ olan hücreyi BOŞ BIRAK. Oraya kare koyma, karakter çizme.
- Kareler arasındaki boşluklar ve ızgaranın DIŞINDAKİ kenar payı (A)'daki
  kadar kalsın. Karakterin hiçbir pikseli tuvalin dış kenarına DEĞMESİN.
- Canvas (A) ile aynı en-boy oranında olsun.
- Çerçeve, ayırıcı çizgi, kare numarası, etiket ya da yazı EKLEME.

ÖLÇEK — EN KRİTİK MADDE
- Karakterin ölçeği bütün karelerde BİREBİR aynı olmalı: kafa yüksekliği, gövde
  genişliği, bacak uzunluğu — hepsi aynı sayıda piksel.
- Değişen tek şey uzuvların POZİSYONU. Kareler arasında büyütme, küçültme,
  yakınlaştırma yok.
- Tüm sheet aynı piksel ızgarasında çizilsin; bir karedeki piksel bloğu ile
  diğerindeki aynı boyutta olmalı.
- Karakter SAĞA baksın (sola yürüyüş bizde aynadan üretiliyor).

ARKA PLAN
- (A)'daki dama (checkerboard) desenini aynen koru: renkleri TAM OLARAK
  #FF00FF ve #C000C0, kare boyutu da (A)'daki kadar.
- Bu iki magenta tonu karakterin HİÇBİR yerinde kullanılmamalı.
- Dama tüm görsel boyunca AYNI iki renkte kalsın; gradyan, gölge, vinyet ya da
  renk kayması EKLEME.

ÇİZİM KURALLARI
- Gerçek pixel art: her piksel bloğu TEK düz renk, kenarları keskin.
- Anti-aliasing, yumuşak geçiş, gradyan, bulanıklık ya da yarı saydam piksel YOK.
- Sınırlı palet (16-24 renk), net koyu kontur.
- Uzak taraftaki kol ve bacağı biraz daha koyu tonda çiz ki hangi uzvun önde
  olduğu anlaşılsın.
- Kolla gövde arasında 1-2 piksellik minik boşluklar bırakma: kol ya gövdeye
  değsin ya da arada en az 4 piksellik net açıklık olsun.
- Yer gölgesi, zemin çizgisi ÇİZME.


Çıktıyı PNG olarak ver. JPEG'e çevirme, yeniden sıkıştırma, "enhance"/upscale
filtresi uygulama.
```

### Gelen dosyada kontrol edilecekler

Kareler yapışık gelirse otomatik bölme çalışmaz; ızgara ölçüsünü elle verin (menüde 3. adımda "Kareler arasında boşluk var mı?" sorusuna hayır, ya da doğrudan):

```bash
python3 tools/split_sheet.py sheet_native.png -o kareler/ --rows 3 --cols 3 --preview bolme.png
```

Boş hücre kare sayısını bir fazla gösterir mi? Göstermez — boş hücrede opak piksel olmadığı için `split_sheet` onu kare saymaz. Ama filigran oraya düştüyse **sayar**; o zaman `--frames` ile beklenen sayıyı verip fazladan çıkanı silin.

## 4. Idle spritesheet

Idle için de en güvenilir yol poz referansı vermek. Sıfırdan üretim aşağıda ikinci seçenek olarak duruyor.

### 4a. Hazır idle sheet üzerinde karakter değiştirme (önerilen)

Walk ile aynı mantık, ama **bir tuzağı fazla var**: idle'da kareler arasındaki fark çok küçük. Ölçülen referansta nefes hareketi tam **1 piksel** — omuz hattı 1. karede y=7, diğer üçünde y=6; siluet farkları 35-101 piksel. Bu kadar ince bir farkı model kolayca "gürültü" sanıp dört kareyi birbirinin aynısı yapıyor. Prompt bu yüzden farkın korunmasını açıkça istiyor.

```bash
python3 tools/grid_ref.py characters/ael/idle_spritesheet.png -o idle_ref.png
```

4 kare için 2 satır × 3 sütun seçilir; iki hücre boş kalır, sonuncusu sağ altta (filigran oraya düşsün).

```
Sana İKİ referans veriyorum:
  (A) POZ REFERANSI — idle (bekleme) animasyonu, IZGARA düzeninde.
  (B) KARAKTER REFERANSI — kullanmanı istediğim karakter.

GÖREV
(A)'daki her karenin DURUŞUNU birebir koru, ama karakteri (B)'deki karakterle
DEĞİŞTİR. Duruş/hareket (A)'dan, görünüm (B)'den gelecek.

- (B)'deki saç, yüz, gözlük, sakal, kıyafet, aksesuarlar, renk paleti — hepsi
  birebir taşınacak.
- (A)'daki karakterin kıyafetinden, saç renginden, vücut oranından HİÇBİR ŞEY
  sızmayacak. (A) yalnızca duruş kaynağı.

EN KRİTİK MADDE — KARELER ARASI FARK ÇOK KÜÇÜK, KORU
(A)'daki dört kare birbirine ÇOK benziyor; aralarındaki tek fark göğüs/omuz
hattının 1 piksel oynaması. Bu fark animasyonun KENDİSİ, gürültü değil.
- Dört kareyi birbirinin aynısı YAPMA.
- Hangi karede omuz hattı yukarıdaysa senin çıktında da yukarıda olsun;
  aşağıdaysa aşağıda. (A)'ya kare kare bakıp bu farkı taşı.
- Farkı BÜYÜTME de: 1 piksellik oynama 1 piksel kalsın. Karakteri bütün
  olarak büyütüp küçültme.
- Ayakların konumu, bacaklar, kolların X konumu, kafanın boyutu, silüetin
  genişliği dört karede de TEK PİKSEL bile oynamayacak.

DÜZEN — (A) İLE BİREBİR AYNI
- (A)'nın ızgara düzenini AYNEN koru: aynı satır sayısı, aynı sütun sayısı,
  aynı kare sırası.
- (A)'da BOŞ olan hücreleri BOŞ BIRAK. Oraya kare koyma, karakter çizme.
- Kareler arasındaki boşluklar ve ızgaranın DIŞINDAKİ kenar payı (A)'daki
  kadar kalsın. Karakterin hiçbir pikseli tuvalin dış kenarına DEĞMESİN.
- Canvas (A) ile aynı en-boy oranında olsun.
- Çerçeve, ayırıcı çizgi, kare numarası, etiket ya da yazı EKLEME.

ÖLÇEK
- Karakterin ölçeği bütün karelerde BİREBİR aynı olmalı: kafa yüksekliği,
  gövde genişliği, bacak uzunluğu — hepsi aynı sayıda piksel.
- Tüm sheet aynı piksel ızgarasında çizilsin; bir karedeki piksel bloğu ile
  diğerindeki aynı boyutta olmalı.
- Karakter ÖNDEN görünsün (idle önden, yürüyüş yandan).

ARKA PLAN
- (A)'daki dama (checkerboard) desenini aynen koru: renkleri TAM OLARAK
  #FF00FF ve #C000C0, kare boyutu da (A)'daki kadar.
- Bu iki magenta tonu karakterin HİÇBİR yerinde kullanılmamalı.
- Dama tüm görsel boyunca AYNI iki renkte kalsın; gradyan, gölge, vinyet ya da
  renk kayması EKLEME.

ÇİZİM KURALLARI
- Gerçek pixel art: her piksel bloğu TEK düz renk, kenarları keskin.
- Anti-aliasing, yumuşak geçiş, gradyan, bulanıklık ya da yarı saydam piksel YOK.
- Sınırlı palet (16-24 renk), net koyu kontur.
- Kolla gövde arasında 1-2 piksellik minik boşluklar bırakma: kol ya gövdeye
  değsin ya da arada en az 4 piksellik net açıklık olsun.
- Yer gölgesi, zemin çizgisi ÇİZME.

Çıktıyı PNG olarak ver. JPEG'e çevirme, yeniden sıkıştırma, "enhance"/upscale
filtresi uygulama.
```

Gelen dosyada ilk bakılacak şey: **dört kare gerçekten farklı mı?** Aynı çıktıysa yeniden ürettirin — prompt'taki "fark animasyonun kendisi" maddesini daha da vurgulayarak. Kontrol için:

```bash
python3 tools/pack_sheet.py kareler/kare_*.png -o idle_spritesheet.png --gif on.gif --duration 500
```

GIF'te hiçbir hareket görünmüyorsa kareler aynıdır.

### 4b. Sıfırdan idle (poz referansı yoksa)

Walk prompt'unun aynısı; yalnızca POZLAR bölümünü değiştirin:

```
POZLAR (önden görünüm, nötr ayakta duruş)
Dört kare de aynı duruş. Değişen TEK şey göğüs/omuz hattının yüksekliği —
nefes alma hissi.

1. kare — Nötr: Referanstaki duruşun birebir aynısı.
2. kare — Göğüs/omuz hattı 1 piksel yukarıda.
3. kare — Göğüs/omuz hattı 2 piksel yukarıda (nefesin zirvesi).
4. kare — Göğüs/omuz hattı 1 piksel yukarıda.

Bunların DIŞINDA hiçbir şey değişmeyecek: ayakların konumu, bacaklar, şort,
ayakkabılar, kolların X konumu, kafanın boyutu ve konumu, silüetin genişliği —
hepsi dört karede de TEK PİKSEL bile oynamayacak. Karakteri bütün olarak
büyütüp küçültme; sadece göğüs/omuz hattı kayacak.
```

Tuzak şu: "nefes alma" belirsiz tarif edilirse Gemini nefes hissi yerine tüm karakteri büyütüp küçültüyor. Piksel cinsinden kesin talimat şart — hangi hattın kaç piksel kayacağı yazılmalı.

## 5. Üretim sonrası kontrol listesi

Pipeline'a sokmadan önce görsele bakıp şunları doğrulayın:

1. **Görsel ızgara mı, tek uzun sıra mı?** Tek sıra geldiyse yeniden ürettirin — en-boy oranı büyüdükçe görsel yeniden sıkıştırılıp geliyor ve piksel ızgarası bozuluyor (bkz. [Düzen](#düzen-ızgara-tek-sıra-değil)).
2. **Görsele yakınlaşınca blok kenarları keskin mi?** Bulanıksa yeniden ürettirin; bu, araçların düzeltemediği tek kusur (bkz. [Render keskinliği](#render-keskinliği-kurtarılamayan-tek-kusur)).
3. **Kareler arasında gerçekten boş şerit var mı?** Yoksa ızgara ölçüsünü elle verin: `split_sheet --rows 2 --cols 4`.
4. **Kare sayısı ve sırası doğru mu?** Karakter değiştirme yönteminde Gemini bazen kare atlıyor ya da sırayı bozuyor. Izgarada okuma sırası soldan sağa, sonra alt satır.
5. **Karakter bütün karelerde aynı boyda mı?** Değilse `split_sheet` uyarı verir; düzeltmek için yeniden ürettirmek gerekir, araç ölçekleyemez.
6. **Yer gölgesi, çerçeve, numara, köşede parıltı var mı?** Varsa yeniden ürettirin — hepsi opak piksel olarak sprite'a karışır.
7. **Dama gerçekten magenta mı?** Gemini bazen istenen rengi görmezden gelip griye dönüyor. Gri geldiyse çalışır ama beyaz detaylar risk altındadır.
8. **Karakter değiştirme yaptıysanız:** poz referansındaki karakterin kıyafeti/saç rengi sızmış mı? Gemini iki referansı bazen karıştırıyor.

Sonra araçları çalıştırın — menüden (`npm run tools` → 1) ya da elle:

```bash
python3 tools/pixelart_extract.py sheet_ham.png sheet_native.png --verbose --verify
```

Çıktıda **önce native çözünürlüğe bakın**: 2048'lik bir canvas'tan 100×100 civarı beklenir. Araç size girdiyle aynı ölçüyü söylüyorsa ("Gorsel zaten native cozunurlukte gorunuyor") indirgeme hiç yapılmamıştır — görsel fazla gürültülüdür, sonuç kullanılamaz.

Sonra `--verify` çıktısındaki `3) Detay kaybi` satırı: çakışan hücre sayısı 0'a yakın olmalı. `4) Kaynak gurultusu` satırındaki palet, temiz bir render'da birkaç yüz renk mertebesinde kalır; on binlere çıkıyorsa kaynak yeniden sıkıştırılmış demektir.

Native çözünürlük beklediğinizden çok küçükse (ör. kare başına 40 pikselden az) Gemini'yi daha büyük canvas'a zorlayın ya da kareleri tek tek ürettirin.

```bash
python3 tools/split_sheet.py sheet_native.png -o kareler/ --frames 4 --preview bolme.png
```

```bash
python3 tools/pack_sheet.py kareler/kare_*.png -o walk_right_spritesheet.png --gif on.gif
```

`on.gif`'i açın. Titreme varsa `pack_sheet` çıktısındaki örtüşme yüzdelerine bakın: düşük olan kare ya farklı ölçekte üretilmiş ya da pozu diğerlerinden çok farklı.

Sheet'i `characters/` altına yerleştirip `meta.json` yazmak için: [README](README.md#yeni-karakter-ekleme). Doğrulamak için `npm run check`.
