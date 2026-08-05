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
    this.key = clip.key;

    if (!sameClip) {
      this.frameIndex = 0;
      this.elapsed = 0;
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
    this.elapsed += dt;
    while (this.elapsed >= this.frameDuration) {
      this.elapsed -= this.frameDuration;
      this.frameIndex = (this.frameIndex + 1) % this.frameCount;
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
