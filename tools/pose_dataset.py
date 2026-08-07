#!/usr/bin/env python3
"""
pose_dataset.py — pixel art poz modeli icin etiketli veri toplar.

    python3 tools/pose_dataset.py characters/ -o _data/poz --limit 20

NE YAPIYOR
    Sprite'lari sabit bir tuvale ortalayip PixelLab'in `estimate-skeleton`
    ucuna etiketletiyor, sonucu diske biriktiriyor. Sonra bunu artirarak
    (aynalama, ton kaydirma, olcek/kaydirma) egitim setine cikariyor.

NEDEN BU TASARIM

    ONBELLEK ZORUNLU. Etiketleme UCRETLI (cagri basina 0.1 generation) ve
    deney sirasinda ayni goruntuye defalarca donuluyor. Onbellek goruntunun
    ICERIK HASH'iyle anahtarlaniyor; ayni pikseller bir daha asla
    ucretlendirilmiyor. Dosya adiyla anahtarlamak yetmezdi — ayni kare farkli
    yollardan gelebiliyor.

    ARTIRMA BEDAVA. Etiketi degistirmeyen ya da HESAPLANABILIR sekilde
    degistiren donusumler icin yeni cagri yapilmiyor:
      - aynalama: x -> 1-x ve sol/sag etiket takasi. PixelLab'in bunu dogru
        yaptigi olculdu (etiket takasiyla fark 0.0073), yani guvenli.
      - ton/palet kaydirma: geometri degismiyor, eklemler yerinde kaliyor.
      - olcek ve kaydirma: eklemler ayni donusumle tasiniyor.
    Yani API cagrisi KAYNAK KARE basina bir tane; artirma onu cogaltiyor.

    TUVAL SABIT. PixelLab 16/32/64/128/256 destekliyor ve olculdu: 91x91
    goruntu ile 128x128'e ortalanmis hali BIREBIR ayni sonucu veriyor. Model
    de dedektorsuz calisacagi icin (bkz. iki-karakter olcumu) girdi tuvalinin
    sabit ve karakterin ortali olmasi tasarimin parcasi, sinirlama degil.

CIKTI DUZENI
    <cikti>/gorseller/<hash>.png     128x128 RGBA
    <cikti>/etiketler.jsonl          her satir bir ornek
    <cikti>/onbellek/<hash>.json     ham API yaniti (bir daha ucret yok)
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import sys
import time

import numpy as np
import requests
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skeleton as sk  # noqa: E402

UC = "https://api.pixellab.ai/v2/estimate-skeleton"
BAKIYE_UCU = "https://api.pixellab.ai/v2/balance"
CAGRI_BASI = 0.1          # generation


def anahtar_oku(kok: str) -> str:
    """.env icinden API anahtarini okur. Deger hicbir yere basilmiyor."""
    yol = os.path.join(kok, ".env")
    if not os.path.exists(yol):
        raise SystemExit(f"HATA: {yol} yok. PIXELLAB_API_KEY= satiri gerekiyor.")
    for satir in open(yol):
        if satir.startswith("PIXELLAB_API_KEY="):
            d = satir.split("=", 1)[1].strip().strip('"').strip("'")
            if d:
                return d
    raise SystemExit("HATA: .env icinde PIXELLAB_API_KEY bulunamadi.")


def bakiye(gizli: str) -> tuple[float, float]:
    r = requests.get(BAKIYE_UCU, headers={"Authorization": f"Bearer {gizli}"}, timeout=30)
    r.raise_for_status()
    a = r.json().get("subscription", {})
    return float(a.get("generations", 0)), float(a.get("total", 0))


# ---------------------------------------------------------------------------
# Tuval
# ---------------------------------------------------------------------------

def kanvasa_yerlestir(rgba: np.ndarray, boyut: int = 128
                      ) -> tuple[np.ndarray, float, float, float]:
    """Sprite'i `boyut` kare tuvale ORTALAR; (tuval, olcek, dx, dy) doner.

    Karakter tuvale sigmiyorsa kucultuluyor — ama BUYUTULMUYOR: pixel art'i
    buyutmek sahte ara tonlar uretir ve modelin ogrenmesi gereken keskin
    kenar yapisini bozar."""
    ys, xs = np.where(rgba[:, :, 3] > 0)
    if ys.size == 0:
        raise ValueError("kare tamamen seffaf")
    y0, y1, x0, x1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
    kirp = rgba[y0:y1 + 1, x0:x1 + 1]
    h, w = kirp.shape[:2]

    olcek = min(1.0, (boyut - 4) / max(h, w))
    if olcek < 1.0:
        yh, yw = max(1, int(round(h * olcek))), max(1, int(round(w * olcek)))
        kirp = np.array(Image.fromarray(kirp).resize((yw, yh), Image.NEAREST))
        h, w = kirp.shape[:2]

    tuval = np.zeros((boyut, boyut, 4), np.uint8)
    dy, dx = (boyut - h) // 2, (boyut - w) // 2
    tuval[dy:dy + h, dx:dx + w] = kirp
    return tuval, olcek, float(dx - x0 * olcek), float(dy - y0 * olcek)


def _hash(a: np.ndarray) -> str:
    return hashlib.sha256(a.tobytes()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Etiketleme
# ---------------------------------------------------------------------------

def etiketle(tuval: np.ndarray, gizli: str, onbellek: str,
             deneme: int = 3) -> dict[str, list[float]]:
    """Tuvali etiketler. Onbellekte varsa API'ye GITMEZ."""
    h = _hash(tuval)
    yol = os.path.join(onbellek, f"{h}.json")
    if os.path.exists(yol):
        with open(yol) as f:
            return json.load(f)

    t = io.BytesIO()
    Image.fromarray(tuval).save(t, format="PNG")
    govde = {"image": {"type": "base64",
                       "base64": base64.b64encode(t.getvalue()).decode(),
                       "format": "png"}}
    son = None
    for i in range(deneme):
        try:
            r = requests.post(UC, headers={"Authorization": f"Bearer {gizli}"},
                              json=govde, timeout=120)
            r.raise_for_status()
            kp = {k["label"]: [k["x"], k["y"]] for k in r.json()["keypoints"]}
            os.makedirs(onbellek, exist_ok=True)
            with open(yol, "w") as f:
                json.dump(kp, f)
            return kp
        except requests.RequestException as err:
            son = err
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"etiketleme basarisiz: {son}")


