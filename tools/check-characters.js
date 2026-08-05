#!/usr/bin/env node
/**
 * characters/ altındaki tüm karakterleri doğrular.
 *
 *   npm run check
 *
 * Yeni karakter ekleyenler için hızlı geri bildirim: eksik dosya, bozuk JSON ya da
 * meta.json'daki kare sayısıyla uyuşmayan sprite sheet ölçüsü uygulamada sessizce
 * yanlış çizime yol açıyor — burada erken yakalıyoruz.
 */
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const CHARACTERS_DIR = path.join(__dirname, '..', 'characters');
const REQUIRED_CLIPS = ['idle', 'walk_right'];
const OPTIONAL_CLIPS = ['walk_left'];

/** PNG başlığındaki IHDR bloğundan genişlik/yükseklik okur (bağımlılık gerekmesin diye). */
function pngSize(file) {
  const buf = Buffer.alloc(24);
  const fd = fs.openSync(file, 'r');
  try {
    const read = fs.readSync(fd, buf, 0, 24, 0);
    if (read < 24 || buf.toString('ascii', 1, 4) !== 'PNG') {
      throw new Error('geçerli bir PNG değil');
    }
  } finally {
    fs.closeSync(fd);
  }
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}

/**
 * PNG'nin alfa kanalını çözer. Elle yazıldı çünkü projenin Node tarafında hiç
 * bağımlılık yok ve bunun için bir görüntü kütüphanesi eklemek istemedik
 * (Python araçları da aynı sebeple scipy'siz).
 *
 * Yalnızca 8 bit RGBA, interlace'siz PNG destekleniyor — pixelart_extract.py ve
 * pack_sheet.py tam olarak bunu üretiyor. Başka bir biçim gelirse null döner ve
 * çağıran taraf içerik analizini atlar.
 */
function pngAlpha(file) {
  const buf = fs.readFileSync(file);
  if (buf.toString('ascii', 1, 4) !== 'PNG') return null;

  const width = buf.readUInt32BE(16);
  const height = buf.readUInt32BE(20);
  const bitDepth = buf[24];
  const colorType = buf[25];
  const interlace = buf[28];
  if (bitDepth !== 8 || colorType !== 6 || interlace !== 0) return null;

  // IDAT parçalarını birleştir
  const parts = [];
  let off = 8;
  while (off + 8 <= buf.length) {
    const len = buf.readUInt32BE(off);
    const type = buf.toString('ascii', off + 4, off + 8);
    if (type === 'IDAT') parts.push(buf.subarray(off + 8, off + 8 + len));
    if (type === 'IEND') break;
    off += 12 + len;
  }
  if (parts.length === 0) return null;

  const raw = zlib.inflateSync(Buffer.concat(parts));
  const bpp = 4;
  const stride = width * bpp;
  const alpha = new Uint8Array(width * height);
  const prev = Buffer.alloc(stride);
  const cur = Buffer.alloc(stride);

  let p = 0;
  for (let y = 0; y < height; y++) {
    const filter = raw[p++];
    raw.copy(cur, 0, p, p + stride);
    p += stride;

    // PNG satır filtrelerini geri al (spec: 0 None, 1 Sub, 2 Up, 3 Average, 4 Paeth)
    for (let i = 0; i < stride; i++) {
      const a = i >= bpp ? cur[i - bpp] : 0;
      const b = prev[i];
      const c = i >= bpp ? prev[i - bpp] : 0;
      let v = cur[i];
      if (filter === 1) v += a;
      else if (filter === 2) v += b;
      else if (filter === 3) v += (a + b) >> 1;
      else if (filter === 4) {
        const q = a + b - c;
        const pa = Math.abs(q - a);
        const pb = Math.abs(q - b);
        const pc = Math.abs(q - c);
        v += pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
      }
      cur[i] = v & 255;
    }
    for (let x = 0; x < width; x++) alpha[y * width + x] = cur[x * bpp + 3];
    cur.copy(prev);
  }
  return { width, height, alpha };
}

/**
 * Karelerin içerik ölçüleri: karakterin gerçek boyu, ayak çizgisinin kareden
 * kareye oynaması ve kutu içindeki yatay pay.
 *
 * Boy, farklı native çözünürlükteki karakterleri karşılaştırmanın DOĞRU ölçütü —
 * `frameSize` değil. pack_sheet kutuyu çapanın etrafına kare olarak kuruyor, yani
 * kolunu yana açan bir karakterde kutu boydan büyük çıkıyor; iki karakteri kutu
 * boyuna göre kıyaslamak yanıltır.
 */
