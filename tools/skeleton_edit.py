#!/usr/bin/env python3
"""
skeleton_edit.py — sprite'i surukle, iskeleti otomatik cikar, elle duzelt.

    npm run skeleton          (ya da: python3 tools/skeleton_edit.py)

NEDEN BU ARAC VAR
    Otomatik tespitin genel bir garantisi YOK ve olculdu: `skeleton.py`
    insansi, iki bacakli, bacaklari ayrilan ve ~32 pikselden buyuk figurlerde
    calisiyor; cubbeli bir karakterde iki ayak tek noktaya cokuyor, dort
    ayaklida kalca boynun USTUNE cikiyor, 16 piksellik sprite'ta zincir
    capraziyor.

    Bu bir eksiklik degil, alanin yapisi. Meta'nin CIZIMLER uzerinde egitilmis
    modeli de "insansi iskelet varsayiyor" deyip insansi olmayan icin elle
    iskelet tanimi istiyor; PixelLab'in kendi urununde de "edit skeleton"
    ekrani var. Ciddi her arac otomatik tespiti elle duzeltmeyle esliyor.

TASARIM
    Bagimlilik yok: sunucu saf standart kutuphane, sayfa tek dosya HTML,
    sprite base64 olarak icine gomuluyor.

    Sprite tarayiciya SURUKLENIYOR, tespit sunucuda yapiliyor. Boyle olmasinin
    sebebi tespit algoritmasinin tek yerde kalmasi: JS'te ikinci bir kopya
    yazilsaydi iki uygulama sessizce birbirinden ayrilirdi.

    Kaydetme geri POST ile geliyor; kullanicinin indirilenler klasorunden
    dosya tasimasi gerekmiyor.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import http.server
import io
import json
import os
import sys
import threading
import webbrowser

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skeleton as sk  # noqa: E402


def en_guncel_model(kok: str) -> str | None:
    """En yeni URETIM modelini bulur. IKI yere birden bakar.

        models/          depoda, Git LFS ile gelir — KLONLAYANIN elindeki tek
                         model burasidir
        _data/modeller/  yerel egitim ciktisi; `_data/` gitignore'da, yani
                         yalnizca burada egitim yapmis kiside bulunur

    Ikisine birden bakmak sart: yalnizca `_data/` aransaydi klonlayan kisi
    LFS ile modeli almis olmasina ragmen sezgisele duserdi. Yalnizca
    `models/` aransaydi, yerel egitim yapan kisi taze modelini goremezdi.
    Ikisinden EN YENISI seciliyor.

    Neden yalnizca URETIM modelleri: `_data/modeller/` icindeki digerleri
    OLCUM icin egitildi ve her biri bir karakteri disarida birakiyor
    (mchen_mag.pt mag'i hic gormedi). Genelleme olcmek icin dogru, kullanmak
    icin yanlis — elimizdeki veriyi bilerek eksik kullanmis oluruz.

    Uretim modeli yoksa None doner ve cagiran sezgisele duser; sessizce bir
    olcum modeline dusmek yanlis olurdu."""
    import glob
    adaylar = []
    for dizin in (os.path.join(kok, "models"),
                  os.path.join(kok, "_data", "modeller")):
        for p in glob.glob(os.path.join(dizin, "*.pt")):
            try:
                import torch
                k = torch.load(p, map_location="cpu").get("kunye") or {}
            except Exception:                                      # noqa: BLE001
                # LFS cekilmemisse dosya birkac yuz baytlik bir ISARETCI olur
                # ve torch onu acamaz. Sessizce atlamak yanlis olurdu.
                if os.path.getsize(p) < 4096:
                    print(f"UYARI: {p} bir Git LFS isaretcisi — model henuz "
                          f"indirilmemis. `git lfs pull` calistirin.",
                          file=sys.stderr)
                continue
            if k.get("uretim"):
                adaylar.append((k.get("tarih", ""), os.path.getmtime(p), p))
    return max(adaylar)[2] if adaylar else None


class _Tahminci:
    """Iskeleti kim cikariyor: POZ MODELI, yoksa sezgisel algoritma.

    Model varsayilan, cunku olculdu (dort holdout):
        skeleton.py  gorulmemis karakterde 13.46px; yandan gorunuste kalcayi
                     18.6px sasiriyor ve NECK>HIP iki bacak zincirinin de koku
                     oldugu icin altindaki her sey kayiyor
        poz modeli   onden 1.51px, yandan 4.06px

    Sezgisel yol yine de duruyor: bagimliliksiz calisiyor ve checkpoint
    bulunamadiginda tek secenek o. Hangisinin kullanildigi arayuze
    bildiriliyor — kullanici neye baktigini bilmeli."""

    def __init__(self, ckpt: str | None):
        self.ad, self._model, self._dev, self._tuval = "sezgisel", None, None, 128
        if not ckpt:
            return
        try:
            import pose_model as pm
            import torch
            d = torch.load(ckpt, map_location="cpu")
            self._model = pm.PozModeli(d["tuval"], len(sk.LABELS),
                                       on_egitimli=False, derinlik=d["derinlik"])
            self._model.load_state_dict(d["model"])
            self._dev = pm.aygit()
            self._model.to(self._dev).eval()
            self._tuval, self._pm = d["tuval"], pm
            self.ad = "model"
        except Exception as err:                                  # noqa: BLE001
            print(f"UYARI: poz modeli yuklenemedi ({err}); sezgisel tahminciye "
                  f"dusuluyor.", file=sys.stderr)

    # Egitim verisinde siluet yuksekligi medyani 122px, %5 dilimi 91px.
    # Hedef bunun biraz altina, 100'e konuldu: tam sayi kati zorunlulugu
    # yuzunden tam 122'ye oturmak mumkun degil ve hedefi yuksek tutmak kucuk
    # sprite'larda gereksiz buyuk katlar seciyor.
    HEDEF_SILUET = 100

    def _buyutme_kati(self, kare: np.ndarray) -> int:
        opak = kare[:, :, 3] > 0
        ys, _ = np.where(opak)
        if ys.size == 0:
            return 1
        boy = int(ys.max() - ys.min() + 1)
        if boy <= 0:
            return 1
        # ASAGI yuvarlaniyor, yakina degil: hedefi asmak olculdu ve zarar
        # veriyor. 63px'lik bir siluette round 2 kat secip 126px'e cikariyor
        # ve hata 2.04'ten 2.90'a yukseliyor; asagi yuvarlayinca 1 katta
        # kalip 2.04'te kaliyor. Yani "biraz kucuk" "biraz buyuk"ten iyi.
        return max(1, min(8, int(self.HEDEF_SILUET / boy)))

    def __call__(self, kare: np.ndarray, yon: str) -> sk.Iskelet:
        if self._model is None:
            return sk.estimate(kare, direction=yon)
        import torch
        import pose_dataset as pdset

        # KUCUK SPRITE'I ONCE BUYUT. `kanvasa_yerlestir` bilerek buyutmuyor —
        # egitim verisi uretirken dogru karar, cunku pixel art'i buyutmek
        # sahte ara tonlar uretir. Ama CIKARIMDA tam tersi gerekiyor: model
        # karakteri egitimde gordugu boyda gormeli.
        #
        # Olculdu, ael idle karesi farkli boylarda:
        #     21px sprite -> 29.18px hata      65px -> 2.04px
        #     34px        ->  9.01px           87px -> 0.52px
        #     43px        ->  6.94px          261px -> 3.31px
        # Egitim verisinde siluet yuksekligi medyani 122px (%5 dilimi 91).
        # Yani 50 pikselin altindaki bir sprite dagilimin tamamen disinda
        # kaliyor ve cikti kullanilamaz oluyor. Pixel art genelde 32x32 ya da
        # 48x48 oldugu icin bu nadir bir durum degil, olagan durum.
        #
        # Buyutme TAM SAYI katiyla ve NEAREST ile: ara ton uretmiyor, yalnizca
        # her pikseli bir bloga ceviriyor. Cikti koordinatlari sonunda ayni
        # katsayiya bolunerek KAREYE geri tasiniyor.
        kat = self._buyutme_kati(kare)
        if kat > 1:
            from PIL import Image as _I
            kare = np.array(_I.fromarray(kare).resize(
                (kare.shape[1] * kat, kare.shape[0] * kat), _I.NEAREST))

        # Model, egitimde gordugu tuvale gore calisiyor: kare ortalanip
        # `tuval` boyutuna yerlestiriliyor. Donusum degerleri saklaniyor ki
        # cikti KAREYE geri tasinabilsin.
        tuval, olcek, dx, dy = pdset.kanvasa_yerlestir(kare, self._tuval)
        olcek, dx, dy = olcek * kat, dx, dy
        # Girdi normalizasyonu pose_model.Kume ile BIREBIR ayni olmali.
        rgb = np.where(tuval[:, :, 3:4] > 0, tuval[:, :, :3], 255).astype(np.float32) / 255.0
        x = rgb.transpose(2, 0, 1)
        ort = np.array([0.485, 0.456, 0.406], np.float32).reshape(3, 1, 1)
        std = np.array([0.229, 0.224, 0.225], np.float32).reshape(3, 1, 1)
        x = np.ascontiguousarray((x - ort) / std, dtype=np.float32)[None]
        with torch.no_grad():
            xl, yl = self._model(torch.from_numpy(x).to(self._dev))
            px, py = self._pm.koordinat_coz(xl, yl, self._tuval)
        p = torch.stack([px, py], -1).cpu().numpy()[0]
        noktalar = {l: ((float(p[i][0]) - dx) / olcek, (float(p[i][1]) - dy) / olcek)
                    for i, l in enumerate(sk.LABELS)}
        # olculen/supheli sezgisel algoritmanin kavramlari; modelde karsiligi
        # yok, o yuzden bos. Arayuz bunlari yalnizca renklendirmede kullaniyor.
        return sk.Iskelet(noktalar=noktalar, z={}, olculen=frozenset(),
                          supheli=frozenset())


SAYFA = r"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<title>Iskelet duzenleyici</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
         background:#14161a; color:#e6e6e6; display:flex; height:100vh; }
  #sol { flex:1; display:flex; align-items:center; justify-content:center;
         overflow:auto; position:relative; background:
           repeating-conic-gradient(#1c1f24 0 25%, #242830 0 50%) 0 0/24px 24px; }
  #sol.uzerinde::after { content:"birak"; position:absolute; inset:12px;
         border:2px dashed #4f9dd9; border-radius:10px; display:flex;
         align-items:center; justify-content:center; font-size:20px;
         color:#4f9dd9; background:#4f9dd922; pointer-events:none; }
  canvas { image-rendering:pixelated; cursor:crosshair; }
  #bosluk { text-align:center; color:#7d8592; padding:40px; max-width:420px; }
  #bosluk b { color:#c8cdd6; display:block; font-size:15px; margin-bottom:8px; }
  #yan { width:300px; padding:14px; background:#1a1d22; overflow-y:auto;
         border-left:1px solid #2b3038; }
  h1 { font-size:14px; margin:0 0 4px; }
  .alt { color:#8b93a1; font-size:11px; margin:0 0 12px; word-break:break-all; }
  button, select, input[type=number] { font:inherit; padding:6px 9px; margin:0 4px 6px 0;
      cursor:pointer; background:#272c34; color:#e6e6e6; border:1px solid #39404a;
      border-radius:5px; }
  button:hover:not(:disabled) { background:#323842; }
  button:disabled { opacity:.4; cursor:default; }
  button.ana { background:#2f6f43; border-color:#3d8a55; }
  label { font-size:11px; color:#8b93a1; display:block; margin:8px 0 2px; }
  ul { list-style:none; padding:0; margin:10px 0 0; font-size:11px; }
  li { padding:3px 6px; border-radius:4px; display:flex; justify-content:space-between;
       cursor:pointer; }
  li:hover { background:#242932; }
  li.secili { background:#2f4a6f; }
  .olculdu { color:#ff6b6b; }  .turetildi { color:#ffd93d; }
  .supheli { color:#ff8c1a; font-weight:700; }
  .ipucu { margin-top:14px; font-size:11px; color:#8b93a1; }
  .ipucu b { color:#c8cdd6; font-weight:600; }
  #durum { margin-top:8px; font-size:11px; min-height:32px; color:#9fd3a0; }
  #durum.hata { color:#ff8b8b; }
</style></head><body>
<div id="sol">
  <div id="bosluk"><b>Sprite'i buraya surukle</b>
    PNG — tek kare ya da yatay serit.<br>Iskelet otomatik cikarilir,
    sonra eklemleri elle duzeltirsin.<br><br>
    <button onclick="document.getElementById('dosya').click()">dosya sec</button>
    <input id="dosya" type="file" accept="image/png,image/*" hidden
           onchange="dosyaOku(this.files[0])">
  </div>
  <canvas id="tuval" hidden></canvas>
</div>
<div id="yan">
  <h1>Iskelet duzenleyici</h1>
  <p class="alt" id="bilgi">sprite bekleniyor</p>

  <label>Bakis yonu — idle genelde onden, walk yandan</label>
  <select id="yon" onchange="tespit()">
    <option value="south">south · one bakan</option>
    <option value="north">north · sirti donuk</option>
    <option value="east">east · saga bakan</option>
    <option value="west">west · sola bakan</option>
  </select>

  <div id="kare_kutu" hidden>
    <label>Kare (<span id="kare_say">1</span> kare bulundu)</label>
    <button onclick="kareGec(-1)">‹ onceki</button>
    <span id="kare_no">0</span>
    <button onclick="kareGec(1)">sonraki ›</button>
  </div>

  <label>Goruntu</label>
  <button onclick="yakinlik(-2)">− kucult</button>
  <button onclick="yakinlik(2)">+ buyut</button>
  <button onclick="tespit()">yeniden tespit</button>

  <div style="margin-top:10px">
    <button class="ana" id="kaydet_btn" onclick="kaydet()" disabled>Kaydet</button>
  </div>
  <div id="durum"></div>
  <ul id="liste"></ul>
  <p class="ipucu">
    <b>Surukle</b> eklemi tasir · <b>ok tuslari</b> 1 piksel ·
    <b>Shift+ok</b> 5 piksel · <b>Tab</b> siradaki eklem.<br><br>
    Suruklerken hiza cizgileri cikar ve yakinsan kilitler:<br>
    <span style="color:#ff58d8">▮</span> govde ekseni ·
    <span style="color:#59e0a0">▮</span> ayna / es eklem ·
    <span style="color:#7fb2ff">▮</span> baska bir eklem.<br>
    <b>Alt</b> basili tutarsan kilitleme kapanir.<br><br>
    <span class="olculdu">■</span> olculdu ·
    <span class="supheli">■</span> zayif sinyal ·
    <span class="turetildi">■</span> turetildi<br>
    Turuncular bu karakterin cizim tarzinda ISARETI OLMAYAN eklemler —
    once onlari duzelt.
  </p>
</div>
<script>
const KEMIK = __KEMIK__, LABELS = __LABELS__;
let durum = null;               // {sprite,w,h,kare,kare_say,noktalar,olculen,ad}
let olcek = 8, secili = null, suruklenen = null, im = null;
let kilavuz = [];               // o an gosterilen hiza cizgileri
const YAPIS = 1.5;              // native piksel — bu kadar yaklasinca kilitlenir

/* Hiza yardimcisi. Iskelette en cok ise yarayan uc hiza var:
   - ES eklem: omuzlar ayni yukseklikte, kalcalar ayni yukseklikte, gozler
     ayni hizada olmali. Bunu gozle tutturmak zor, kilit kolay.
   - AYNA: sag/sol es eklem govde ekseninde simetrik olmali.
   - GOVDE EKSENI: burun, boyun, kasik hep o dikey cizgide.
   Alt tusu basiliyken yapisma kapaniyor — bilerek hafif kaydirmak icin. */
function esNokta(ad) {
  if (ad.startsWith('RIGHT ')) return 'LEFT ' + ad.slice(6);
  if (ad.startsWith('LEFT ')) return 'RIGHT ' + ad.slice(5);
  return null;
}
function hizala(ad, x, y, kapali) {
  const cizgiler = [];
  if (kapali) return {x, y, cizgiler};
  const merkez = durum.merkez_x;
  const es = esNokta(ad), esN = es && durum.noktalar[es];

  let enX = null, dX = YAPIS;
  const adayX = [];
  if (merkez != null) adayX.push([merkez, 'merkez']);
  if (esN) adayX.push([2 * merkez - esN[0], 'ayna']);
  for (const b of LABELS) if (b !== ad) adayX.push([durum.noktalar[b][0], 'eklem']);
  for (const [v, tur] of adayX) {
    if (Math.abs(v - x) < dX) { dX = Math.abs(v - x); enX = [v, tur]; }
  }

  let enY = null, dY = YAPIS;
  const adayY = [];
  if (esN) adayY.push([esN[1], 'es']);
  for (const b of LABELS) if (b !== ad) adayY.push([durum.noktalar[b][1], 'eklem']);
  for (const [v, tur] of adayY) {
    if (Math.abs(v - y) < dY) { dY = Math.abs(v - y); enY = [v, tur]; }
  }

  if (enX) { x = enX[0]; cizgiler.push(['dikey', x, enX[1]]); }
  if (enY) { y = enY[0]; cizgiler.push(['yatay', y, enY[1]]); }
  return {x, y, cizgiler};
}

const sol = document.getElementById('sol'), tuval = document.getElementById('tuval');
const ctx = tuval.getContext('2d');

/* ---- sprite alma ---- */
['dragenter','dragover'].forEach(e => sol.addEventListener(e, ev => {
  ev.preventDefault(); sol.classList.add('uzerinde'); }));
['dragleave','drop'].forEach(e => sol.addEventListener(e, ev => {
  ev.preventDefault(); sol.classList.remove('uzerinde'); }));
sol.addEventListener('drop', ev => {
  const f = ev.dataTransfer.files[0];
  if (f) dosyaOku(f); else bildir('dosya bulunamadi', true);
});
function dosyaOku(f) {
  if (!f) return;
  const r = new FileReader();
  r.onload = () => { durum = {sprite: r.result, ad: f.name}; tespit(true); };
  r.onerror = () => bildir('dosya okunamadi', true);
  r.readAsDataURL(f);
}

/* ---- tespit sunucuda ---- */
async function tespit(yeni = false) {
  if (!durum || !durum.sprite) return;
  bildir('tespit ediliyor…');
  try {
    const r = await fetch('/detect', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({sprite: durum.sprite, ad: durum.ad,
        yon: document.getElementById('yon').value,
        kare: yeni ? 0 : (durum.kare || 0)})});
    const g = await r.json();
    if (!r.ok) { bildir(g.hata || 'tespit basarisiz', true); return; }
    durum = Object.assign(durum, g);
    im = new Image(); im.src = durum.sprite_kare; im.onload = ciz;
    document.getElementById('kaydet_btn').disabled = false;
    document.getElementById('bosluk').hidden = true;
    tuval.hidden = false;
    document.getElementById('kare_kutu').hidden = durum.kare_say < 2;
    document.getElementById('kare_say').textContent = durum.kare_say;
    document.getElementById('kare_no').textContent = durum.kare;
    document.getElementById('bilgi').textContent =
      `${durum.ad} · ${durum.w}x${durum.h} · ${durum.olculen.length}/18 olculdu`
      + ((durum.supheli||[]).length ? ` · ${durum.supheli.length} zayif sinyal` : '');
    bildir(`hazir — kaydedilecek: ${durum.cikti}`);
  } catch (e) { bildir(String(e), true); }
}
function kareGec(d) {
  if (!durum) return;
  durum.kare = Math.max(0, Math.min(durum.kare_say - 1, (durum.kare || 0) + d));
  tespit();
}
function bildir(m, hata=false) {
  const d = document.getElementById('durum');
  d.textContent = m; d.className = hata ? 'hata' : '';
}

/* ---- cizim ---- */
function ciz() {
  if (!durum || !im) return;
  tuval.width = durum.w * olcek; tuval.height = durum.h * olcek;
  ctx.imageSmoothingEnabled = false;
  ctx.clearRect(0,0,tuval.width,tuval.height);
  ctx.drawImage(im, 0, 0, tuval.width, tuval.height);

  for (const [yon, v, tur] of kilavuz) {
    ctx.save();
    ctx.strokeStyle = tur === 'merkez' ? '#ff58d8'
                    : (tur === 'ayna' || tur === 'es') ? '#59e0a0' : '#7fb2ff';
    ctx.lineWidth = 1; ctx.setLineDash([6, 4]);
    ctx.beginPath();
    if (yon === 'dikey') { ctx.moveTo((v+.5)*olcek, 0); ctx.lineTo((v+.5)*olcek, tuval.height); }
    else { ctx.moveTo(0, (v+.5)*olcek); ctx.lineTo(tuval.width, (v+.5)*olcek); }
    ctx.stroke(); ctx.restore();
  }

  ctx.lineWidth = Math.max(1, olcek/5);
  ctx.strokeStyle = 'rgba(0,200,255,.75)';
  for (const [a,b] of KEMIK) {
    ctx.beginPath();
    ctx.moveTo((durum.noktalar[a][0]+.5)*olcek, (durum.noktalar[a][1]+.5)*olcek);
    ctx.lineTo((durum.noktalar[b][0]+.5)*olcek, (durum.noktalar[b][1]+.5)*olcek);
    ctx.stroke();
  }
  for (const ad of LABELS) {
    const [x,y] = durum.noktalar[ad];
    const sup = (durum.supheli||[]).includes(ad), oz = durum.olculen.includes(ad);
    const r = olcek * (ad===secili ? .55 : (sup ? .5 : oz ? .42 : .3));
    ctx.beginPath(); ctx.arc((x+.5)*olcek, (y+.5)*olcek, r, 0, 7);
    ctx.fillStyle = sup ? '#ff8c1a' : oz ? '#ff6b6b' : '#ffd93d'; ctx.fill();
    if (ad === secili) { ctx.strokeStyle='#fff'; ctx.lineWidth=Math.max(1,olcek/6); ctx.stroke(); }
  }
  listele();
}
function listele() {
  document.getElementById('liste').innerHTML = LABELS.map(a =>
    `<li class="${a===secili?'secili':''}" onclick="sec('${a}')">
       <span class="${(durum.supheli||[]).includes(a)?'supheli':durum.olculen.includes(a)?'olculdu':'turetildi'}">${a}</span>
       <span>${durum.noktalar[a][0].toFixed(1)}, ${durum.noktalar[a][1].toFixed(1)}</span></li>`
  ).join('');
}
function sec(a){ secili = a; ciz(); }
function yakinlik(d){ olcek = Math.max(2, Math.min(30, olcek+d)); ciz(); }

/* ---- surukle-birak duzenleme ---- */
function yerel(e) {
  const r = tuval.getBoundingClientRect();
  return [(e.clientX-r.left)/olcek - .5, (e.clientY-r.top)/olcek - .5];
}
tuval.addEventListener('mousedown', e => {
  if (!durum) return;
  const [x,y] = yerel(e);
  let iyi=null, d2=1e9;
  for (const a of LABELS) {
    const dx=durum.noktalar[a][0]-x, dy=durum.noktalar[a][1]-y, d=dx*dx+dy*dy;
    if (d<d2) { d2=d; iyi=a; }
  }
  if (d2 <= 36) { secili = suruklenen = iyi; ciz(); }
});
addEventListener('mousemove', e => {
  if (!suruklenen) return;
  const [hx,hy] = yerel(e);
  const h = hizala(suruklenen, Math.round(hx*2)/2, Math.round(hy*2)/2, e.altKey);
  durum.noktalar[suruklenen] = [h.x, h.y];
  kilavuz = h.cizgiler;
  ciz();
});
addEventListener('mouseup', () => { suruklenen = null; kilavuz = []; ciz(); });
addEventListener('keydown', e => {
  if (!durum) return;
  if (e.key === 'Tab') {
    e.preventDefault();
    secili = LABELS[(LABELS.indexOf(secili)+1) % LABELS.length]; ciz(); return;
  }
  if (!secili) return;
  const yon = {ArrowLeft:[-1,0], ArrowRight:[1,0], ArrowUp:[0,-1], ArrowDown:[0,1]}[e.key];
  if (!yon) return;
  e.preventDefault();
  const adim = e.shiftKey ? 5 : 1;
  const p = durum.noktalar[secili];
  durum.noktalar[secili] = [p[0]+yon[0]*adim, p[1]+yon[1]*adim];
  ciz();
});

async function kaydet() {
  if (!durum) return;
  bildir('kaydediliyor…');
  try {
    const r = await fetch('/save', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({noktalar: durum.noktalar, kare: durum.kare,
                            ad: durum.ad, yon: document.getElementById('yon').value})});
    const g = await r.json();
    bildir(r.ok ? `✓ kaydedildi: ${g.yol}` : (g.hata || 'kaydedilemedi'), !r.ok);
  } catch (e) { bildir(String(e), true); }
}
</script></body></html>
"""


def _kareyi_cikar(rgba: np.ndarray, kare: int, kutu: int | None) -> tuple[np.ndarray, int]:
    """Yatay seritten kareyi ayirir; (kare, toplam_kare) doner."""
    k = kutu or rgba.shape[0]
    if k > 0 and rgba.shape[1] % k == 0 and rgba.shape[1] // k > 1:
        n = rgba.shape[1] // k
        kare = max(0, min(n - 1, kare))
        return rgba[:, kare * k:(kare + 1) * k], n
    return rgba, 1


def _png_datauri(a: np.ndarray) -> str:
    t = io.BytesIO()
    Image.fromarray(a).save(t, format="PNG")
    return "data:image/png;base64," + base64.b64encode(t.getvalue()).decode()


class Durum:
    """Sunucunun tuttugu tek oturumluk durum."""

    def __init__(self, cikti: str | None, kutu: int | None,
                 tahminci: "_Tahminci | None" = None):
        self.cikti = cikti
        self.kutu = kutu
        self.z: dict[str, float] = {}
        self.tahminci = tahminci or _Tahminci(None)

    def cikti_yolu(self, ad: str, kare: int) -> str:
        if self.cikti:
            return self.cikti
        kok = os.path.splitext(os.path.basename(ad or "iskelet"))[0]
        return os.path.abspath(f"{kok}_iskelet_{kare}.json")


def _sunucu(sayfa: str, durum: Durum, port: int, tarayici_ac: bool) -> None:
    class Islem(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, kod: int, govde: dict):
            veri = json.dumps(govde).encode()
            self.send_response(kod)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(veri)))
            self.end_headers()
            self.wfile.write(veri)

        def _govde(self) -> dict:
            n = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(n)) if n else {}

        def do_GET(self):
            g = sayfa.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(g)))
            self.end_headers()
            self.wfile.write(g)

        def do_POST(self):
            try:
                govde = self._govde()
            except (ValueError, json.JSONDecodeError) as err:
                self._json(400, {"hata": f"gecersiz istek: {err}"})
                return
            if self.path == "/detect":
                self._detect(govde)
            elif self.path == "/save":
                self._save(govde)
            else:
                self._json(404, {"hata": "bilinmeyen uc"})

        def _detect(self, govde: dict):
            try:
                veri = govde["sprite"].split(",", 1)[1]
                rgba = np.array(Image.open(io.BytesIO(base64.b64decode(veri)))
                                .convert("RGBA"))
            except (KeyError, IndexError, binascii.Error, OSError, ValueError) as err:
                self._json(400, {"hata": f"gorsel okunamadi: {err}"})
                return
            kare, toplam = _kareyi_cikar(rgba, int(govde.get("kare", 0)), durum.kutu)
            try:
                isk = durum.tahminci(kare, govde.get("yon", "south"))
            except ValueError as err:
                self._json(400, {"hata": str(err)})
                return
            durum.z = {a: float(v) for a, v in isk.z.items()}
            # Govde ekseni: siluet kutusunun ortasi. Hiza kilavuzu bunu
            # "merkez" cizgisi ve ayna ekseni olarak kullaniyor.
            xs = np.where((kare[:, :, 3] > 0).any(axis=0))[0]
            merkez = float((int(xs.min()) + int(xs.max())) / 2.0) if xs.size else None
            self._json(200, {
                "sprite_kare": _png_datauri(kare),
                "merkez_x": merkez,
                "w": int(kare.shape[1]), "h": int(kare.shape[0]),
                "kare": int(govde.get("kare", 0)), "kare_say": int(toplam),
                "olculen": sorted(isk.olculen),
                "supheli": sorted(isk.supheli),
                "noktalar": {a: [round(float(x), 1), round(float(y), 1)]
                             for a, (x, y) in isk.noktalar.items()},
                "cikti": durum.cikti_yolu(govde.get("ad", ""), int(govde.get("kare", 0))),
            })

        def _save(self, govde: dict):
            try:
                ham = govde["noktalar"]
                isk = sk.Iskelet({a: (float(v[0]), float(v[1])) for a, v in ham.items()},
                                 dict(durum.z))
            except (KeyError, TypeError, ValueError) as err:
                self._json(400, {"hata": f"iskelet gecersiz: {err}"})
                return
            yol = durum.cikti_yolu(govde.get("ad", ""), int(govde.get("kare", 0)))
            try:
                with open(yol, "w") as f:
                    json.dump({"direction": govde.get("yon", "south"),
                               "frame": int(govde.get("kare", 0)),
                               "keypoints": isk.to_pixellab()}, f, indent=2)
            except OSError as err:
                self._json(400, {"hata": f"yazilamadi: {err}"})
                return
            print(f"Kaydedildi: {yol}")
            self._json(200, {"yol": yol})

    srv = http.server.HTTPServer(("127.0.0.1", port), Islem)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/"
    print(f"Iskelet duzenleyici: {url}")
    print("Sprite'i pencereye surukle. Kapatmak icin Ctrl-C.")
    if tarayici_ac:
        webbrowser.open(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nKapatildi.")
    srv.shutdown()


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Sprite'i surukle, iskeleti otomatik cikar, elle duzelt.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Ornek:\n  npm run skeleton\n  python3 tools/skeleton_edit.py")
    p.add_argument("-o", "--output", default=None,
                   help="Cikti JSON. Verilmezse sprite adindan turetilir.")
    p.add_argument("--frame-size", type=int, default=None,
                   help="Kare kutusu (varsayilan: goruntu yuksekligi)")
    p.add_argument("--model", default=None,
                   help="Poz modeli checkpoint'i. Verilmezse VARSAYILAN "
                        "aranir; o da yoksa sezgisel algoritmaya dusulur.")
    p.add_argument("--sezgisel", action="store_true",
                   help="Modeli hic kullanma. Olculdu: sezgisel tahminci "
                        "gorulmemis karakterde 13.46px, model 1.51-4.06px.")
    p.add_argument("--port", type=int, default=0, help="0 = bos port secilir")
    p.add_argument("--no-open", action="store_true",
                   help="Tarayiciyi kendiliginden acma")
    args = p.parse_args(argv)

    sayfa = (SAYFA
             .replace("__KEMIK__", json.dumps([list(k) for k in sk.KEMIKLER]))
             .replace("__LABELS__", json.dumps(list(sk.LABELS))))
    kok_proje = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ckpt = None if args.sezgisel else (args.model or en_guncel_model(kok_proje))
    tahminci = _Tahminci(ckpt)
    if tahminci.ad == "model":
        print(f"Iskelet tahmincisi: MODEL  ({os.path.basename(ckpt)})")
    else:
        print("Iskelet tahmincisi: SEZGISEL — uretim modeli bulunamadi.\n"
              "  Egitmek icin: ~/ComfyUI/venv/bin/python tools/pose_model.py "
              "train _data/karisik_yan --holdout yok \\\n"
              "                 --ckpt _data/modeller/uretim.pt")
    _sunucu(sayfa, Durum(args.output, args.frame_size, tahminci),
            args.port, not args.no_open)
    return 0


if __name__ == "__main__":
    sys.exit(main())