# ---------------------------------------------------------------------------
# Artirma — hicbiri yeni API cagrisi gerektirmiyor
# ---------------------------------------------------------------------------

def _es(l: str) -> str:
    if l.startswith("RIGHT "):
        return "LEFT " + l[6:]
    if l.startswith("LEFT "):
        return "RIGHT " + l[5:]
    return l


def aynala(tuval: np.ndarray, kp: dict) -> tuple[np.ndarray, dict]:
    """Yatay ayna: x -> 1-x ve sol/sag etiket takasi.

    PixelLab'in aynalanmis goruntude etiketleri DOGRU takas ettigi olculdu
    (fark 0.0073), yani bu donusum etiketi gecerli tutuyor."""
    return tuval[:, ::-1].copy(), {l: [1.0 - kp[_es(l)][0], kp[_es(l)][1]] for l in kp}


def ton_kaydir(tuval: np.ndarray, kayma: float, rng: np.random.Generator
               ) -> np.ndarray:
    """Renk tonunu dondurur; geometri degismedigi icin etiket aynen gecerli."""
    opak = tuval[:, :, 3] > 0
    hsv = np.array(Image.fromarray(tuval[:, :, :3]).convert("HSV"), dtype=np.int16)
    hsv[:, :, 0] = (hsv[:, :, 0] + int(kayma * 255)) % 256
    yeni = tuval.copy()
    yeni[:, :, :3] = np.array(
        Image.fromarray(hsv.astype(np.uint8), mode="HSV").convert("RGB"))
    yeni[~opak] = 0
    return yeni


def olcekle(tuval: np.ndarray, kp: dict, oran: float, dx: int, dy: int
            ) -> tuple[np.ndarray, dict] | None:
    """Tuval icinde olcekleyip kaydirir; eklemler ayni donusumle tasinir."""
    b = tuval.shape[0]
    yb = max(8, int(round(b * oran)))
    kucuk = np.array(Image.fromarray(tuval).resize((yb, yb), Image.NEAREST))
    y0, x0 = (b - yb) // 2 + dy, (b - yb) // 2 + dx
    if not (0 <= y0 and y0 + yb <= b and 0 <= x0 and x0 + yb <= b):
        return None
    yeni = np.zeros_like(tuval)
    yeni[y0:y0 + yb, x0:x0 + yb] = kucuk
    return yeni, {l: [(v[0] * yb + x0) / b, (v[1] * yb + y0) / b] for l, v in kp.items()}


# ---------------------------------------------------------------------------
# Toplama
# ---------------------------------------------------------------------------

def kaynak_kareler(kok: str) -> list[tuple[str, np.ndarray]]:
    """characters/ altindaki her klibin her karesi."""
    cikti = []
    for ad in sorted(d for d in os.listdir(kok)
                     if os.path.isdir(os.path.join(kok, d))):
        meta_yolu = os.path.join(kok, ad, "meta.json")
        if not os.path.exists(meta_yolu):
            continue
        with open(meta_yolu) as f:
            meta = json.load(f)
        for klip in ("idle", "walk_right"):
            if klip not in meta:
                continue
            k = meta[klip]["frameSize"]
            sh = np.array(Image.open(os.path.join(kok, ad, meta[klip]["file"]))
                          .convert("RGBA"))
            for i in range(meta[klip]["frameCount"]):
                kare = sh[:, i * k:(i + 1) * k]
                if (kare[:, :, 3] > 0).any():
                    cikti.append((f"{ad}/{klip}/{i}", kare))
    return cikti