function contentStats(file, frameSize, frameCount) {
  const png = pngAlpha(file);
  if (!png) return null;

  const boylar = [];
  const ayaklar = [];
  let payMin = frameSize;

  for (let i = 0; i < frameCount; i++) {
    let top = -1, bottom = -1, left = frameSize, right = 0;
    for (let y = 0; y < frameSize; y++) {
      for (let x = 0; x < frameSize; x++) {
        const gx = i * frameSize + x;
        if (gx >= png.width || png.alpha[y * png.width + gx] === 0) continue;
        if (top < 0) top = y;
        bottom = y + 1;
        if (x < left) left = x;
        if (x + 1 > right) right = x + 1;
      }
    }
    if (top < 0) continue;
    boylar.push(bottom - top);
    ayaklar.push(bottom);
    payMin = Math.min(payMin, left, frameSize - right);
  }
  if (boylar.length === 0) return null;

  return {
    boyMin: Math.min(...boylar),
    boyMax: Math.max(...boylar),
    ayakOynama: Math.max(...ayaklar) - Math.min(...ayaklar),
    yatayPay: payMin
  };
}

function checkClip(folder, name, def, errors, warnings) {
  const where = `${folder}/meta.json → ${name}`;

  if (!def.file) return errors.push(`${where}: "file" alanı eksik`);
  if (!Number.isInteger(def.frameSize) || def.frameSize <= 0) {
    return errors.push(`${where}: "frameSize" pozitif tam sayı olmalı`);
  }
  if (!Number.isInteger(def.frameCount) || def.frameCount <= 0) {
    return errors.push(`${where}: "frameCount" pozitif tam sayı olmalı`);
  }
  if (!Number.isFinite(def.frameDuration) || def.frameDuration <= 0) {
    warnings.push(`${where}: "frameDuration" eksik/geçersiz`);
  }

  const file = path.join(CHARACTERS_DIR, folder, def.file);
  if (!fs.existsSync(file)) return errors.push(`${where}: dosya bulunamadı → ${def.file}`);

  let size;
  try {
    size = pngSize(file);
  } catch (err) {
    return errors.push(`${where}: ${def.file} okunamadı — ${err.message}`);
  }

  const expectedWidth = def.frameSize * def.frameCount;
  if (size.height !== def.frameSize) {
    errors.push(
      `${where}: sheet yüksekliği ${size.height}px, frameSize ${def.frameSize}px olmalıydı`
    );
  }
  if (size.width !== expectedWidth) {
    const fits = size.width / def.frameSize;
    const hint = Number.isInteger(fits) ? ` (bu sheet'te ${fits} kare var gibi görünüyor)` : '';
    errors.push(
      `${where}: sheet genişliği ${size.width}px, ${def.frameSize}×${def.frameCount} = ` +
        `${expectedWidth}px olmalıydı${hint}`
    );
    return null;
  }

  const stats = contentStats(file, def.frameSize, def.frameCount);
  if (stats && stats.ayakOynama > 1) {
    warnings.push(
      `${where}: ayak çizgisi kareden kareye ${stats.ayakOynama}px oynuyor — animasyon ` +
        `titrer. pack_sheet.py --align-y bottom ile yeniden paketleyin.`
    );
  }
  return stats;
}

