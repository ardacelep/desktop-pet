/**
 * Piksel konuşma balonunun regresyon testi.
 *
 *   npm run check:bubble
 *
 * Balonun bozulma biçimi sessiz: ölçek yanlışsa ya da kanvas fiziksel piksel
 * ızgarasına oturmazsa balon "biraz bulanık" görünür, hata vermez. Gözle fark
 * etmek zor olduğu için burada sayıyla ölçüyoruz:
 *
 *  1) balon kanvası NATIVE çözünürlükte mi (CSS ile büyütülüyor mu)
 *  2) CSS boyutu karakterin ölçeğiyle birebir mi (iki ayrı piksel boyutu olmasın)
 *  3) kenarları fiziksel piksele oturuyor mu (yarım piksel -> yeniden örnekleme)
 *  4) balon pencerenin içinde mi (kırpılıyor mu)
 *  5) metin EŞİKLENMİŞ mi — ara alfa değeri kalmışsa font bitmap'e çevrilmemiş
 *     demektir ve büyütmede gri kenarlar çıkar
 *
 * Ayrıca pencerenin ekran görüntüsünü kaydediyor: sayıların yakalayamadığı
 * yerleşim hatalarına (balon başın içine girmiş, kuyruk kaymış) gözle bakmak için.
 */

const path = require('path');
const fs = require('fs');