def topla(kaynak: str, cikti: str, gizli: str, limit: int | None,
          artirma: int, tuval_boyut: int, tohum: int = 0) -> dict:
    gorseller = os.path.join(cikti, "gorseller")
    onbellek = os.path.join(cikti, "onbellek")
    os.makedirs(gorseller, exist_ok=True)
    os.makedirs(onbellek, exist_ok=True)
    rng = np.random.default_rng(tohum)

    kareler = kaynak_kareler(kaynak)
    if limit:
        kareler = kareler[:limit]

    satirlar, yeni_cagri = [], 0
    for etiket, kare in kareler:
        tuval, _, _, _ = kanvasa_yerlestir(kare, tuval_boyut)
        h = _hash(tuval)
        onbellekte = os.path.exists(os.path.join(onbellek, f"{h}.json"))
        kp = etiketle(tuval, gizli, onbellek)
        yeni_cagri += 0 if onbellekte else 1

        ornekler = [("ham", tuval, kp)]
        a_tuval, a_kp = aynala(tuval, kp)
        ornekler.append(("ayna", a_tuval, a_kp))
        for j in range(artirma):
            temel_ad, temel_t, temel_k = ornekler[j % 2]
            t = ton_kaydir(temel_t, float(rng.uniform(0, 1)), rng)
            sonuc = olcekle(t, temel_k, float(rng.uniform(0.7, 1.0)),
                            int(rng.integers(-8, 9)), int(rng.integers(-8, 9)))
            if sonuc:
                ornekler.append((f"{temel_ad}+art{j}", sonuc[0], sonuc[1]))

        for ad, t, k in ornekler:
            dosya = f"{_hash(t)}.png"
            Image.fromarray(t).save(os.path.join(gorseller, dosya))
            satirlar.append({"gorsel": f"gorseller/{dosya}", "kaynak": etiket,
                             "artirma": ad, "keypoints": k})

    with open(os.path.join(cikti, "etiketler.jsonl"), "w") as f:
        for s in satirlar:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    return {"kaynak_kare": len(kareler), "ornek": len(satirlar),
            "yeni_cagri": yeni_cagri}


def main(argv=None):
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = argparse.ArgumentParser(
        description="Pixel art poz modeli icin PixelLab ile etiketli veri toplar.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Ornek:\n  python3 tools/pose_dataset.py characters -o _data/poz")
    p.add_argument("kaynak", nargs="?", default=os.path.join(kok, "characters"),
                   help="characters/ klasoru")
    p.add_argument("-o", "--output", default=os.path.join(kok, "_data", "poz"),
                   help="Cikti klasoru")
    p.add_argument("--limit", type=int, default=None,
                   help="En fazla kac KAYNAK kare etiketlensin (maliyet siniri)")
    p.add_argument("--augment", type=int, default=4,
                   help="Kaynak kare basina ek artirma sayisi (varsayilan 4)")
    p.add_argument("--canvas", type=int, default=128, choices=(16, 32, 64, 128, 256),
                   help="Tuval boyutu (PixelLab'in destekledigi olculer)")
    p.add_argument("--dry-run", action="store_true",
                   help="Cagri yapmadan kac YENI etiket gerekecegini soyler")
    args = p.parse_args(argv)

    gizli = anahtar_oku(kok)
    kareler = kaynak_kareler(args.kaynak)
    if args.limit:
        kareler = kareler[:args.limit]

    onbellek = os.path.join(args.output, "onbellek")
    yeni = 0
    for _, kare in kareler:
        t, _, _, _ = kanvasa_yerlestir(kare, args.canvas)
        if not os.path.exists(os.path.join(onbellek, f"{_hash(t)}.json")):
            yeni += 1

    kalan, toplam = bakiye(gizli)
    print(f"Kaynak kare: {len(kareler)}   onbellekte olmayan: {yeni}")
    print(f"Tahmini maliyet: {yeni * CAGRI_BASI:.1f} generation "
          f"(bakiye {kalan:.1f}/{toplam:.0f})")
    if yeni * CAGRI_BASI > kalan:
        print("HATA: bakiye yetmiyor. --limit ile azaltin.", file=sys.stderr)
        return 1
    if args.dry_run:
        return 0

    sonuc = topla(args.kaynak, args.output, gizli, args.limit,
                  args.augment, args.canvas)
    kalan2, _ = bakiye(gizli)
    print(f"\n{sonuc['ornek']} ornek yazildi ({sonuc['kaynak_kare']} kaynak kareden)")
    print(f"Yeni API cagrisi: {sonuc['yeni_cagri']}   "
          f"bakiye {kalan:.1f} -> {kalan2:.1f}")
    print(f"Cikti: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
