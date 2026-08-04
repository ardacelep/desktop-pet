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
│   └── check-characters.js # Karakter doğrulayıcı (npm run check)
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

Karakterin **sağa bakıyor** olması gerekir — sola yürüyüş `flip` ile üretilir. Sola bakan bir sheet çizdiyseniz `walk_right`'a `"flip": true`, `walk_left`'e `false` verin.

`characters/characters.json` yalnızca ilk kurulumda hangi karakterle başlanacağını tutar; yeni karakter eklerken bu dosyaya dokunmayın.

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
