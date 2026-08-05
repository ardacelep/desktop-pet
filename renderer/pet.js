/* global SpriteAnimator, SpeechBubble, loadImage, measureContent */

const STATE = {
  IDLE: 'IDLE',
  WALKING: 'WALKING',
  DRAGGING: 'DRAGGING',
  REACTING: 'REACTING'
};

// Tıklama mı sürükleme mi ayrımı için eşikler
const CLICK_MOVE_THRESHOLD = 5; // px
const CLICK_TIME_THRESHOLD = 400; // ms

const IDLE_MIN = 3000;
const IDLE_MAX = 9000;
const REACT_DURATION = 2600;

// Konuşma balonu kendi genişliğini istiyor; pencere sprite'tan dar olamaz.
const BUBBLE_MIN_WIDTH = 200;

// Hit-test payı (CSS px). Karakter 40 piksel eninde ve kolu/bacağı birkaç piksel
// kalınlığında — tam piksel isabeti istemek pet'i yakalamayı sinir bozucu yapardı.
// Pay aynı zamanda imleç sprite'a değmeden pencereyi tıklanabilir yaptığı için
// hızlı hareket edip hemen tıklayan kullanıcıda yarış durumunu da kapatıyor.
const GRAB_TOLERANCE = 3;

class Pet {
  /**
   * @param {{ canvas: HTMLCanvasElement, bubbleEl: HTMLElement, api: typeof window.petAPI }} deps
   */
  constructor({ canvas, bubbleEl, api }) {
    this.canvas = canvas;
    this.api = api;
    this.animator = new SpriteAnimator(canvas);
    this.bubble = new SpeechBubble(bubbleEl);

    this.state = STATE.IDLE;
    this.direction = 'right';
    this.clips = {};
    this.lines = [];
    this.walkSpeed = 40;

    this.x = 0;
    this.y = 0;
    this.targetX = null;
    this.workArea = null;
    this.windowSize = { width: 200, height: 180 };
    this.bubbleHeadroom = 92;

    // Ölçek her zaman TAM SAYI. Kesirli ölçek pixel art'ı bulanıklaştırıyor;
    // pixelart_extract.py da bu yüzden native çözünürlüğü zorlamıyor ve
    // ölçeklemeyi bilerek uygulama katmanına bırakıyor.
    this.scale = 1;
    // Kare kutusunun kenarındaki boş pay (native px). Yürüme sınırları ve
    // ayak hizası bundan hesaplanıyor.
    this.contentMargin = 0;
    this.footGap = 0;

    this.stateTimer = 0;
    this.nextIdleWait = this.randomIdleWait();
    this.lastFrameTime = 0;

    this.drag = null;

    // Pencere tıklama geçirgen başlıyor (main.js). Bu bayrak main'e gereksiz IPC
    // göndermemek için son bilinen durumu tutuyor.
    this.interactive = false;
  }

  /* ------------------------------ kurulum ------------------------------ */

  async init() {
    const config = await this.api.getConfig();

    this.windowSize = { width: config.window.width, height: config.window.height };
    this.x = config.window.x;
    this.y = config.window.y;
    this.workArea = config.workArea;
    this.bubbleHeadroom = config.bubbleHeadroom ?? this.bubbleHeadroom;

    await this.applyCharacter(config.character);

    this.snapToGround();
    this.clampToWorkArea();
    this.api.move(this.x, this.y);

    this.bindEvents();
    this.setState(STATE.IDLE);

    this.lastFrameTime = performance.now();
    requestAnimationFrame((t) => this.loop(t));
  }

  /** @param {any} character klasörden keşfedilen kayıt + meta.json */
  async applyCharacter(character) {
    const { meta, baseUrl, nativeFrameSize } = character;

    const names = ['idle', 'walk_right', 'walk_left'];
    const clips = {};
    for (const name of names) {
      const def = meta[name];
      if (!def) continue;
      const frameSize = def.frameSize ?? nativeFrameSize;
      const image = await loadImage(baseUrl + def.file);
      clips[name] = {
        key: name,
        image,
        frameSize,
        frameCount: def.frameCount,
        frameDuration: def.frameDuration,
        flip: Boolean(def.flip),
        content: measureContent(image, frameSize, def.frameCount)
      };
    }

    this.clips = clips;
    this.lines = meta.lines?.length ? meta.lines : ['...'];
    this.walkSpeed = meta.walkSpeed ?? 40;
    this.scale = resolveScale(character);

    const list = Object.values(clips);

    // Yürüme sınırı ve ayak hizası için EN GENİŞ pozu esas al; yoksa kolunu
    // uzattığı karede sprite ekran kenarından taşardı.
    // Payı iki yandan simetrik ölçüyoruz: sola yürüyüş flip ile üretildiği için
    // sol/sağ payları yön değişince yer değiştiriyor, simetrik olan invaryant.
    this.contentMargin = Math.min(
      ...list.map((c) => Math.min(c.content.left, c.frameSize - c.content.right))
    );
    this.footGap = Math.min(...list.map((c) => c.frameSize - c.content.bottom));

    await this.resizeWindowForCharacter();
    this.playClip(this.state === STATE.WALKING ? this.walkClipName() : 'idle');
  }

