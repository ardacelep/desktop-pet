# Desktop Pet — Mimari Plan (Electron)

## Hedefler
- Windows + macOS'ta çalışan, şeffaf/çerçevesiz, her zaman üstte bir masaüstü pet uygulaması
- Başlangıçta tek karakter, ama karakter ekleme/değiştirme kolay olacak şekilde yapılandırılmış
- Etkileşimler: sürükle-bırak, tıklayınca konuşma balonu, sağ tık menü, ekran kenarında yürüme/dönme

---

## 1. Proje Yapısı

```
desktop-pet/
├── package.json
├── main.js                    # Electron ana süreç (pencere yönetimi, tray, IPC)
├── preload.js                 # Renderer <-> main köprüsü (contextBridge)
├── renderer/
│   ├── index.html
│   ├── pet.js                 # Sprite/animasyon motoru, davranış state machine
│   ├── pet.css
│   └── speech-bubble.js       # Tıklama reaksiyonu UI'ı
├── characters/
│   ├── characters.json        # Karakter kayıt defteri (aşağıda detay)
│   └── <karakter-adi>/
│       ├── idle_spritesheet.png
│       ├── walk_right_spritesheet.png
│       ├── walk_left_spritesheet.png   # (flip ile üretilen versiyon)
│       └── meta.json           # bu karaktere özel frame boyutu, kare sayısı vb.
└── build/                      # electron-builder ikon/config dosyaları
```

### `characters/characters.json` örneği
```json
{
  "active": "karakter7",
  "list": [
    {
      "id": "karakter7",
      "displayName": "Arkadaş 1",
      "folder": "karakter7",
      "nativeFrameSize": 88,
      "displayHeight": 80
    }
  ]
}
```

**Önemli:** Farklı karakterlerin native sprite çözünürlüğü farklı olabilir (biz üretim sırasında bazı karakterleri 88x88, hacimli saçlı olanı 140x140 yapmıştık). `nativeFrameSize` + `displayHeight` ayrımı sayesinde, dosya çözünürlüğü ne olursa olsun ekranda hepsi aynı boyutta görünür (CSS `transform: scale()` ile normalize edilir).

### `meta.json` örneği (her karakter klasöründe)
```json
{
  "idle": { "frameSize": 88, "frameCount": 4, "frameDuration": 500 },
  "walk_right": { "frameSize": 88, "frameCount": 7, "frameDuration": 150 },
  "walk_left": { "frameSize": 88, "frameCount": 7, "frameDuration": 150 }
}
```

---

## 2. Pencere Yönetimi (main.js)

Kritik `BrowserWindow` ayarları:
```js
new BrowserWindow({
  width: 200, height: 200,
  frame: false,
  transparent: true,
  alwaysOnTop: true,
  skipTaskbar: true,
  hasShadow: false,
  resizable: false,
  webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true }
})
```

**Platform notları:**
- macOS: `win.setAlwaysOnTop(true, 'floating')` — normal `alwaysOnTop` bazen Dock/menu bar'ın altında kalabiliyor, `'floating'` seviyesi daha güvenilir.
- Windows: `skipTaskbar: true` olmazsa taskbar'da boş bir pencere ikonu görünür, pet'in ruhuna aykırı.
- **Tıklama geçirgenliği:** Pet'in olmadığı şeffaf alanlarda tıklamaların arkadaki uygulamalara geçmesini istersen `win.setIgnoreMouseEvents(true, { forward: true })` kullan, ama bu sürükleme/tıklama etkileşimini karmaşıklaştırır — basit başlangıç için bunu KULLANMA, pencereyi sprite boyutuna yakın küçük tut (200x200 gibi), böylece şeffaf alan zaten minimal olur.

---

## 3. Sprite/Animasyon Motoru (renderer/pet.js)

**Yaklaşım:** `<canvas>` üzerinde sprite sheet'ten kare kare çizim (CSS `background-position` yerine canvas tercih et — flip/scale gibi işlemler canvas'ta daha kontrollü).

```js
class SpriteAnimator {
  constructor(canvas, spriteSheetImg, frameSize, frameCount, frameDuration) { ... }
  play() { /* setInterval veya requestAnimationFrame ile frame ilerlet */ }
  setSpriteSheet(img, frameSize, frameCount) { /* state değişince kaynağı değiştir */ }
}
```

**State Machine (durum makinesi):**
```
IDLE ──(rastgele zamanlayıcı tetikler)──> WALKING
WALKING ──(hedef X'e ulaşınca)──> IDLE
WALKING ──(ekran kenarına çarpınca)──> yön değiştir, WALKING'de kal
* ──(mouse down + sürükleme)──> DRAGGING
DRAGGING ──(mouse up)──> IDLE
* ──(tıklama, sürükleme değilse)──> REACTING (kısa süreli, sonra önceki state'e döner)
```

**Yön mantığı:** `walk_left` spritesheet'i, sende zaten hazır olan `walk_right` görsellerinin **CSS/canvas transform ile flip edilmiş hali**. İki ayrı dosya tutmak yerine, tek `walk_right` seti + runtime'da `ctx.scale(-1,1)` ile flip etmek dosya sayısını yarıya indirir — tercih sana kalmış, ikisi de çalışır.

---

## 4. Davranış (Behavior AI)

