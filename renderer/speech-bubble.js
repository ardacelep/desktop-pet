/* global PixelText, loadImage */

/**
 * Pet'in üstünde beliren piksel konuşma balonu.
 *
 * Balon karakterle AYNI piksel ızgarasında yaşıyor: native çözünürlükte çizilip
 * karakterin `scale` katsayısıyla büyütülüyor. Farklı ölçekte çizilseydi iki ayrı
 * "piksel boyutu" görünür ve balon karakterin üstüne yapıştırılmış gibi dururdu.
 *
 * Çerçeve 9-slice: köşeler sabit, kenarlar TILE ediliyor (stretch değil).
 * Stretch, düz kenarlı bir balonda fark ettirmez ama kenara doku çizildiği anda
 * pikselleri ezer — tile, asset'i değiştirme özgürlüğünü koruyor.
 */

/** 9-slice köşe boyutu (native px) — bubble.png 32x12 içinde 5px köşe. */
const KOSE = 5;
/** Metin ile çerçeve arası iç boşluk (native px). */
const IC_PAY_X = 5;
const IC_PAY_Y = 4;
/** Balonun taşabileceği azami native genişlik. */
const MAX_GENISLIK = 104;

const RENK_METIN = [43, 43, 58];

/**
 * Açılış/kapanış "pop" adımları. Ölçek DEĞİL kutu boyutu değişiyor: 9-slice her
 * boyutta 1:1 çizdiği için çerçeve hiçbir adımda bulanıklaşmıyor. 1.08'lik
 * taşma, piksel animasyonundaki klasik squash hissini veriyor.
 */
const ACILIS = [0.35, 0.72, 1.08, 1];
const KAPANIS = [1, 0.6, 0.25];
const POP_KARE_SURE = 45;

const DURUM = { GIZLI: 'gizli', ACILIYOR: 'aciliyor', ACIK: 'acik', KAPANIYOR: 'kapaniyor' };

class SpeechBubble {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {PixelText} metinMotoru
   */
  constructor(canvas, metinMotoru) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.ctx.imageSmoothingEnabled = false;
    this.metinMotoru = metinMotoru;

