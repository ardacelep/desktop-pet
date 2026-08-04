/* global SpriteAnimator, SpeechBubble, loadImage */

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

    this.stateTimer = 0;
    this.nextIdleWait = this.randomIdleWait();
    this.lastFrameTime = 0;

    this.drag = null;
  }

  /* ------------------------------ kurulum ------------------------------ */

  async init() {
    const config = await this.api.getConfig();

    this.windowSize = { width: config.window.width, height: config.window.height };
    this.x = config.window.x;
    this.y = config.window.y;
    this.workArea = config.workArea;

    await this.applyCharacter(config.character);

    this.snapToGround();
    this.clampToWorkArea();
    this.api.move(this.x, this.y);

    this.bindEvents();
    this.setState(STATE.IDLE);

    this.lastFrameTime = performance.now();
    requestAnimationFrame((t) => this.loop(t));
  }

  /** @param {any} character characters.json kaydı + meta.json */
  async applyCharacter(character) {
    const { meta, baseUrl, nativeFrameSize, displayHeight } = character;

    const names = ['idle', 'walk_right', 'walk_left'];
    const clips = {};
    for (const name of names) {
      const def = meta[name];
      if (!def) continue;
      clips[name] = {
        key: name,
        image: await loadImage(baseUrl + def.file),
        frameSize: def.frameSize ?? nativeFrameSize,
        frameCount: def.frameCount,
        frameDuration: def.frameDuration,
        flip: Boolean(def.flip)
      };
    }

    this.clips = clips;
    this.lines = meta.lines?.length ? meta.lines : ['...'];
    this.walkSpeed = meta.walkSpeed ?? 40;

    // Farklı karakterlerin native çözünürlüğü farklı olabilir; ekranda hepsi
    // displayHeight kadar görünsün diye CSS boyutunu burada normalize ediyoruz.
    const size = displayHeight ?? nativeFrameSize;
    this.canvas.style.width = `${size}px`;
    this.canvas.style.height = `${size}px`;

    this.playClip(this.state === STATE.WALKING ? this.walkClipName() : 'idle');
  }

  bindEvents() {
    this.canvas.addEventListener('mousedown', (e) => this.onMouseDown(e));
    window.addEventListener('mousemove', (e) => this.onMouseMove(e));
    window.addEventListener('mouseup', (e) => this.onMouseUp(e));

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
  }

  randomIdleWait() {
    return IDLE_MIN + Math.random() * (IDLE_MAX - IDLE_MIN);
  }

  pickNewWalkTarget() {
    const wa = this.workArea;
    const maxX = wa.x + wa.width - this.windowSize.width;
    const target = wa.x + Math.random() * (maxX - wa.x);

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

    const wa = this.workArea;
    const minX = wa.x;
    const maxX = wa.x + wa.width - this.windowSize.width;

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

  onMouseMove(e) {
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
  }

  react() {
    const line = this.lines[Math.floor(Math.random() * this.lines.length)];
    this.bubble.show(line, REACT_DURATION);
    // REACTING'e girmek için önce state'i sıfırla (art arda tıklamada süre yenilensin)
    this.state = STATE.IDLE;
    this.setState(STATE.REACTING);
  }

  /* ------------------------------ yardımcı ------------------------------ */

  /** Pet'i çalışma alanının altına (dock/taskbar üstüne) sabitle. */
  snapToGround() {
    this.y = this.workArea.y + this.workArea.height - this.windowSize.height;
  }

  clampToWorkArea() {
    const wa = this.workArea;
    const maxX = wa.x + wa.width - this.windowSize.width;
    this.x = Math.max(wa.x, Math.min(maxX, this.x));
  }
}

window.addEventListener('DOMContentLoaded', () => {
  const pet = new Pet({
    canvas: document.getElementById('pet'),
    bubbleEl: document.getElementById('bubble'),
    api: window.petAPI
  });
  pet.init().catch((err) => console.error('Pet başlatılamadı:', err));
});
