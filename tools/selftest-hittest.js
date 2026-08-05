/**
 * Tıklama geçirgenliğinin regresyon testi.
 *
 *   npm run check:hittest
 *
 * Neden ayrı bir test: pencerenin %90'dan fazlası şeffaf ve bu alan eskiden
 * altındaki uygulamalara giden tıklamaları yutuyordu. Çözüm, imleci alfa
 * hit-test'ten geçirip pencereyi yalnızca karakterin üstündeyken tıklanabilir
 * yapmak. Bu zinciri (koordinat dönüşümü + IPC) gözle doğrulamak zor, çünkü
 * hata "tıklama arkaya geçmiyor" gibi sessiz bir davranış olarak çıkıyor.
 *
 * Test, gerçek fareyi kullanmak yerine sendInputEvent ile renderer'a sentetik
 * mousemove enjekte ediyor ve ana sürecin hangi duruma geçtiğini okuyor.
 * Böylece kullanıcı etkileşimi olmadan çalışıyor.
 *
 * NOT: sendInputEvent olayı doğrudan renderer'a verdiği için bu test
 * `setIgnoreMouseEvents(..., { forward: true })` bayrağının işletim sistemi
 * tarafını KAPSAMAZ; yalnızca hit-test matematiğini ve IPC bağlantısını
 * doğrular.
 */

const PROBLAR = [
  // [ad, x oranı/ofset türü, y, beklenen]
  { ad: 'govde (opak)', x: (w) => Math.round(w / 2), y: (_w, h) => h - 44, bekle: true },
  { ad: 'balon seridi', x: (w) => Math.round(w / 2), y: () => 20, bekle: false },
  { ad: 'sol ust kose', x: () => 5, y: () => 5, bekle: false },
  { ad: 'sag alt kose', x: (w) => w - 5, y: (_w, h) => h - 5, bekle: false },
  { ad: 'kanvas ici, govdenin solu', x: (w) => Math.round(w / 2) - 38, y: (_w, h) => h - 44, bekle: false }
];

/**
 * @param {import('electron').BrowserWindow} win
 * @param {() => boolean} okuDurum ana süreçteki güncel interactive durumu
 * @param {import('electron').App} app
 */
async function calistir(win, okuDurum, app) {
  // Karakterin yüklenip pencerenin yeniden ölçülmesini bekle
  await new Promise((r) => setTimeout(r, 2000));

  const [w, h] = win.getSize();
  console.log(`SELFTEST pencere ${w}x${h}`);

  let hata = 0;

  // Kanvas fiziksel piksel ızgarasına oturmalı. Oturmazsa ölçek "güvenli" olsa
  // bile tarayıcı görüntüyü yeniden örnekler ve pixel art bulanıklaşır — gözle
  // fark etmesi zor, sessizce bozulan cinsten bir hata.
  const l = await win.webContents.executeJavaScript(`(() => {
    const c = document.getElementById('pet');
    const r = c.getBoundingClientRect();
    return { dpr: devicePixelRatio, left: r.left, top: r.top, w: r.width, h: r.height };
  })()`);

  const tam = (v) => Math.abs(v - Math.round(v)) < 1e-6;
  for (const [ad, deger] of [
    ['sol kenar', l.left * l.dpr],
    ['ust kenar', l.top * l.dpr],
    ['genislik', l.w * l.dpr],
    ['yukseklik', l.h * l.dpr]
  ]) {
    const ok = tam(deger);
    if (!ok) hata++;
    console.log(`SELFTEST ${ok ? 'OK  ' : 'HATA'} izgara: kanvas ${ad.padEnd(17)} `
      + `= ${deger} fiziksel px ${ok ? '(tam sayi)' : '(TAM SAYI DEGIL -> yeniden orneklenir)'}`);
  }
  console.log(`SELFTEST      dpr=${l.dpr}, kanvas ${l.w}x${l.h} CSS px @ sol ${l.left}`);

  for (const p of PROBLAR) {
    const x = p.x(w, h);
    const y = p.y(w, h);
    win.webContents.sendInputEvent({ type: 'mouseMove', x, y });
    await new Promise((r) => setTimeout(r, 200));

    const durum = okuDurum();
    const ok = durum === p.bekle;
    if (!ok) hata++;
    console.log(`SELFTEST ${ok ? 'OK  ' : 'HATA'} ${p.ad.padEnd(26)} (${x},${y}) `
      + `-> interactive=${durum} (beklenen ${p.bekle})`);
  }

  console.log(`SELFTEST ${hata === 0 ? 'HEPSI GECTI' : hata + ' BASARISIZ'}`);
  app.exit(hata === 0 ? 0 : 1);
}

module.exports = calistir;
