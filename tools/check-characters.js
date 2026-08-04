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
  }
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

  for (const name of REQUIRED_CLIPS) {
    if (!meta[name]) errors.push(`${folder}/meta.json: zorunlu "${name}" tanımı eksik`);
    else checkClip(folder, name, meta[name], errors, warnings);
  }
  for (const name of OPTIONAL_CLIPS) {
    if (meta[name]) checkClip(folder, name, meta[name], errors, warnings);
  }

  return meta;
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
  let ok = 0;

  for (const folder of folders) {
    if (!fs.existsSync(path.join(CHARACTERS_DIR, folder, 'meta.json'))) {
      warnings.push(`${folder}: meta.json yok — uygulama bu klasörü görmezden gelecek`);
      continue;
    }
    const before = errors.length;
    const meta = checkCharacter(folder, errors, warnings);
    if (meta && errors.length === before) {
      ok++;
      console.log(`✓ ${folder} — ${meta.displayName || folder}`);
    } else {
      console.log(`✗ ${folder}`);
    }
  }

  for (const w of warnings) console.log(`  uyarı: ${w}`);
  for (const e of errors) console.error(`  hata:  ${e}`);

  console.log(`\n${ok}/${folders.length} karakter geçerli.`);
  process.exit(errors.length > 0 ? 1 : 0);
}

main();
