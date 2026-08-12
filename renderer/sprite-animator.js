/**
 * Yatay sprite sheet'ten canvas'a kare kare çizim yapan basit animatör.
 * Zamanlama requestAnimationFrame ile yürür; kare ilerlemesi geçen süreye bağlıdır,
 * böylece frame drop olsa da animasyon hızı sabit kalır.
 */
class SpriteAnimator {
  /** @param {HTMLCanvasElement} canvas */
  constructor(canvas) {
    this.canvas = canvas;
    // willReadFrequently: hit-test her mousemove'da getImageData ile canvas'tan
    // tek piksel okuyor; bu bayrak olmadan Chromium her okumada GPU'dan geri
    // kopyalama yapıp uyarı basıyor.
    this.ctx = canvas.getContext('2d', { willReadFrequently: true });
    this.ctx.imageSmoothingEnabled = false;

    /** @type {HTMLImageElement | null} */
    this.image = null;
    this.frameSize = canvas.width;
    this.frameCount = 1;
    this.frameDuration = 500;
    this.flip = false;

    this.frameIndex = 0;
    this.elapsed = 0;
  }

  /**
   * Çalınacak animasyonu değiştirir. Aynı klip yeniden verilirse kare sayacı korunur
   * (ör. sadece yön değişti, yürüyüş kesilmesin).
   * @param {{ image: HTMLImageElement, frameSize: number, frameCount: number, frameDuration: number, flip?: boolean, key?: string }} clip
   */
  setClip(clip) {
    const sameClip = this.key === clip.key;

    this.image = clip.image;
    this.frameSize = clip.frameSize;
    this.frameCount = clip.frameCount;
    this.frameDuration = clip.frameDuration;
    this.flip = Boolean(clip.flip);
    // GEÇİŞ klipleri döngü değil. 'otur' ayaktan oturmaya geçiyor; döngüye
    // alınınca pet sürekli oturup kalkıyor gibi görünüyor. loop:false olan
    // klip son karede DURUYOR.
    this.loop = clip.loop !== false;
    // TERS OYNATMA: 'kalk' klibi 'otur'un dosyasini geriye oynatiyor.
    // walk_left'in walk_right'i flip:true ile yeniden kullanmasiyla ayni
    // desen — ayri bir sprite sheet uretmeye gerek yok.
    this.reverse = Boolean(clip.reverse);
    // YOYO: ileri oyna, son karede `yoyo` ms bekle, sonra geri oyna ve dur.
    // El sallamada gerekiyordu: klip 980ms, REACT_DURATION 2600ms; tek-sefer
    // oynatinca el 1.6 saniye havada DONUYORDU.
    this.yoyo = Number(clip.yoyo) || 0;
    this.yon = 1;
    this.bekleme = 0;
    this.bitti = false;
    this.key = clip.key;

    if (!sameClip) {
      this.frameIndex = this.reverse ? this.frameCount - 1 : 0;
      this.elapsed = 0;
      this.yon = this.reverse ? -1 : 1;
      this.bekleme = 0;
      this.bitti = false;
    } else if (this.frameIndex >= this.frameCount) {
      this.frameIndex = 0;
    }

    this.canvas.width = this.frameSize;
    this.canvas.height = this.frameSize;
    this.ctx.imageSmoothingEnabled = false;
  }

  /** @param {number} dt geçen süre (ms) */
  update(dt) {
    if (!this.image || this.frameCount <= 1) return;
    if (this.loop && !this.yoyo) {
      this.elapsed += dt;
      while (this.elapsed >= this.frameDuration) {
        this.elapsed -= this.frameDuration;
        this.frameIndex = (this.frameIndex + 1) % this.frameCount;
      }
      return;
    }
    if (this.bitti) return;                       // son karede duruyor
    if (this.bekleme > 0) { this.bekleme -= dt; return; }

    this.elapsed += dt;
    while (this.elapsed >= this.frameDuration) {
      this.elapsed -= this.frameDuration;
      const sonraki = this.frameIndex + this.yon;
      if (sonraki >= 0 && sonraki < this.frameCount) {
        this.frameIndex = sonraki;
        continue;
      }
      // Uca gelindi
      if (this.yoyo && this.yon === 1) {
        this.bekleme = this.yoyo;                 // tepede bekle, sonra geri
        this.yon = -1;
        this.elapsed = 0;
        return;
      }
      if (this.loop) {
        // Yoyo + dongu: salinim tekrarlanıyor (uyku sırasında baş sallanması).
        // Bastan basla, yon ileri.
        this.frameIndex = this.reverse ? this.frameCount - 1 : 0;
        this.yon = this.reverse ? -1 : 1;
        this.bekleme = this.yoyo;
        this.elapsed = 0;
        return;
      }
      this.bitti = true;
      this.elapsed = 0;
      break;
    }
  }

  draw() {
    const { ctx, canvas, image, frameSize } = this;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!image || !image.complete) return;

    ctx.save();
    if (this.flip) {
      ctx.translate(canvas.width, 0);
      ctx.scale(-1, 1);
    }
    ctx.drawImage(
      image,
      this.frameIndex * frameSize, 0, frameSize, frameSize,
      0, 0, frameSize, frameSize
    );
    ctx.restore();
  }
}

/**
 * Bir sheet'teki TÜM karelerin opak piksellerini kapsayan sınır kutusunu ölçer.
 * Native piksel biriminde döner: { top, bottom, left, right }.
 *
 * Üç yerde gerekiyor ve üçü de aynı ölçümden besleniyor:
 *   - pencereyi karakterin gerçek boyuna göre ölçmek,
 *   - yürüme sınırlarını kare kutusuna değil karakterin kendisine dayamak
 *     (kutunun boş kenarı yüzünden pet ekran kenarına varamıyordu),
 *   - ayakların dock çizgisine tam oturması için alttaki payı bilmek.
 */
function measureContent(image, frameSize, frameCount) {
  const c = document.createElement('canvas');
  c.width = frameSize * frameCount;
  c.height = frameSize;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(image, 0, 0);

  const { data } = ctx.getImageData(0, 0, c.width, c.height);
  let top = frameSize, bottom = 0, left = frameSize, right = 0;

  for (let y = 0; y < c.height; y++) {
    for (let x = 0; x < c.width; x++) {
      if (data[(y * c.width + x) * 4 + 3] === 0) continue;
      const fx = x % frameSize; // kare içindeki sütun
      if (y < top) top = y;
      if (y + 1 > bottom) bottom = y + 1;
      if (fx < left) left = fx;
      if (fx + 1 > right) right = fx + 1;
    }
  }

  if (bottom === 0) return { top: 0, bottom: frameSize, left: 0, right: frameSize };
  return { top, bottom, left, right };
}

/** Sprite sheet'leri önceden yükler. */
function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`Sprite yüklenemedi: ${src}`));
    img.src = src;
  });
}