  /**
   * Pencereyi karakterin gerçek boyutuna göre ölçer. Sabit 200x180 pencere,
   * displayScale ile büyütülmüş bir karakteri kırpardı.
   */
  async resizeWindowForCharacter() {
    const maxFrame = Math.max(...Object.values(this.clips).map((c) => c.frameSize));
    this.canvasSize = maxFrame * this.scale;

    const bounds = await this.api.resize(
      Math.max(BUBBLE_MIN_WIDTH, this.canvasSize),
      this.canvasSize + this.bubbleHeadroom
    );
    if (!bounds) return;

    this.windowSize = { width: bounds.width, height: bounds.height };
    this.x = bounds.x;
    this.y = bounds.y;
  }

  bindEvents() {
    this.canvas.addEventListener('mousedown', (e) => this.onMouseDown(e));
    window.addEventListener('mousemove', (e) => this.onMouseMove(e));
    window.addEventListener('mouseup', (e) => this.onMouseUp(e));

    // İmleç pencereden çıkınca geçirgenliğe dön. Aksi halde pet'in üstünden
    // hızlıca çıkan imleçte pencere tıklanabilir kalabiliyor.
    document.addEventListener('mouseleave', () => {
      if (!this.drag) this.setInteractive(false);
    });

    this.canvas.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      this.api.openContextMenu();
    });

    this.api.onCharacterChanged((character) => {
      this.applyCharacter(character).catch((err) => console.error(err));
    });

    this.api.onPositionReset((pos) => {
      this.x = pos.x;
      this.y = pos.y;
      this.targetX = null;
      this.setState(STATE.IDLE);
    });
  }

  /* --------------------------- durum makinesi --------------------------- */

  setState(next) {
    if (this.state === next) return;
    this.state = next;
    this.stateTimer = 0;

    if (next === STATE.IDLE) {
      this.nextIdleWait = this.randomIdleWait();
      this.targetX = null;
      this.playClip('idle');
      this.api.persistPosition();
    } else if (next === STATE.WALKING) {
      this.playClip(this.walkClipName());
    } else if (next === STATE.DRAGGING) {
      this.targetX = null;
      this.playClip('idle');
    } else if (next === STATE.REACTING) {
      this.targetX = null;
      this.playClip('idle');
    }
  }

  walkClipName() {
    return this.direction === 'left' && this.clips.walk_left ? 'walk_left' : 'walk_right';
  }

  playClip(name) {
    const clip = this.clips[name] || this.clips.idle;
    if (!clip) return;
    // walk_left ayrı dosya değilse walk_right'ı runtime'da flip ederek kullan
    const flip = name === 'walk_left' && !this.clips.walk_left ? true : clip.flip;
    this.animator.setClip({ ...clip, key: name, flip });

    // CSS boyutu karakter başına değil KLİP başına ayarlanıyor: idle ve walk
    // farklı kutu boyutunda paketlenmiş olabilir (pack_sheet kutuyu her klip için
    // ayrı hesaplıyor). Tek bir CSS boyutu kullanmak, kutusu küçük olan klibi
    // büyütüp karakteri yürümeye başlayınca boy değiştirmiş gibi gösterirdi.
    // frameSize x scale demek "1 native piksel = scale CSS piksel", yani kutu ne
    // olursa olsun karakterin ekrandaki boyu sabit kalıyor.
    const css = clip.frameSize * this.scale;
    this.canvas.style.width = `${css}px`;
    this.canvas.style.height = `${css}px`;
  }

  randomIdleWait() {
    return IDLE_MIN + Math.random() * (IDLE_MAX - IDLE_MIN);
  }

  pickNewWalkTarget() {
    const { minX, maxX } = this.walkBounds();
    const target = minX + Math.random() * (maxX - minX);

    // Çok kısa mesafeler için yürümeye değmez
    if (Math.abs(target - this.x) < 40) return false;

    this.targetX = target;
    this.direction = target > this.x ? 'right' : 'left';
    return true;
  }

  /* ------------------------------- döngü ------------------------------- */

  loop(now) {
    const dt = Math.min(now - this.lastFrameTime, 100); // sekme uykuya dalarsa sıçramasın
    this.lastFrameTime = now;

    this.update(dt);
    this.animator.update(dt);
    this.animator.draw();

    requestAnimationFrame((t) => this.loop(t));
  }

  update(dt) {
    this.stateTimer += dt;

    switch (this.state) {
      case STATE.IDLE:
        if (this.stateTimer >= this.nextIdleWait) {
          if (this.pickNewWalkTarget()) this.setState(STATE.WALKING);
          else this.stateTimer = 0;
        }
        break;

      case STATE.WALKING:
        this.updateWalk(dt);
        break;

      case STATE.REACTING:
        if (this.stateTimer >= REACT_DURATION) this.setState(STATE.IDLE);
        break;

      case STATE.DRAGGING:
      default:
        break;
    }
  }

  updateWalk(dt) {
    const step = (this.walkSpeed * dt) / 1000;
    const dir = this.direction === 'right' ? 1 : -1;
    let nextX = this.x + step * dir;

    const { minX, maxX } = this.walkBounds();

    // Ekran kenarına çarpınca dön ve yürümeye devam et
    if (nextX <= minX || nextX >= maxX) {
      nextX = Math.max(minX, Math.min(maxX, nextX));
      this.direction = this.direction === 'right' ? 'left' : 'right';
      this.targetX = this.direction === 'right' ? maxX : minX;
      this.playClip(this.walkClipName());
    }

    this.x = nextX;
    this.api.move(this.x, this.y);

    if (this.targetX !== null && Math.abs(this.x - this.targetX) <= step + 0.5) {
      this.x = this.targetX;
      this.api.move(this.x, this.y);
      this.setState(STATE.IDLE);
    }
  }

  /* ---------------------------- etkileşimler ---------------------------- */

  onMouseDown(e) {
    if (e.button !== 0) return;
    e.preventDefault();

    this.drag = {
      offsetX: e.screenX - this.x,
      offsetY: e.screenY - this.y,
      startScreenX: e.screenX,
      startScreenY: e.screenY,
      startTime: performance.now(),
      moved: false
    };
  }

  /**
   * İmleç gerçekten karakterin üstünde mi? Canvas'ın canlı piksellerini okuyor,
   * yani flip edilmiş yürüyüşte de, animasyonun o anki karesinde de doğru sonuç
   * veriyor — ayrı bir maske tutmaya gerek yok.
   */
  isOverSprite(clientX, clientY) {
    const canvas = this.canvas;
    const rect = canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;

    // CSS px -> canvas (native) px
    const sx = canvas.width / rect.width;
    const sy = canvas.height / rect.height;
    const cx = (clientX - rect.left) * sx;
    const cy = (clientY - rect.top) * sy;

    const tol = Math.max(1, Math.round(GRAB_TOLERANCE * sx));
    const x0 = Math.max(0, Math.floor(cx) - tol);
    const y0 = Math.max(0, Math.floor(cy) - tol);
    const x1 = Math.min(canvas.width, Math.floor(cx) + tol + 1);
    const y1 = Math.min(canvas.height, Math.floor(cy) + tol + 1);
    if (x1 <= x0 || y1 <= y0) return false;

    const { data } = this.animator.ctx.getImageData(x0, y0, x1 - x0, y1 - y0);
    for (let i = 3; i < data.length; i += 4) {
      if (data[i] > 0) return true;
    }
    return false;
  }

  /** Pencereyi tıklanabilir/geçirgen yapar; yalnızca durum değişince IPC gönderir. */
  setInteractive(next) {
    if (this.interactive === next) return;
    this.interactive = next;
    this.api.setInteractive(next);
  }

  onMouseMove(e) {
    // Sürükleme sırasında imleç sprite'tan çıksa bile pencere tıklanabilir kalmalı,
    // yoksa hızlı sürüklemede pet elden kaçıyor.
    if (!this.drag) this.setInteractive(this.isOverSprite(e.clientX, e.clientY));

    if (!this.drag) return;

    const dx = e.screenX - this.drag.startScreenX;
    const dy = e.screenY - this.drag.startScreenY;

    if (!this.drag.moved && Math.hypot(dx, dy) > CLICK_MOVE_THRESHOLD) {
      this.drag.moved = true;
      this.canvas.classList.add('dragging');
      this.setState(STATE.DRAGGING);
    }

    if (!this.drag.moved) return;

    this.x = e.screenX - this.drag.offsetX;
    this.y = e.screenY - this.drag.offsetY;
    this.api.move(this.x, this.y);
  }

  async onMouseUp(e) {
    if (!this.drag) return;
    const drag = this.drag;
    this.drag = null;
    this.canvas.classList.remove('dragging');

    const duration = performance.now() - drag.startTime;

    if (!drag.moved && duration < CLICK_TIME_THRESHOLD) {
      this.react();
      return;
    }

    // Sürükleme bitti: bırakıldığı monitörün çalışma alanına göre yere otur
    this.workArea = await this.api.getWorkArea({
      x: this.x + this.windowSize.width / 2,
      y: this.y + this.windowSize.height / 2
    });
    this.snapToGround();
    this.clampToWorkArea();
    this.api.move(this.x, this.y);
    this.setState(STATE.IDLE);

    // Sürükleme bitti: imleç hâlâ pet'in üstünde mi, yeniden bak.
    this.setInteractive(this.isOverSprite(e.clientX, e.clientY));
  }

  react() {
    const line = this.lines[Math.floor(Math.random() * this.lines.length)];
    this.bubble.show(line, REACT_DURATION);
    // REACTING'e girmek için önce state'i sıfırla (art arda tıklamada süre yenilensin)
    this.state = STATE.IDLE;
    this.setState(STATE.REACTING);
  }

  /* ------------------------------ yardımcı ------------------------------ */

  /**
   * Pencerenin sol kenarı ile karakterin görünen sol kenarı arasındaki mesafe.
   * Yürüme sınırları pencereye değil BUNA dayanmalı: pencere sprite'tan geniş
   * (balon payı) ve kare kutunun kendi boş kenarı var; ikisi toplandığında pet
   * ekranın kenarına ~55 piksel kala duruyordu.
   */
  spriteInset() {
    return (this.windowSize.width - this.canvasSize) / 2 + this.contentMargin * this.scale;
  }

  /** Pencere X'inin gidebileceği aralık — karakterin kendisi ekran kenarına değsin. */
  walkBounds() {
    const wa = this.workArea;
    const inset = this.spriteInset();
    return {
      minX: wa.x - inset,
      maxX: wa.x + wa.width - (this.windowSize.width - inset)
    };
  }

  /** Pet'i çalışma alanının altına (dock/taskbar üstüne) sabitle. */
  snapToGround() {
    // footGap: kare kutusunun altında kalan boş piksel. Pencereyi o kadar aşağı
    // kaydırmazsak karakter dock çizgisinin birkaç piksel üstünde havada durur.
    this.y = this.workArea.y + this.workArea.height
      - this.windowSize.height + this.footGap * this.scale;
  }

  clampToWorkArea() {
    const { minX, maxX } = this.walkBounds();
    this.x = Math.max(minX, Math.min(maxX, this.x));
  }
}