    this.durum = DURUM.GIZLI;
    this.satirlar = [];
    /** Metnin gerektirdiği tam (native) kutu — pop bunun oranıyla çalışıyor. */
    this.hedef = { genislik: 0, yukseklik: 0 };
    this.karesi = 0;
    this.kareSayaci = 0;
    this.kalanSure = 0;
    this.yon = 1;
    this.cerceve = null;
    this.kuyruk = null;
    /**
     * Kuyruğun balonun altına eklediği pay. Asset yüksekliğinden 1 eksik:
     * kuyruğun en üst satırı gövdenin alt hattını KESİYOR (o satırda hat yerine
     * dolgu var), yani hattın üstüne biniyor, altına eklenmiyor.
     */
    this.kuyrukPay = 0;
  }

  async yukle() {
    [this.cerceve, this.kuyruk] = await Promise.all([
      loadImage('ui/bubble.png'),
      loadImage('ui/bubble_tail.png')
    ]);
    this.kuyrukPay = this.kuyruk.height - 1;
  }

  /**
   * Bir metnin native kutu ölçüsü. Pencere boyutu buna göre ayrıldığı için
   * karakterin TÜM replikleri önceden ölçülüp en büyüğü alınıyor; balon her
   * repliğe göre pencereyi yeniden boyutlandırsaydı pet ekranda titrerdi.
   */
  olc(metin) {
    const m = this.metinMotoru.olc(metin, MAX_GENISLIK - 2 * IC_PAY_X);
    return {
      genislik: Math.max(2 * KOSE + 2, m.genislik + 2 * IC_PAY_X),
      yukseklik: Math.max(2 * KOSE + 2, m.yukseklik + 2 * IC_PAY_Y) + this.kuyrukPay,
      satirlar: m.satirlar,
      metin: { genislik: m.genislik, yukseklik: m.yukseklik }
    };
  }

  /** Replik listesinin en geniş ve en yüksek kutusu — pencere payı için. */
  enBuyukKutu(satirlar) {
    let g = 0;
    let y = 0;
    for (const s of satirlar) {
      const o = this.olc(s);
      g = Math.max(g, o.genislik);
      y = Math.max(y, o.yukseklik);
    }
    return { genislik: g, yukseklik: y };
  }

  /** @param {string} metin @param {number} sure ms @param {number} yon 1 sağ, -1 sol */
  show(metin, sure, yon = 1) {
    const o = this.olc(metin);
    this.satirlar = o.satirlar;
    this.hedef = { genislik: o.genislik, yukseklik: o.yukseklik };
    // Her karede yeniden ölçmemek için sakla — satır sarma measureText çağırıyor.
    this.metinKutu = o.metin;
    this.yon = yon;
    this.durum = DURUM.ACILIYOR;
    this.karesi = 0;
    this.kareSayaci = 0;
    this.kalanSure = sure;
  }

  hide() {
    if (this.durum === DURUM.GIZLI || this.durum === DURUM.KAPANIYOR) return;
    this.durum = DURUM.KAPANIYOR;
    this.karesi = 0;
    this.kareSayaci = 0;
  }

  get gorunur() {
    return this.durum !== DURUM.GIZLI;
  }

  /**
   * Zamanı ilerletir. setTimeout yerine dt tabanlı: pencere arka plana düşünce
   * rAF donduruluyor ve timer tabanlı bir balon geri gelindiğinde çoktan
   * kaçırılmış oluyordu.
   */
  update(dt) {
    if (this.durum === DURUM.GIZLI) return;

    if (this.durum === DURUM.ACILIYOR || this.durum === DURUM.KAPANIYOR) {
      this.kareSayaci += dt;
      while (this.kareSayaci >= POP_KARE_SURE) {
        this.kareSayaci -= POP_KARE_SURE;
        this.karesi++;
        const dizi = this.durum === DURUM.ACILIYOR ? ACILIS : KAPANIS;
        if (this.karesi >= dizi.length) {
          this.durum = this.durum === DURUM.ACILIYOR ? DURUM.ACIK : DURUM.GIZLI;
          this.karesi = 0;
          break;
        }
      }
      return;
    }

    this.kalanSure -= dt;
    if (this.kalanSure <= 0) this.hide();
  }

  /** Pop adımına göre o anki native kutu. */
  suankiKutu() {
    let oran = 1;
    if (this.durum === DURUM.ACILIYOR) oran = ACILIS[Math.min(this.karesi, ACILIS.length - 1)];
    else if (this.durum === DURUM.KAPANIYOR) oran = KAPANIS[Math.min(this.karesi, KAPANIS.length - 1)];

    const gövde = this.hedef.yukseklik - this.kuyrukPay;
    return {
      genislik: Math.max(2 * KOSE + 2, Math.round(this.hedef.genislik * oran)),
      gövde: Math.max(2 * KOSE + 2, Math.round(gövde * oran)),
      tam: oran === 1
    };
  }

  /**
   * Kanvası native çözünürlükte çizer. Ölçekleme kanvasın CSS boyutuyla
   * yapılıyor, burada değil — ctx.scale kullanmak metni yeniden örnekletirdi.
   */
  ciz() {
    const c = this.ctx;
    // canvas.width'e yazmak ctx durumunu sıfırlıyor (pet.js balon kutusu
    // değişince yazıyor), o yüzden her karede yeniden kapatıyoruz.
    c.imageSmoothingEnabled = false;
    c.clearRect(0, 0, this.canvas.width, this.canvas.height);
    if (this.durum === DURUM.GIZLI || !this.cerceve) return;

    const k = this.suankiKutu();
    // Kutu alt-ortadan büyüyor: kuyruk pet'e sabit kalsın, balon ondan doğsun.
    const x = Math.round((this.canvas.width - k.genislik) / 2);
    const gövdeAlt = this.canvas.height - this.kuyrukPay;
    const y = gövdeAlt - k.gövde;

    this.dokuzDilim(x, y, k.genislik, k.gövde);

    // Kuyruk yalnızca balon tam açıkken — yarı boyutta balonun altında yüzerdi
    if (k.tam) {
      const kx = Math.round(this.canvas.width / 2 - this.kuyruk.width / 2);
      // 1px yukarı: kuyruğun üst satırı gövdenin alt hattının üstüne binip
      // oradan ağzı açıyor. Hattın altına çizilseydi balon kapalı kalır,
      // kuyruk ayrı bir parça gibi dururdu.
      const ky = gövdeAlt - 1;
      c.save();
      if (this.yon < 0) {
        c.translate(kx + this.kuyruk.width, ky);
        c.scale(-1, 1);
        c.drawImage(this.kuyruk, 0, 0);
      } else {
        c.drawImage(this.kuyruk, kx, ky);
      }
      c.restore();

      const m = this.metinKutu;
      const mx = x + Math.round((k.genislik - m.genislik) / 2);
      const my = y + Math.round((k.gövde - m.yukseklik) / 2);
      this.metinMotoru.ciz(c, this.satirlar, mx, my, RENK_METIN);
    }
  }

  /**
   * 9-slice: köşeler 1:1, kenarlar ve orta TILE edilerek çizilir.
   * Kenar dilimi tam sığmadığında son parça kırpılıyor — bu yüzden asset'in
   * kenar dokusu kendi kendine dikişsiz tekrarlanabilir olmalı.
   */
  dokuzDilim(x, y, w, h) {
    const c = this.ctx;
    const im = this.cerceve;
    const iw = im.width;
    const ih = im.height;
    const dw = iw - 2 * KOSE; // orta dilim genişliği
    const dh = ih - 2 * KOSE;

    // köşeler
    c.drawImage(im, 0, 0, KOSE, KOSE, x, y, KOSE, KOSE);
    c.drawImage(im, iw - KOSE, 0, KOSE, KOSE, x + w - KOSE, y, KOSE, KOSE);
    c.drawImage(im, 0, ih - KOSE, KOSE, KOSE, x, y + h - KOSE, KOSE, KOSE);
    c.drawImage(im, iw - KOSE, ih - KOSE, KOSE, KOSE, x + w - KOSE, y + h - KOSE, KOSE, KOSE);

    const icW = w - 2 * KOSE;
    const icH = h - 2 * KOSE;

    // üst ve alt kenar
    for (let o = 0; o < icW; o += dw) {
      const p = Math.min(dw, icW - o);
      c.drawImage(im, KOSE, 0, p, KOSE, x + KOSE + o, y, p, KOSE);
      c.drawImage(im, KOSE, ih - KOSE, p, KOSE, x + KOSE + o, y + h - KOSE, p, KOSE);
    }
    // sol ve sağ kenar
    for (let o = 0; o < icH; o += dh) {
      const p = Math.min(dh, icH - o);
      c.drawImage(im, 0, KOSE, KOSE, p, x, y + KOSE + o, KOSE, p);
      c.drawImage(im, iw - KOSE, KOSE, KOSE, p, x + w - KOSE, y + KOSE + o, KOSE, p);
    }
    // orta
    for (let oy = 0; oy < icH; oy += dh) {
      const ph = Math.min(dh, icH - oy);
      for (let ox = 0; ox < icW; ox += dw) {
        const pw = Math.min(dw, icW - ox);
        c.drawImage(im, KOSE, KOSE, pw, ph, x + KOSE + ox, y + KOSE + oy, pw, ph);
      }
    }
  }
}

SpeechBubble.MAX_GENISLIK = MAX_GENISLIK;
