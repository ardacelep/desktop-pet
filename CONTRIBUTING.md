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
- Piksel sanatı ölçeklenirken bulanıklaşır: `displayHeight`'i `nativeFrameSize` ile aynı ya da tam katı tut

Klasör adları için küçük harf + ASCII kullan (`karakter2`, `kedi`). macOS büyük/küçük harfe duyarsız ama Linux (ve CI) duyarlı — `Kedi` ile `kedi` orada iki ayrı klasör olur.

## Kod değişiklikleri

| Dosya | Sorumluluk |
| --- | --- |
| `main.js` | Pencere, tray, menü, IPC, kalıcılık, karakter keşfi |
| `preload.js` | Renderer'a açılan API yüzeyi |
| `renderer/pet.js` | Durum makinesi ve davranış |
| `renderer/sprite-animator.js` | Kare çizimi |
| `renderer/speech-bubble.js` | Konuşma balonu |

Renderer'ın Node'a doğrudan erişimi yok (`contextIsolation` açık). Yeni bir ana süreç yeteneği gerekiyorsa `preload.js`'e açıkça eklenmeli.

Kod stili: 2 boşluk girinti, tek tırnak, noktalı virgül. Yorumlar Türkçe ve **niçin**'i anlatsın — ne yaptığı zaten kodda yazıyor.

## Commit ve PR

- Commit mesajı Türkçe, ilk satır 72 karakteri geçmesin, emir kipi:
  `Kedi karakteri ekle`, `Yürüme hızını meta.json'a taşı`
- PR'da karakter eklediysen ekran görüntüsü ya da kısa bir kayıt ekle — sprite'ın gerçekten doğru çizildiğini gözle görmek en hızlı kontrol
- PR açmadan önce `npm run check` yeşil olsun

## Çakışma çıkarsa

PNG dosyaları ikili; Git bunları birleştiremez. İki kişi aynı sprite'ı düzenlediyse conflict'i elle çözmek yerine hangi sürümün kalacağına karar verin:

```bash
git checkout --ours characters/<ad>/<dosya>.png
```

```bash
git checkout --theirs characters/<ad>/<dosya>.png
```

Herkes kendi klasöründe çalıştığı sürece bu durum pratikte oluşmaz.
