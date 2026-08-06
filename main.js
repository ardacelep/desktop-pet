const { app, BrowserWindow, ipcMain, screen, Menu, Tray, nativeImage } = require('electron');
const path = require('path');
const fs = require('fs');
const Store = require('electron-store');

const CHARACTERS_DIR = path.join(__dirname, 'characters');

// Yalnızca ilk kare için başlangıç değeri: renderer karakteri ve balonu
// yükleyince pencereyi gerçek ölçülere göre yeniden boyutlandırıyor
// (pet:resize). Balon payı artık burada sabit değil — repliklerin native
// kutusundan ölçülüp karakterle aynı katsayıyla büyütülüyor.
const WINDOW_WIDTH = 200;
const WINDOW_HEIGHT = 180;

const store = new Store({
  defaults: {
    activeCharacterId: null,
    position: null,
    // Kullanıcının sağ tık menüsünden seçtiği boyut, karakter başına.
    // meta.json'daki displayScale'i ezer.
    scaleOverrides: {}
  }
});

/** @type {BrowserWindow | null} */
let petWindow = null;
/** @type {Tray | null} */
let tray = null;

/**
 * Karakterleri klasörden keşfeder: meta.json içeren her alt klasör bir karakterdir.
 * Merkezi bir kayıt defteri tutmuyoruz — böylece yeni karakter eklemek ortak bir
 * dosyaya dokunmayı gerektirmiyor ve paralel katkılarda merge conflict çıkmıyor.
 */
