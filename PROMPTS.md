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
| Karakterin canvas'ta ortalı olması | `pack_sheet` zaten içerikten hizalıyor | ✓ |
| Kareler arası aynı taban çizgisi | `pack_sheet` ayak çizgisine hizalıyor | ✓ |
| Kenar boşluğu miktarı | Kırpma hallediyor | ✓ |

Yani prompt'ta yer alması gereken şey, üstteki beş satır. Alttaki üçü eskiden zorunluydu, artık değil — REHBER.md'deki "%85 doldurmalı" gibi maddeleri prompt'a koymak sadece Gemini'nin dikkatini dağıtır.

## Dama rengi: gri değil, magenta

REHBER.md **açık tonlu** dama istiyordu; o, eski script nötr gri beklediği için doğruydu. Yeni script dama rengini kenardan ölçerek buluyor, dolayısıyla artık tersi geçerli: dama, karakterin paletinde **asla bulunmayacak** bir renk olmalı.

Ölçüm (saf beyaz içeren bir karakterle):

| Dama | Arka plan kalıntısı | Yenen karakter pikseli |
| --- | --- | --- |
| `#ffffff` / `#e1e1e1` | 0 | 1 |
| `#ff00ff` / `#c000c0` | 0 | 0 |
| `#b4f0c8` / `#8cd8a8` | 0 | 0 |

Yan fayda: `--fill-gaps` güvenli hale geliyor. Gri damada göz akı (254-255) damanın açık tonundan (253) ayırt edilemiyor ve boşluklarla birlikte siliniyor; magenta damada göz akı damaya 300 birim uzak, yani hiçbir zaman aday olmuyor.

## Düzen: 2×2 ızgara

Gemini kare canvas'ta daha tutarlı çalışıyor (REHBER.md, 1.1). `split_sheet.py` R×C ızgarayı zaten destekliyor, o yüzden 4 kareyi tek sıra yerine 2×2 dizmek hem Gemini için kolay hem bizim için sorunsuz.

**Bunun bedeli çözünürlük.** Tek kare üretiminde 2048'lik canvas'tan ~95 piksel boyunda karakter çıkıyor; 2×2 ızgarada her kareye 1024 düşüyor, yani yaklaşık yarısı. Karşılığında kareler **birbiriyle tutarlı** oluyor — REHBER.md 4.1'de tek tek üretimin en büyük sorunu buydu. Detay mı tutarlılık mı sorusunun cevabı karaktere göre değişir; ikisini de deneyip `pixelart_extract`'in bildirdiği native çözünürlüğe bakın.

---

## Walk cycle spritesheet (4 kare, 2×2)

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
- Gerçek pixel art: her piksel bloğu tek düz renk. Yumuşak geçiş, anti-aliasing,
  gradyan, bulanıklık ya da yarı saydam piksel YOK.
- Sınırlı palet (16-24 renk), net koyu kontur.
- Karakterin tasarımı (saç, gözlük, sakal, kıyafet, aksesuarlar, renkler)
  referanstakiyle birebir aynı kalmalı.
- Kolla gövde arasında 1-2 piksellik minik boşluklar bırakma: kol ya gövdeye
  değsin ya da arasında en az 4 piksellik net bir açıklık olsun.

Çıktıyı yüksek çözünürlüklü PNG olarak ver.
```

## Idle spritesheet (4 kare, 2×2)

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

REHBER.md 4.2'deki tuzak burada da geçerli: "nefes alma" belirsiz tarif edilirse Gemini tüm karakteri ölçekliyor. Piksel cinsinden kesin talimat şart.

## Üretim sonrası kontrol listesi

Pipeline'a sokmadan önce görsele bakıp şunları doğrulayın:

1. **Kareler arasında gerçekten boş şerit var mı?** Yoksa `split_sheet --rows 2 --cols 2` ile eşit bölmek gerekir.
2. **Karakter dört karede de aynı boyda mı?** Değilse `split_sheet` uyarı verir; düzeltmek için yeniden ürettirmek gerekir, araç ölçekleyemez.
3. **Yer gölgesi, çerçeve, numara var mı?** Varsa yeniden ürettirin — bunlar opak piksel olarak sprite'a karışır.
4. **Dama gerçekten magenta mı?** Gemini bazen istenen rengi görmezden gelip griye dönüyor. Gri geldiyse çalışır ama beyaz detaylar risk altındadır.

Sonra:

```bash
python3 tools/pixelart_extract.py sheet_ham.png sheet_native.png --verbose --verify
```

`--verify` çıktısındaki "gercek detay kaybi" satırı 0'a yakın olmalı. Native çözünürlük beklediğinizden çok küçükse (ör. kare başına 40 pikselden az) Gemini'yi daha büyük canvas'a zorlayın ya da kareleri tek tek ürettirin.

```bash
python3 tools/split_sheet.py sheet_native.png -o kareler/ --frames 4 --preview bolme.png
```

```bash
python3 tools/pack_sheet.py kareler/kare_*.png -o walk_right_spritesheet.png --gif on.gif
```

`on.gif`'i açın. Titreme varsa `pack_sheet` çıktısındaki örtüşme yüzdelerine bakın: düşük olan kare ya farklı ölçekte üretilmiş ya da pozu diğerlerinden çok farklı.

## Temel karakter prompt'u

Tek bir karakteri sıfırdan üretmek için REHBER.md 1.2'deki prompt hâlâ geçerli, iki değişiklikle:

- **Dama rengini değiştirin:** "açık tonlu (#FFFFFF ve #E0E0E0)" yerine "#FF00FF ve #C000C0 magenta".
- **Beyaz kıyafet yasağını kaldırabilirsiniz.** O kısıt, gri damanın beyaz kıyafeti yemesi yüzünden vardı; magenta damayla ölçülen kayıp sıfır.

Kare canvas ve "%85 doldur" maddeleri zararsız ama artık gerekli değil — kırpma ve hizalama bunu hallediyor.
