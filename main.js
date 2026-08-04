const { app, BrowserWindow, ipcMain, screen, Menu, Tray, nativeImage } = require('electron');
const path = require('path');
const fs = require('fs');
const Store = require('electron-store');

const CHARACTERS_DIR = path.join(__dirname, 'characters');

// Pencere sprite'tan biraz büyük: üstte konuşma balonu için yer kalsın.
const WINDOW_WIDTH = 200;
const WINDOW_HEIGHT = 180;

const store = new Store({
  defaults: {
    activeCharacterId: null,
    position: null
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
        displayHeight: meta.displayHeight ?? nativeFrameSize,
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

  return {
    ...entry,
    // renderer/index.html'e göreli — file:// ve asar içinde de çalışır
    baseUrl: `../characters/${entry.folder}/`
  };
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

  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  win.on('closed', () => {
    petWindow = null;
  });

  return win;
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
  return {
    character: resolveActiveCharacter(),
    window: { x, y, width: WINDOW_WIDTH, height: WINDOW_HEIGHT },
    workArea: workAreaAt(x + WINDOW_WIDTH / 2, y + WINDOW_HEIGHT / 2),
    platform: process.platform
  };
});

ipcMain.handle('pet:get-work-area', (_e, point) => workAreaAt(point.x, point.y));

ipcMain.on('pet:move', (_e, { x, y }) => {
  if (!petWindow || petWindow.isDestroyed()) return;
  petWindow.setPosition(Math.round(x), Math.round(y));
});

ipcMain.on('pet:persist-position', persistPosition);

ipcMain.on('pet:context-menu', () => {
  Menu.buildFromTemplate(buildMenuTemplate()).popup({ window: petWindow });
});
