/**
 * Piksel metin motoru.
 *
 * Neden ayrı bir motor: Pixelify Sans bir outline fontu, gerçek bitmap değil.
 * Glif koordinatları hiçbir piksel ızgarasına oturmuyor (bbox koordinatlarının
 * GCD'si 1), bu yüzden tarayıcı metni her boyutta antialias ediyor. O gri
 * kenarları native çözünürlükte bırakıp sonra nearest-neighbor ile 3x büyütürsek
 * griler de büyür ve pixel art'ın yanında kirli durur.
 *
 * Çözüm: metni native boyutta çiz, alfayı EŞİKLE (yarıdan koyu -> tam opak,
 * gerisi -> şeffaf), yani fontu çalışma anında bitmap'e çevir. Ölçekleme bundan
 * SONRA, karakterle aynı katsayıyla yapılır.
 *
 * FONT_PX neden 10: 6-8px'te eşikleme sonrası ı/İ/ğ/ş ayırt edilemiyor (ölçüldü,
 * render karşılaştırmasıyla). 10px ilk temiz boyut.
 */

const FONT_AILE = 'PixelifySans';
const FONT_DOSYA = 'fonts/PixelifySans.ttf';

/** Native piksel cinsinden font boyutu. Ölçekleme bu değerin üstüne uygulanır. */
const FONT_PX = 10;
/** Satır aralığı (native px). Fontun 10px gövdesi + 2px nefes payı. */
const SATIR_YUKSEKLIGI = 12;
/** Alfa eşiği: bunun altı tamamen şeffaf, üstü tamamen opak olur. */
const ESIK = 110;

class PixelText {
  constructor() {
    /** Ölçüm için kullanılan hafif kanvas — çizim yapmaz, sadece measureText. */
    this.olcek = document.createElement('canvas').getContext('2d');
    /** Metnin eşiklendiği ara kanvas; her çizimde yeniden boyutlanır. */
    this.ara = document.createElement('canvas');
    this.araCtx = this.ara.getContext('2d', { willReadFrequently: true });
    this.hazir = false;
  }

  /** Fontu yükler. CSP'de font-src 'self' olmadan sessizce başarısız olur. */
  async yukle() {
    const f = new FontFace(FONT_AILE, `url(${FONT_DOSYA})`, { weight: '400 700' });
    await f.load();
    document.fonts.add(f);
    // measureText'in doğru sonuç vermesi için font gerçekten hazır olmalı
    await document.fonts.load(`${FONT_PX}px ${FONT_AILE}`);
    this.olcek.font = `${FONT_PX}px ${FONT_AILE}`;
    this.hazir = true;
  }

  /** @param {string} metin @returns {number} native px genişlik */
  satirGenisligi(metin) {
    this.olcek.font = `${FONT_PX}px ${FONT_AILE}`;
    return Math.ceil(this.olcek.measureText(metin).width);
  }

  /**
   * Metni maxGenislik'e sığacak satırlara böler.
   * Tek bir kelime bile sığmıyorsa taşmasına izin verir — kelimeyi ortadan
   * kesmek pixel art balonda daha kötü duruyor.
   *
   * @returns {{ satirlar: string[], genislik: number, yukseklik: number }}
   */
  olc(metin, maxGenislik) {
    const kelimeler = String(metin).split(/\s+/).filter(Boolean);
    const satirlar = [];
    let aktif = '';

    for (const k of kelimeler) {
      const aday = aktif ? `${aktif} ${k}` : k;
      if (aktif && this.satirGenisligi(aday) > maxGenislik) {
        satirlar.push(aktif);
        aktif = k;
      } else {
        aktif = aday;
      }
    }
    if (aktif) satirlar.push(aktif);
    if (!satirlar.length) satirlar.push('');

    return {
      satirlar,
      genislik: Math.max(...satirlar.map((s) => this.satirGenisligi(s))),
      yukseklik: satirlar.length * SATIR_YUKSEKLIGI
    };
  }

  /**
   * Satırları hedef kanvasa NATIVE çözünürlükte, eşiklenmiş olarak yazar.
   * Çağıran ctx'i ölçeklememeli — ölçek dışarıda, kanvasın CSS boyutuyla.
   *
   * @param {CanvasRenderingContext2D} hedef
   * @param {string[]} satirlar
   * @param {number} x sol kenar (native px)
   * @param {number} y üst kenar (native px)
   * @param {[number, number, number]} renk
   */
  ciz(hedef, satirlar, x, y, renk) {
    const g = Math.max(1, Math.max(...satirlar.map((s) => this.satirGenisligi(s))));
    const h = Math.max(1, satirlar.length * SATIR_YUKSEKLIGI);

    if (this.ara.width !== g || this.ara.height !== h) {
      this.ara.width = g;
      this.ara.height = h;
    }
    this.araCtx.clearRect(0, 0, g, h);
    this.araCtx.font = `${FONT_PX}px ${FONT_AILE}`;
    this.araCtx.textBaseline = 'top';
    this.araCtx.fillStyle = '#000';

    satirlar.forEach((s, i) => {
      // Satırı kendi içinde ortala — balon simetrik dursun
      const ofs = Math.round((g - this.satirGenisligi(s)) / 2);
      this.araCtx.fillText(s, ofs, i * SATIR_YUKSEKLIGI + 1);
    });

    const veri = this.araCtx.getImageData(0, 0, g, h);
    const d = veri.data;
    const [kr, kg, kb] = renk;
    for (let i = 0; i < d.length; i += 4) {
      if (d[i + 3] >= ESIK) {
        d[i] = kr; d[i + 1] = kg; d[i + 2] = kb; d[i + 3] = 255;
      } else {
        d[i + 3] = 0;
      }
    }
    this.araCtx.putImageData(veri, 0, 0);

    hedef.drawImage(this.ara, Math.round(x), Math.round(y));
  }
}

PixelText.FONT_PX = FONT_PX;
PixelText.SATIR_YUKSEKLIGI = SATIR_YUKSEKLIGI;
