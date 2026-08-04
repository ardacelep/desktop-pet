const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('petAPI', {
  /** Aktif karakter, pencere konumu, çalışma alanı ve platform bilgisi. */
  getConfig: () => ipcRenderer.invoke('pet:get-config'),

  /** Verilen ekran noktasını içeren monitörün çalışma alanı. */
  getWorkArea: (point) => ipcRenderer.invoke('pet:get-work-area', point),

  /** Pencereyi mutlak ekran koordinatına taşı. */
  move: (x, y) => ipcRenderer.send('pet:move', { x, y }),

  /** Son konumu diske yaz (sürükleme bitince / yürüyüş durunca). */
  persistPosition: () => ipcRenderer.send('pet:persist-position'),

  /** Sağ tık menüsünü aç. */
  openContextMenu: () => ipcRenderer.send('pet:context-menu'),

  onCharacterChanged: (cb) => ipcRenderer.on('pet:character-changed', (_e, c) => cb(c)),
  onPositionReset: (cb) => ipcRenderer.on('pet:position-reset', (_e, p) => cb(p))
});