function checkCharacter(folder, errors, warnings) {
  const metaPath = path.join(CHARACTERS_DIR, folder, 'meta.json');

  let meta;
  try {
    meta = JSON.parse(fs.readFileSync(metaPath, 'utf8'));
  } catch (err) {
    errors.push(`${folder}/meta.json okunamadı: ${err.message}`);
    return null;
  }

  if (!meta.displayName) {
    warnings.push(`${folder}: "displayName" yok, menüde klasör adı görünecek`);
  }
  if (!Array.isArray(meta.lines) || meta.lines.length === 0) {
    warnings.push(`${folder}: "lines" boş, tıklayınca konuşacak bir şeyi yok`);
  }
  if (meta.displayScale != null
      && (!Number.isInteger(meta.displayScale) || meta.displayScale < 1)) {
    errors.push(
      `${folder}/meta.json: "displayScale" 1 veya daha büyük TAM SAYI olmalı ` +
        `(verilen: ${meta.displayScale}). Kesirli ölçek pixel art'ı bulanıklaştırır.`
    );
  }
  if (meta.displayHeight != null) {
    warnings.push(
      `${folder}: "displayHeight" artık kullanılmıyor, yerine "displayScale" ` +
        `(tam sayı çarpan) yazın. Şimdilik okunuyor ama en yakın tam sayıya yuvarlanıyor.`
    );
  }

  const istatistikler = {};
  for (const name of REQUIRED_CLIPS) {
    if (!meta[name]) errors.push(`${folder}/meta.json: zorunlu "${name}" tanımı eksik`);
    else istatistikler[name] = checkClip(folder, name, meta[name], errors, warnings);
  }
  for (const name of OPTIONAL_CLIPS) {
    if (meta[name]) istatistikler[name] = checkClip(folder, name, meta[name], errors, warnings);
  }

  // Klip kutuları farklıysa uygulama her klibi kendi ölçeğinde çizerek doğru
  // sonucu veriyor, ama bu genelde kareleri ayrı ayrı paketlemekten geliyor;
  // katkı verenin haberi olsun.
  const kutular = [...new Set(
    [...REQUIRED_CLIPS, ...OPTIONAL_CLIPS].filter((n) => meta[n]).map((n) => meta[n].frameSize)
  )];
  if (kutular.length > 1) {
    warnings.push(
      `${folder}: klipler farklı kutu boyutunda (${kutular.join(', ')}). Çalışır, ama ` +
        `hepsini aynı --box değeriyle paketlemek daha temiz.`
    );
  }

  return { meta, istatistikler };
}

function main() {
  const folders = fs
    .readdirSync(CHARACTERS_DIR, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name)
    .sort();

  if (folders.length === 0) {
    console.error('✗ characters/ altında hiç karakter klasörü yok.');
    process.exit(1);
  }

  const errors = [];
  const warnings = [];
  const boylar = [];
  let ok = 0;

  for (const folder of folders) {
    if (!fs.existsSync(path.join(CHARACTERS_DIR, folder, 'meta.json'))) {
      warnings.push(`${folder}: meta.json yok — uygulama bu klasörü görmezden gelecek`);
      continue;
    }
    const before = errors.length;
    const sonuc = checkCharacter(folder, errors, warnings);
    if (!sonuc) {
      console.log(`✗ ${folder}`);
      continue;
    }

    const { meta, istatistikler } = sonuc;
    const olcek = Number.isInteger(meta.displayScale) && meta.displayScale >= 1
      ? meta.displayScale
      : 1;
    const idle = istatistikler.idle;

    if (errors.length === before) {
      ok++;
      const ekranBoyu = idle ? idle.boyMax * olcek : null;
      const boyBilgi = idle
        ? `boy ${idle.boyMax}px × ${olcek} = ekranda ${ekranBoyu}px`
        : 'boy ölçülemedi';
      console.log(`✓ ${folder} — ${meta.displayName || folder}  (kutu ${meta.nativeFrameSize}, ${boyBilgi})`);
      if (ekranBoyu) boylar.push({ folder, ekranBoyu });
    } else {
      console.log(`✗ ${folder}`);
    }
  }

  // Karakterler birbirine göre çok farklı boyda mı? Karşılaştırma ölçütü kare
  // kutusu değil karakterin GERÇEK boyu — kutu, kolunu açan karakterde şişiyor.
  if (boylar.length > 1) {
    const enKucuk = boylar.reduce((a, b) => (a.ekranBoyu <= b.ekranBoyu ? a : b));
    const enBuyuk = boylar.reduce((a, b) => (a.ekranBoyu >= b.ekranBoyu ? a : b));
    if (enBuyuk.ekranBoyu > 1.25 * enKucuk.ekranBoyu) {
      warnings.push(
        `karakterler ekranda çok farklı boyda: ${enKucuk.folder} ${enKucuk.ekranBoyu}px, ` +
          `${enBuyuk.folder} ${enBuyuk.ekranBoyu}px. Küçük olanın meta.json'ına tam sayı ` +
          `"displayScale" verin ya da sprite'ı daha yüksek ızgara yoğunluğunda yeniden üretin.`
      );
    }
  }

  for (const w of warnings) console.log(`  uyarı: ${w}`);
  for (const e of errors) console.error(`  hata:  ${e}`);

  console.log(`\n${ok}/${folders.length} karakter geçerli.`);
  process.exit(errors.length > 0 ? 1 : 0);
}

main();