function discoverCharacters() {
  const dirs = fs
    .readdirSync(CHARACTERS_DIR, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .filter((d) => fs.existsSync(path.join(CHARACTERS_DIR, d.name, 'meta.json')));

  const list = [];
  for (const dir of dirs) {
    try {
      const meta = JSON.parse(
        fs.readFileSync(path.join(CHARACTERS_DIR, dir.name, 'meta.json'), 'utf8')
      );
      const nativeFrameSize = meta.nativeFrameSize ?? meta.idle?.frameSize ?? 88;
      list.push({
        id: dir.name,
        folder: dir.name,
        displayName: meta.displayName || dir.name,
        nativeFrameSize,
        meta
      });
    } catch (err) {
      // Bozuk bir meta.json tüm uygulamayı düşürmesin, sadece o karakter atlansın
      console.error(`[pet] "${dir.name}" karakteri atlandı: ${err.message}`);
    }
  }

  // Menü sırası her makinede aynı olsun diye deterministik sıralama
  list.sort((a, b) => a.displayName.localeCompare(b.displayName, 'tr'));
  return list;
}

/** Yeni kurulumda hangi karakterle başlanacağı. Nadiren değişir. */
function readDefaultCharacterId() {
  try {
    const raw = fs.readFileSync(path.join(CHARACTERS_DIR, 'characters.json'), 'utf8');
    return JSON.parse(raw).default ?? null;
  } catch {
    return null;
  }
}

function resolveActiveCharacter() {
  const list = discoverCharacters();
  if (list.length === 0) {
    throw new Error('characters/ altında meta.json içeren hiçbir karakter klasörü bulunamadı.');
  }

  const wantedId = store.get('activeCharacterId') || readDefaultCharacterId();
  const entry = list.find((c) => c.id === wantedId) || list[0];
  const overrides = store.get('scaleOverrides') || {};

  return {
    ...entry,
    // Kullanıcı menüden boyut seçtiyse meta.json'daki değer yerine o geçerli
    userScale: Number.isFinite(overrides[entry.id]) ? overrides[entry.id] : null,
    // renderer/index.html'e göreli — file:// ve asar içinde de çalışır
    baseUrl: `../characters/${entry.folder}/`
  };
}

/** Pet'in şu an bulunduğu ekranın piksel oranı. */
function currentScaleFactor() {
  if (!petWindow || petWindow.isDestroyed()) return 1;
  const [x, y] = petWindow.getPosition();
  const [w, h] = petWindow.getSize();
  const display = screen.getDisplayNearestPoint({
    x: Math.round(x + w / 2),
    y: Math.round(y + h / 2)
  });
  return display.scaleFactor || 1;
}

/**
 * Bu ekranda bozulma üretmeyen boyut adımları.
 *
 * Bir kaynak piksel tam sayıda fiziksel piksel kaplamalı, yani ölçek `k / dpr`
 * olmalı. Merdiven ekrana göre değişiyor: Retina'da (dpr 2) yarım adımlar
 * mümkün, düz bir 1x monitörde yalnızca tam sayılar. Bu yüzden menü sabit
 * değil, açıldığı anda bulunulan ekrandan hesaplanıyor.
 */
function scaleSteps(dpr, max = 3) {
  const adimlar = [];
  for (let k = 1; k <= Math.round(max * dpr); k++) adimlar.push(k / dpr);
  return adimlar;
}

/** Verilen noktayı içeren ekranın çalışma alanı (dock/taskbar hariç). */
function workAreaAt(x, y) {
  const display = screen.getDisplayNearestPoint({ x: Math.round(x), y: Math.round(y) });
  return display.workArea;
}

function defaultPosition() {
  const { x, y, width, height } = screen.getPrimaryDisplay().workArea;
  return {
    x: Math.round(x + width / 2 - WINDOW_WIDTH / 2),
    y: Math.round(y + height - WINDOW_HEIGHT)
  };
}

function createPetWindow(characterId) {
  if (characterId) store.set('activeCharacterId', characterId);

  const saved = store.get('position');
  const pos = saved || defaultPosition();

  const win = new BrowserWindow({
    x: pos.x,
    y: pos.y,
    width: WINDOW_WIDTH,
    height: WINDOW_HEIGHT,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    hasShadow: false,
    resizable: false,
    movable: true,
    fullscreenable: false,
    focusable: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  // macOS'ta düz alwaysOnTop bazen Dock/menu bar altında kalıyor; 'floating' daha güvenilir.
  win.setAlwaysOnTop(true, 'floating');
  if (process.platform === 'darwin') {
    // Tam ekran uygulamalar dahil her Space'te görünsün.
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  }

  // Pencere tıklama geçirgen BAŞLAR. Pencerenin ~%94'ü şeffaf (balon için ayrılan
  // üst şerit, kenar payları, kare kutunun kendi boşluğu) ve bu alan altındaki
  // uygulamalara giden tıklamaları yutuyordu. `forward: true` sayesinde geçirgen
  // haldeyken bile mousemove renderer'a ulaşıyor; renderer imleç gerçekten opak bir
  // pikselin üstüne geldiğinde pet:set-interactive ile pencereyi kısa süreliğine
  // tıklanabilir yapıyor.
  win.setIgnoreMouseEvents(true, { forward: true });

  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  win.on('closed', () => {
    petWindow = null;
  });

  return win;
}

let currentInteractive = false;

// Renderer'ın gerçekte uyguladığı ölçek. Menüdeki işareti buna göre koyuyoruz;
// yuvarlama kuralını burada ikinci kez yazmamak için renderer bildiriyor.
let currentScale = 1;

/** Renderer'ın alfa hit-test sonucuna göre pencereyi tıklanabilir/geçirgen yapar. */
function setInteractive(interactive) {
  if (!petWindow || petWindow.isDestroyed()) return;
  currentInteractive = interactive;
  if (interactive) petWindow.setIgnoreMouseEvents(false);
  else petWindow.setIgnoreMouseEvents(true, { forward: true });
}


function persistPosition() {
  if (!petWindow || petWindow.isDestroyed()) return;
  const [x, y] = petWindow.getPosition();
  store.set('position', { x, y });
}

function buildMenuTemplate() {
  const list = discoverCharacters();
  const activeId = store.get('activeCharacterId') || readDefaultCharacterId() || list[0]?.id;

  return [
    {
      label: 'Karakter Değiştir',
      submenu: list.map((c) => ({
        label: c.displayName,
        type: 'radio',
        checked: c.id === activeId,
        click: () => switchCharacter(c.id)
      }))
    },
    {
      label: 'Boyut',
      submenu: [
        ...scaleSteps(currentScaleFactor()).map((s) => ({
          label: `${s}×`,
          type: 'radio',
          checked: Math.abs(s - currentScale) < 1e-6,
          click: () => setUserScale(s)
        })),
        { type: 'separator' },
        {
          label: 'Varsayılana dön',
          click: () => setUserScale(null)
        }
      ]
    },
    { type: 'separator' },
    {
      label: 'Ortaya Getir',
      click: () => {
        const pos = defaultPosition();
        petWindow?.setPosition(pos.x, pos.y);
        persistPosition();
        petWindow?.webContents.send('pet:position-reset', pos);
      }
    },
    { type: 'separator' },
    {
      label: 'Çıkış',
      click: () => {
        persistPosition();
        app.quit();
      }
    }
  ];
}

function switchCharacter(id) {
  store.set('activeCharacterId', id);
  petWindow?.webContents.send('pet:character-changed', resolveActiveCharacter());
}

/**
 * Kullanıcının seçtiği boyutu kaydeder. `null` verilirse meta.json'daki
 * displayScale'e geri dönülür. Renderer değeri yine kendi ekranına göre
 * yuvarlıyor — menü zaten güvenli adımlar sunduğu için normalde değişmiyor,
 * ama pet başka bir monitöre taşınırsa orada geçerli olana oturuyor.
 */
function setUserScale(scale) {
  const id = resolveActiveCharacter().id;
  const olcekler = { ...(store.get('scaleOverrides') || {}) };
  if (scale === null) delete olcekler[id];
  else olcekler[id] = scale;
  store.set('scaleOverrides', olcekler);
  petWindow?.webContents.send('pet:scale-changed', scale);
}

function createTray() {
  // Boş/şeffaf bir ikon: build/tray.png yoksa çökmesin diye tolere ediyoruz.
  const iconPath = path.join(__dirname, 'build', 'tray.png');
  const image = fs.existsSync(iconPath)
    ? nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 })
    : nativeImage.createEmpty();

  tray = new Tray(image);
  tray.setTitle('🐾'); // macOS menü çubuğunda ikon yoksa en azından bir işaret
  tray.setToolTip('Desktop Pet');
  tray.setContextMenu(Menu.buildFromTemplate(buildMenuTemplate()));
}

app.whenReady().then(() => {
  if (process.platform === 'darwin') app.dock?.hide();

  petWindow = createPetWindow();
  createTray();

  // Regresyon testleri — npm run check:hittest / npm run check:bubble
  if (process.env.PET_SELFTEST) {
    const test = process.env.PET_SELFTEST === 'bubble' ? 'selftest-bubble' : 'selftest-hittest';
    petWindow.webContents.once('did-finish-load', () =>
      require(`./tools/${test}`)(petWindow, () => currentInteractive, app));
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) petWindow = createPetWindow();
  });
});