/**
 * Karakterin ekran ölçeği. Varsayılan 1:1 — native çözünürlük neyse ekranda o.
 * Aykırı bir karakter (çok küçük ya da çok büyük native ızgara) gelirse
 * meta.json'a TAM SAYI bir `displayScale` yazılır; kesirli ölçek pixel art'ı
 * bulanıklaştırdığı için otomatik hesaplanmıyor, kararı insan veriyor.
 *
 * Eski meta.json'lardaki `displayHeight` hâlâ okunuyor: kare kutusuna oranı
 * en yakın tam sayıya yuvarlanıyor.
 */
function resolveScale(character) {
  const { meta, nativeFrameSize } = character;

  if (meta.displayScale != null) {
    const s = Math.round(meta.displayScale);
    if (Number.isFinite(s) && s >= 1) return s;
    console.warn(`displayScale geçersiz (${meta.displayScale}), 1 kullanılıyor.`);
    return 1;
  }

  if (meta.displayHeight && nativeFrameSize) {
    return Math.max(1, Math.round(meta.displayHeight / nativeFrameSize));
  }
  return 1;
}

window.addEventListener('DOMContentLoaded', () => {
  const pet = new Pet({
    canvas: document.getElementById('pet'),
    bubbleEl: document.getElementById('bubble'),
    api: window.petAPI
  });
  pet.init().catch((err) => console.error('Pet başlatılamadı:', err));
});
