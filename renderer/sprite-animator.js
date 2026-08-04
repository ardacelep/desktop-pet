/**
 * Yatay sprite sheet'ten canvas'a kare kare çizim yapan basit animatör.
 * Zamanlama requestAnimationFrame ile yürür; kare ilerlemesi geçen süreye bağlıdır,
 * böylece frame drop olsa da animasyon hızı sabit kalır.
 */
class SpriteAnimator {
  /** @param {HTMLCanvasElement} canvas */
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
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

/** Sprite sheet'leri önceden yükler. */
function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`Sprite yüklenemedi: ${src}`));
    img.src = src;
  });
}