app.on('window-all-closed', () => {
  app.quit();
});

app.on('before-quit', persistPosition);

/* ---------------------------------- IPC ---------------------------------- */

ipcMain.handle('pet:get-config', () => {
  const [x, y] = petWindow.getPosition();
  const [width, height] = petWindow.getSize();
  return {
    character: resolveActiveCharacter(),
    window: { x, y, width, height },
    workArea: workAreaAt(x + width / 2, y + height / 2),
    platform: process.platform
  };
});

/**
 * Pencereyi karakterin gerçek boyutuna göre yeniden ölçer. Karakterler farklı
 * native çözünürlükte (ve displayScale ile farklı çarpanda) olabildiği için sabit
 * bir pencere boyutu ya sprite'ı kırpardı ya da gereksiz boşluk bırakırdı.
 * Alt kenarı sabit tutuyoruz: pet yere basıyor, yukarı doğru büyümeli.
 */
ipcMain.handle('pet:resize', (_e, { width, height }) => {
  if (!petWindow || petWindow.isDestroyed()) return null;
  const [x, y] = petWindow.getPosition();
  const [, oldHeight] = petWindow.getSize();
  if (!Number.isFinite(width) || !Number.isFinite(height)) {
    console.error(`[pet] geçersiz pencere ölçüsü yok sayıldı: ${width}x${height}`);
    return null;
  }
  const w = Math.max(1, Math.round(width));
  const h = Math.max(1, Math.round(height));

  // y burada da ekranKoordinati'ndan geçiyor: pencere ekranın üst kenarına
  // yakınken y + (oldHeight - h) negatif sıfıra düşebilir.
  const ny0 = ekranKoordinati(y + (oldHeight - h));
  if (ny0 === null) return null;
  petWindow.setBounds({ x, y: ny0, width: w, height: h });
  const [nx, ny] = petWindow.getPosition();
  return { x: nx, y: ny, width: w, height: h };
});

ipcMain.on('pet:set-interactive', (_e, interactive) => setInteractive(Boolean(interactive)));

ipcMain.on('pet:scale-applied', (_e, scale) => {
  if (Number.isFinite(scale) && scale > 0) currentScale = scale;
});

ipcMain.handle('pet:get-work-area', (_e, point) => workAreaAt(point.x, point.y));

/**
 * Ekran koordinatını Electron'un kabul edeceği tam sayıya çevirir; çeviremezse
 * null döner.
 *
 * NEGATİF SIFIR TUZAĞI: `Math.round(-0.3)` JavaScript'te `-0` veriyor ve
 * Electron'un native int dönüşümü `-0` için "Error processing argument at
 * index 0, conversion failure" fırlatıyor (ölçüldü — `-0`, NaN, Infinity ve
 * int32 dışı değerler aynı hatayı veriyor). Pet ekranın soluna yürürken x,
 * [-0.5, 0) aralığından geçmek zorunda (sol sınır negatif, çünkü pencere
 * sprite'tan geniş) ve tam o karede ana süreç çöküyordu.
 *
 * `Number.isFinite(-0)` true olduğu için sıradan bir "geçerli sayı mı"
 * kontrolü bunu YAKALAMIYOR; sıfırı ayrıca normalleştirmek gerekiyor.
 */
function ekranKoordinati(deger) {
  if (!Number.isFinite(deger)) return null;
  const n = Math.round(deger);
  if (Math.abs(n) > 2147483647) return null; // int32 dışı da aynı hatayı veriyor
  return n === 0 ? 0 : n; // -0 -> +0
}

ipcMain.on('pet:move', (_e, { x, y }) => {
  if (!petWindow || petWindow.isDestroyed()) return;
  const ix = ekranKoordinati(x);
  const iy = ekranKoordinati(y);
  if (ix === null || iy === null) {
    console.error(`[pet] geçersiz konum yok sayıldı: x=${x} y=${y}`);
    return;
  }
  petWindow.setPosition(ix, iy);
});

ipcMain.on('pet:persist-position', persistPosition);

ipcMain.on('pet:context-menu', () => {
  Menu.buildFromTemplate(buildMenuTemplate()).popup({ window: petWindow });
});

// Regresyon testi (tools/selftest-hittest.js) icin
module.exports = { ekranKoordinati, buildMenuTemplate, scaleSteps };
