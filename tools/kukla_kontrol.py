#!/usr/bin/env python3
"""
kukla_kontrol.py — kukla karelerini ControlNet kontrol goruntusune cevirir.

    python3 tools/kukla_kontrol.py _cikti/ael --tip lineart -o _cikti/ael/kontrol

NEDEN ISKELET DEGIL SILUET

    Kontrol sinyali olarak dogrudan OpenPose iskeleti vermek OLCULDU ve
    karakteri bozuyor: iskelet yalnizca eklem noktalarini tasiyor, aradaki eti
    difuzyon modeli kendi bildigi gibi dolduruyor ve chibi oranini insan
    oranina cekiyor. Siluet vermek oranlari koruyor — olculdu, kaynak oran
    0.305, uretilen 0.309, %1.3 sapma (ControlNet lineart, SD 1.5).

    Bu yuzden hat "iskelet -> ControlNet" degil,
    "iskelet -> kukla -> SILUET -> ControlNet" seklinde.

NEDEN HAZIR ON ISLEMCI KULLANMIYORUZ

    `comfyui_controlnet_aux` icindeki lineart/scribble on islemcileri sinir
    agi ve FOTOGRAFTAN cizgi cikarmak icin egitilmis. Bizim kuklamiz zaten
    temiz, alfa kanali kesin bir vektor gibi — kenari dogrudan alfadan
    okumak hem daha dogru hem bedava. On islemci burada bilgi eklemez,
    yalnizca gurultu ekler.

ANTI-ALIASING YOK

    Cizgi tek piksel ve keskin. Yumusatmak ControlNet'e "burasi belirsiz"
    demek olurdu; oysa siluetin siniri tam olarak bildigimiz tek sey.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rig_pose as rp    # noqa: E402
import skeleton as sk    # noqa: E402


def _kenar(opak: np.ndarray) -> np.ndarray:
    """Siluetin DIS hatti: opak olup en az bir saydam komsusu olan piksel."""
    kom = np.ones_like(opak)
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        kom &= np.roll(np.roll(opak, dy, 0), dx, 1)
    # Tuval kenarina degen pikseller de sinir sayilir
    kom[0, :] = kom[-1, :] = kom[:, 0] = kom[:, -1] = False
    return opak & ~kom


def _ic_kenar(rgba: np.ndarray, esik: int = 60) -> np.ndarray:
    """Karakterin ICINDEKI belirgin renk siniralari (kol/govde ayrimi gibi).

    Yalnizca dis hat verilirse model govdeyi duz bir kutle sanip uzuvlari
    kaynastiriyor. Esik 60: pixel art'ta golge tonlari arasindaki fark
    genelde bunun altinda, ayri giysi/ten parcalari arasindaki fark ustunde."""
    opak = rgba[:, :, 3] > 0
    r = rgba[:, :, :3].astype(np.int16)
    fark = np.zeros(opak.shape, bool)
    for dy, dx in ((1, 0), (0, 1)):
        d = np.abs(r - np.roll(np.roll(r, dy, 0), dx, 1)).sum(axis=2)
        fark |= (d > esik) & opak & np.roll(np.roll(opak, dy, 0), dx, 1)
    return fark


def _iskelet_cizgisi(sekil: tuple[int, int], kp: dict, kalinlik: int = 1) -> np.ndarray:
    """Eklem noktalarini kemiklerle birlestirip cizgi maskesi uretir.

    KIYAS ICIN var, hattin parcasi degil. PixelLab pozu ham eklem noktasi
    olarak tasiyabiliyor cunku KENDI modeli pixel art'la egitilmis ve
    eklemler arasina ne koyacagini biliyor. SD 1.5 bilmiyor — bu kip o farki
    ayni kosumda olcmek icin."""
    h, w = sekil
    m = np.zeros((h, w), bool)
    ys, xs = np.mgrid[0:h, 0:w]
    for a, b in sk.KEMIKLER:
        if a not in kp or b not in kp:
            continue
        d = rp.nokta_kemik_uzakligi(xs.astype(float).ravel(), ys.astype(float).ravel(),
                                    kp[a], kp[b]).reshape(h, w)
        m |= d <= kalinlik
    return m


def kontrol_goruntusu(rgba: np.ndarray, tip: str = "lineart",
                      buyut: int = 1, kp: dict | None = None) -> Image.Image:
    """Kuklayi ControlNet girdisine cevirir.

    lineart  — BEYAZ zemin, SIYAH cizgi. ControlNet lineart modeli boyle
               egitildi; ters verirsek model cizgiyi arka plan sanar.
    scribble — SIYAH zemin, BEYAZ cizgi (scribble modelinin bekledigi yon).
    siluet   — dolu maske; en katı kontrol, uzuv ici detay birakmaz.
    iskelet  — yalnizca kemik cizgileri (KIYAS kipi, bkz. _iskelet_cizgisi).
    """
    opak = rgba[:, :, 3] > 0
    if tip == "siluet":
        cizgi = opak
    elif tip == "iskelet":
        if kp is None:
            raise SystemExit("HATA: iskelet kipi keypoint istiyor.")
        cizgi = _iskelet_cizgisi(rgba.shape[:2], kp)
    else:
        cizgi = _kenar(opak) | _ic_kenar(rgba)

    if tip == "scribble":
        im = np.where(cizgi[:, :, None], 255, 0).astype(np.uint8).repeat(3, axis=2)
    else:
        im = np.where(cizgi[:, :, None], 0, 255).astype(np.uint8).repeat(3, axis=2)

    out = Image.fromarray(im)
    if buyut > 1:
        # NEAREST: cizgi keskin kalsin. Difuzyon 512 civarinda calisiyor,
        # 111 piksellik bir kontrol goruntusu orada erirdi.
        out = out.resize((out.width * buyut, out.height * buyut), Image.NEAREST)
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="Kukla karelerini ControlNet girdisine cevirir.")
    p.add_argument("girdi", help="rig.json + poz.json tasiyan klasor, ya da PNG klasoru")
    p.add_argument("--sprite", default=None,
                   help="Kaynak sprite. Verilirse kukla kareleri burada uretilir.")
    p.add_argument("--frame", type=int, default=0)
    p.add_argument("--sablon", default="_data/sablonlar.json")
    p.add_argument("--klip", default="walk_right")
    p.add_argument("--tip", choices=("lineart", "scribble", "siluet", "iskelet"),
                   default="lineart")
    p.add_argument("--buyut", type=int, default=4)
    p.add_argument("-o", "--out", required=True)
    args = p.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    kareler: list[np.ndarray] = []
    kp_listesi: list[dict | None] = []
    rig_yolu = os.path.join(args.girdi, "rig.json")
    if args.sprite and os.path.exists(rig_yolu):
        rgba = sk.kareyi_al(args.sprite, args.frame, None)
        with open(rig_yolu) as f:
            rig = json.load(f)
        with open(os.path.join(args.girdi, "poz.json")) as f:
            pozlar = json.load(f)
        import iskelet_rig as ir
        import poz_sablonu as ps
        import skeleton_edit as se
        b = max(rgba.shape[:2])
        isk = se.Tahminci(se.en_guncel_model(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))(rgba, "east")
        dinlenme = {l: (x / b, y / b) for l, (x, y) in isk.noktalar.items()}
        sab = None
        if os.path.exists(args.sablon or ""):
            with open(args.sablon) as f:
                sab = json.load(f)[args.klip]
        for i, poz in enumerate(pozlar):
            # poz_uret rig'i yerinde degistiriyor (_dinlenme yaziyor), her
            # karede taze kopya veriliyor.
            k = rp.poz_uret(rgba, json.loads(json.dumps(rig)), poz)
            kareler.append(np.array(k))
            # Kukla tuvali `pay` kadar her yandan buyuk; keypoint'ler o kaymayi
            # almali yoksa iskelet cizimi kuklayla ortusmez.
            pay = (k.size[0] - rgba.shape[1]) // 2
            if sab:
                hp = ps.uygula(sab, dinlenme, i)
                kp_listesi.append({l: (x * b + pay, y * b + pay) for l, (x, y) in hp.items()})
            else:
                kp_listesi.append(None)
    else:
        for yol in sorted(glob.glob(os.path.join(args.girdi, "*.png"))):
            kareler.append(np.array(Image.open(yol).convert("RGBA")))
            kp_listesi.append(None)
    if not kareler:
        raise SystemExit(f"HATA: {args.girdi} icinde kare bulunamadi.")

    for i, k in enumerate(kareler):
        g = kontrol_goruntusu(k, args.tip, args.buyut, kp_listesi[i])
        g.save(os.path.join(args.out, f"kontrol_{i:02d}.png"))
        Image.fromarray(k).save(os.path.join(args.out, f"kukla_{i:02d}.png"))
    print(f"{len(kareler)} kare -> {args.out}  "
          f"({args.tip}, {kareler[0].shape[1] * args.buyut}px)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