Basit ama etkili bir "rastgele gezinme" mantığı:

```js
function pickNewWalkTarget() {
  const screenWidth = screen.getPrimaryDisplay().workAreaSize.width;
  const currentX = window.getPosition()[0];
  const targetX = Math.random() * screenWidth;
  const direction = targetX > currentX ? 'right' : 'left';
  // WALKING state'e geç, her frame'de currentX'i targetX'e yaklaştır
}
```

**Ekran kenarı davranışı:** Pencere X koordinatı ekran genişliğinin (ya da çoklu monitör senaryosunda ilgili monitörün) sınırına ulaşınca yön tersine çevrilir — basit "duvara çarpıp dönme" hissi.

**Zemin/Y koordinatı:** Başlangıç için pet'i ekranın altına (taskbar/dock üstü) sabitle, sadece X ekseninde hareket etsin — dikey fizik (zıplama, düşme) sonraki bir iterasyon olabilir.

**Çoklu monitör:** `screen.getAllDisplays()` ile tüm monitörleri al, pet'in hangi monitörde olduğunu `screen.getDisplayNearestPoint()` ile takip et — ilerisi için önemli ama MVP'de tek monitör varsayımıyla başlamak sorun değil.

---

## 5. Etkileşimler

**Sürükle-bırak:** Renderer'da `mousedown` → sürükleme moduna geç, `mousemove` sırasında `ipcRenderer.send('move-window', {x,y})` ile main sürece pencere pozisyonunu güncelletir (`win.setPosition`).

**Tıklama → konuşma balonu:** Sürükleme olmadan kısa bir tıklama algılanırsa (mousedown+mouseup arası hareket az ve süre kısaysa), küçük bir HTML overlay (konuşma balonu) 2-3 saniyeliğine göster, rastgele bir repertuardan cümle seç.

**Sağ tık menüsü:** Electron `Menu.buildFromTemplate([...])` + `menu.popup()` — "Karakter Değiştir", "Ayarlar", "Çıkış" gibi seçenekler. Karakter değiştirme, ileride çoklu karakter listesinden seçim yapılacağı yer.

**Sistem tepsisi (opsiyonel ama önerilir):** `Tray` API ile menü çubuğunda/sistem tepsisinde bir ikon — pet'i gizle/göster, ayarlara eriş gibi kontroller için pencereye bağımlı olmayan bir erişim noktası sağlar.

---

## 6. Kalıcılık (Persistence)

`electron-store` paketiyle basit bir tercih dosyası:
- Son pencere pozisyonu
- Aktif karakter ID'si
- Ses/animasyon hız ayarları (varsa)

---

## 7. Çoklu Karakter Genişletilebilirliği (şimdi değil, ama yapıyı buna göre kur)

- `characters.json` zaten bir liste olarak tasarlandı — yeni karakter eklemek yeni bir klasör + JSON kaydı eklemekten ibaret olmalı
- Pet mantığını bir `Pet` sınıfı olarak yaz (state, pozisyon, sprite seti kendi içinde), ileride "birden fazla pet aynı anda" istenirse, her biri kendi `BrowserWindow` + kendi `Pet` instance'ı olacak şekilde çoğaltılabilir
- Şimdilik `main.js` tek bir pencere/pet oluştursun, ama pencere oluşturma kodunu bir fonksiyona (`createPetWindow(characterId)`) ayır — ileride bunu bir döngüde çağırmak yeterli olur

---

## 8. Paketleme

`electron-builder` ile:
```json
"build": {
  "appId": "com.senin.desktoppet",
  "mac": { "target": "dmg", "category": "public.app-category.entertainment" },
  "win": { "target": "nsis" }
}
```
Windows build'i macOS'tan doğrudan üretmek sorunlu olabilir (code signing vs.) — pratikte her platformu kendi işletim sisteminde build etmek en güvenilir yol, ya da GitHub Actions gibi bir CI ile cross-platform build otomasyonu kurulabilir (ileri seviye, şimdilik gerekmez).

---

## 9. Önerilen Yapım Sırası (Claude Code'a bu sırayla görev verilebilir)

1. Boş Electron projesi + şeffaf/çerçevesiz/her zaman üstte pencere (statik tek kare göster, hareket yok)
2. Idle animasyonu çalıştır (4 kare, sprite sheet'ten canvas'a çizim)
3. Sürükle-bırak ekle
4. Rastgele yürüme davranışı + walk spritesheet entegrasyonu + ekran kenarı dönüşü
5. Tıklama → konuşma balonu
6. Sağ tık menü (şimdilik sadece "Çıkış" yeterli, "Karakter Değiştir" iskelet olarak dursun)
7. Pozisyon kalıcılığı (electron-store)
8. Paketleme testi (en az kendi işletim sisteminde .app/.exe üretimi)

---

## Hazır Assetler (bu konuşmadan)
- `idle_spritesheet.png` — 4 kare, 88x88 her biri (352x88 toplam)
- Walk cycle — 7 kare, 88x88 (sağa yürüyüş), sola yürüyüş için flip kullanılabilir
- Script: `pixelart_temizle.py` — yeni karakterler eklenecekse, Gemini çıktısını bu pipeline'dan geçirip aynı formatta (88x88, şeffaf arka plan, kare canvas) hazırlamak için kullanılabilir