async function calistir(win, _okuDurum, app) {
  await new Promise((r) => setTimeout(r, 2500)); // karakter + font yüklensin

  let hata = 0;
  const bildir = (ok, mesaj) => {
    if (!ok) hata++;
    console.log(`SELFTEST ${ok ? 'OK  ' : 'HATA'} ${mesaj}`);
  };

  // Balonu tetikle ve pop animasyonunun bitmesini bekle
  await win.webContents.executeJavaScript(
    `window.__pet.react(), window.__pet.bubble.durum`
  );
  await new Promise((r) => setTimeout(r, 600));

  const o = await win.webContents.executeJavaScript(`(() => {
    const p = window.__pet;
    const b = document.getElementById('bubble');
    const r = b.getBoundingClientRect();
    const ctx = b.getContext('2d', { willReadFrequently: true });
    const d = ctx.getImageData(0, 0, b.width, b.height).data;

    let bos = 0, tam = 0, ara = 0;
    for (let i = 3; i < d.length; i += 4) {
      if (d[i] === 0) bos++;
      else if (d[i] === 255) tam++;
      else ara++;
    }
    return {
      dpr: devicePixelRatio,
      scale: p.scale,
      durum: p.bubble.durum,
      satirlar: p.bubble.satirlar,
      kutu: p.bubbleBox,
      kanvas: { w: b.width, h: b.height },
      css: { left: r.left, top: r.top, w: r.width, h: r.height },
      pencere: { w: innerWidth, h: innerHeight },
      fontVar: document.fonts.check('10px PixelifySans'),
      alfa: { bos, tam, ara },
      petCss: (() => { const q = document.getElementById('pet').getBoundingClientRect();
                       return { left: q.left, top: q.top, w: q.width, h: q.height }; })()
    };
  })()`);

  console.log(`SELFTEST dpr=${o.dpr} scale=${o.scale} durum=${o.durum}`);
  console.log(`SELFTEST replik: ${JSON.stringify(o.satirlar)}`);
  console.log(`SELFTEST balon native ${o.kanvas.w}x${o.kanvas.h}, `
    + `CSS ${o.css.w}x${o.css.h} @ (${o.css.left}, ${o.css.top}), pencere ${o.pencere.w}x${o.pencere.h}`);

  bildir(o.fontVar, 'font: PixelifySans yuklendi (CSP font-src acik)');
  bildir(o.durum === 'acik', `balon durumu "acik" (gelen: ${o.durum})`);

  // 1) kanvas native cozunurlukte
  bildir(o.kanvas.w === o.kutu.genislik && o.kanvas.h === o.kutu.yukseklik,
    `kanvas native cozunurlukte: ${o.kanvas.w}x${o.kanvas.h} == olculen kutu `
    + `${o.kutu.genislik}x${o.kutu.yukseklik}`);

  // 2) CSS boyutu karakterin olcegiyle ayni
  const bekW = o.kutu.genislik * o.scale;
  const bekH = o.kutu.yukseklik * o.scale;
  bildir(Math.abs(o.css.w - bekW) < 0.01 && Math.abs(o.css.h - bekH) < 0.01,
    `balon karakterle ayni olcekte: CSS ${o.css.w}x${o.css.h} == native x ${o.scale} `
    + `(${bekW}x${bekH})`);

  // 3) fiziksel piksel izgarasi
  const tam = (v) => Math.abs(v - Math.round(v)) < 1e-6;
  for (const [ad, deger] of [
    ['sol kenar', o.css.left * o.dpr],
    ['ust kenar', o.css.top * o.dpr],
    ['genislik', o.css.w * o.dpr],
    ['yukseklik', o.css.h * o.dpr]
  ]) {
    bildir(tam(deger), `izgara: balon ${ad.padEnd(9)} = ${deger} fiziksel px `
      + `${tam(deger) ? '(tam sayi)' : '(TAM SAYI DEGIL -> yeniden orneklenir)'}`);
  }

  // 4) pencere icinde mi
  bildir(o.css.top >= 0, `balon pencerenin ustunden tasmiyor (top=${o.css.top})`);
  bildir(o.css.left >= 0 && o.css.left + o.css.w <= o.pencere.w + 0.01,
    `balon pencerenin yanlarindan tasmiyor `
    + `(${o.css.left} .. ${(o.css.left + o.css.w).toFixed(1)} / ${o.pencere.w})`);
  bildir(o.css.top + o.css.h <= o.petCss.top + o.petCss.h,
    'balon karakterin ustunde kaliyor');

  // 5) esikleme: ara alfa kalmamali
  bildir(o.alfa.ara === 0,
    `esikleme: ara alfa piksel sayisi ${o.alfa.ara} (0 olmali; `
    + `opak ${o.alfa.tam}, seffaf ${o.alfa.bos})`);
  bildir(o.alfa.tam > 0, `balon gercekten cizilmis (opak piksel ${o.alfa.tam})`);

  // Gorsel kayit
  const cek = async (ad) => {
    try {
      const img = await win.capturePage();
      const cikti = path.join(app.getPath('temp'), `pet-balon${ad}.png`);
      fs.writeFileSync(cikti, img.toPNG());
      console.log(`SELFTEST gorsel: ${cikti}`);
    } catch (e) {
      console.log(`SELFTEST      ekran goruntusu alinamadi: ${e.message}`);
    }
  };
  await cek('');

  // Olcek turu: balonun en kirilgan yani burasi. Kullanici sag tik menusunden
  // kesirli olcek secebiliyor (dpr 2'de 0.5 / 1.5 / 2.5) ve balon o zaman da
  // fiziksel piksele oturmali — oturmazsa cerceve ve metin yeniden orneklenir.
  for (const s of [0.5, 1.5, 3]) {
    const r = await win.webContents.executeJavaScript(`(async () => {
      const p = window.__pet;
      p.wantedScale = ${s};
      await p.applyDisplayScale();
      p.bubble.show(p.lines[0], 4000, 1);
      for (let i = 0; i < 8; i++) p.bubble.update(50);
      p.bubble.ciz();
      const b = document.getElementById('bubble');
      const r = b.getBoundingClientRect();
      return { scale: p.scale, dpr: devicePixelRatio,
               left: r.left, top: r.top, w: r.width, h: r.height,
               pencereW: innerWidth, pencereH: innerHeight };
    })()`);
    await new Promise((x) => setTimeout(x, 250));

    const hepsiTam = [r.left, r.top, r.w, r.h].every((v) => tam(v * r.dpr));
    bildir(hepsiTam, `olcek ${String(s).padEnd(3)}-> uygulanan ${r.scale}: balon `
      + `${r.w}x${r.h} @ (${r.left}, ${r.top}) = fiziksel `
      + `${[r.left, r.top, r.w, r.h].map((v) => v * r.dpr).join('/')} `
      + `${hepsiTam ? '(hepsi tam sayi)' : '(TAM SAYI DEGIL)'}`);
    bildir(r.top >= 0 && r.left >= 0 && r.left + r.w <= r.pencereW + 0.01,
      `olcek ${String(s).padEnd(3)}-> balon pencere icinde `
      + `(${r.left} .. ${(r.left + r.w).toFixed(1)} / ${r.pencereW}, top ${r.top})`);
    await cek(`-${String(s).replace('.', '_')}x`);
  }

  console.log(`SELFTEST ${hata === 0 ? 'HEPSI GECTI' : hata + ' BASARISIZ'}`);
  app.exit(hata === 0 ? 0 : 1);
}

module.exports = calistir;
