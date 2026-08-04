/** Pet'in üstünde birkaç saniye görünen konuşma balonu. */
class SpeechBubble {
  /** @param {HTMLElement} el */
  constructor(el) {
    this.el = el;
    this.timer = null;
    this.hideTimer = null;
  }

  /** @param {string} text @param {number} duration ms */
  show(text, duration = 2600) {
    clearTimeout(this.timer);
    clearTimeout(this.hideTimer);

    this.el.textContent = text;
    this.el.classList.remove('hidden');
    // Bir frame bekle ki transition tetiklensin
    requestAnimationFrame(() => this.el.classList.add('visible'));

    this.timer = setTimeout(() => this.hide(), duration);
  }

  hide() {
    this.el.classList.remove('visible');
    this.hideTimer = setTimeout(() => this.el.classList.add('hidden'), 200);
  }

  get isVisible() {
    return this.el.classList.contains('visible');
  }
}
