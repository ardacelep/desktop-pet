#!/usr/bin/env python3
"""
poz_referans.py — Gemini'ye verilecek ISKELET POZ REFERANS SHEET'ini uretir.

    python3 tools/poz_referans.py characters/ael/walk_right_spritesheet.png \
        --klip walk_right --kare 4 -o _cikti/ael_poz.png

NEDEN ISKELET, NEDEN GORSEL

    Olculdu (rig_pose.py): Gemini'ye pozu METINLE tarif etmek uc turda da
    basarisiz oldu — iki ayri sheet arasinda alfa IoU %100, yani model hicbir
    seyi degistirmedi. Teshis de cozumu soyluyordu: "metin uzamsal bilgi
    tasimiyor". Eksik olan sey GORSEL poz referansiydi.

    Uzuv KALINLIGI iskelette yok, ama olmasi da gerekmiyor: prompt'ta
    karakterin kendisi referans gorsel olarak veriliyor, kalinlik oradan
    geliyor. Iskeletin tasidigi tek bilgi POZ.

YAKIN/UZAK RENKLE AYRILIYOR

    Cizgiler tek renk olsaydi model hangi kolun onde oldugunu bilemezdi ve
    ortusmeyi/golgelendirmeyi rastgele kurardi. Karakterin izleyiciye YAKIN
    tarafi ile UZAK tarafi ayri renkte; prompt bu kodu aciklıyor.

IZGARA DUZENI ZORUNLU
    PROMPTS.md'de olculdu: 8 kare tek sirada = 8:1 en-boy orani, gorsel
    elimize gelene kadar yeniden sikistiriliyor ve izgara tespiti cokuyor
    (gercek ornek: 5632x704 sheet, 171 700 renk, pixelart_extract "izgara
    bulunamadi" deyip durdu). Kareler bu yuzden R x C dizilyor.

CIKTI HUCRE SIRASI OKUMA SIRASI
    Sol ustten saga, sonra alt satir. `split_sheet --rows R --cols C` ayni
    sirayi bekliyor.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skeleton as sk  # noqa: E402

# Izgara: kare sayisi -> (satir, sutun). PROMPTS.md'deki olculmus tablo.
IZGARA = {4: (2, 2), 6: (2, 3), 8: (2, 4), 9: (3, 3)}

# Karakterin KENDI sagi/solu. Saga bakan bir figuru onden izlerken karakterin
# SAGI izleyiciye yakin gelir.
YAKIN_RENK = (255, 90, 60)     # turuncu-kirmizi: izleyiciye YAKIN uzuvlar
UZAK_RENK = (70, 140, 255)     # mavi: UZAK uzuvlar
GOVDE_RENK = (40, 40, 46)      # koyu gri: govde, boyun, kafa
EKLEM_RENK = (255, 255, 255)


def _taraf(a: str, b: str, yakin: str) -> tuple[int, int, int]:
    uzak = "LEFT" if yakin == "RIGHT" else "RIGHT"
    for etiket in (a, b):
        if etiket.startswith(yakin + " ") and not etiket.endswith(("EYE", "EAR")):
            return YAKIN_RENK
        if etiket.startswith(uzak + " ") and not etiket.endswith(("EYE", "EAR")):
            return UZAK_RENK
    return GOVDE_RENK


def kare_ciz(kp: dict, boy: int, yakin: str, kalinlik: int = 3,
             kafa_r: float | None = None) -> Image.Image:
    """Tek bir pozu beyaz zemine cizer. kp PIKSEL koordinatinda."""
    im = Image.new("RGB", (boy, boy), (255, 255, 255))
    d = ImageDraw.Draw(im)
    # KAFA DAIRE OLARAK ciziliyor. Yalnizca burun/goz/kulak noktalari
    # birakilirsa kafa kopuk noktalar olarak goruntlenip figur okunmaz hale
    # geliyor; modelin kafanin NEREDE ve NE BUYUKLUKTE oldugunu gormesi
    # gerekiyor. Yaricap boyun-burun mesafesinden turetiliyor, sabit degil —
    # chibi ve gercekci oranlarda ayni sekilde calissin.
    if "NECK" in kp and "NOSE" in kp:
        nx, ny = kp["NECK"]
        bx, by = kp["NOSE"]
        # Yaricap SILUETTEN olculup disaridan geliyor. Boyun-burun
        # mesafesinden turetmek yanlis cikti: ael'de gercek kafa boyu o
        # mesafenin 3.9 kati (35.9px vs 9.2px) ve tek bir carpanla iki
        # oranda birden tutturmak mumkun degil.
        r = kafa_r if kafa_r else max(math.hypot(bx - nx, by - ny) * 1.15,
                                      kalinlik * 2)
        cx, cy = nx + (bx - nx) * 0.35, ny - r * 0.75
        d.ellipse([cx - r, cy - r, cx + r, cy + r],
                  outline=GOVDE_RENK, width=kalinlik)
        # Yuz yonu: burun tarafina kisa bir cizgi, model karakterin nereye
        # baktigini bilsin.
        d.line([cx, cy, cx + (bx - nx) * 1.6, cy], fill=GOVDE_RENK, width=kalinlik)
    YUZ = {"NOSE", "LEFT EYE", "RIGHT EYE", "LEFT EAR", "RIGHT EAR"}
    for a, b in sk.KEMIKLER:
        if a not in kp or b not in kp or a in YUZ or b in YUZ:
            continue
        d.line([kp[a][0], kp[a][1], kp[b][0], kp[b][1]],
               fill=_taraf(a, b, yakin), width=kalinlik)
    r = max(2, kalinlik)
    for etiket, (x, y) in kp.items():
        if etiket in ("NOSE", "LEFT EYE", "RIGHT EYE", "LEFT EAR", "RIGHT EAR"):
            continue          # kafa dairesi bunlarin yerini tutuyor
        d.ellipse([x - r, y - r, x + r, y + r], fill=EKLEM_RENK,
                  outline=(30, 30, 34))
    return im


def sheet_yap(pozlar: list[dict], boy: int, yakin: str,
              hucre: int = 512, pay: int = 24,
              kafa_orani: float | None = None) -> Image.Image:
    """Pozlari izgaraya dizer. Hucreler arasi BOS SERIT birakiliyor."""
    n = len(pozlar)
    satir, sutun = IZGARA.get(n, (2, math.ceil(n / 2)))
    sf = Image.new("RGB", (sutun * hucre, satir * hucre), (255, 255, 255))
    olcek = (hucre - 2 * pay) / boy
    for i, kp in enumerate(pozlar):
        r, c = divmod(i, sutun)
        k = kare_ciz({l: (x * olcek, y * olcek) for l, (x, y) in kp.items()},
                     hucre - 2 * pay, yakin, kalinlik=max(3, hucre // 140),
                     kafa_r=(kafa_orani * olcek) if kafa_orani else None)
        sf.paste(k, (c * hucre + pay, r * hucre + pay))
    # Hucre cercevesi ve kare numarasi BILEREK YOK. PROMPTS.md'de olculdu:
    # Gemini yapisal ogeleri ciktiya kopyaliyor, ve cerceve/numara opak
    # piksel olarak kareye yapisip split_sheet'in bolmesini bozuyor.
    # Izgarayi bosluk anlatiyor.
    return sf


def main(argv=None):
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = argparse.ArgumentParser(description="Gemini icin iskelet poz referansi uretir.")
    p.add_argument("sprite")
    p.add_argument("--sablon", default=os.path.join(kok, "_data", "sablonlar.json"))
    p.add_argument("--klip", default="walk_right")
    p.add_argument("--kare", type=int, default=4, help="Poz sayisi (4/6/8/9)")
    p.add_argument("--frame", type=int, default=0, help="Dinlenme pozu icin sprite karesi")
    p.add_argument("--yakin", choices=("RIGHT", "LEFT"), default="RIGHT")
    p.add_argument("--hucre", type=int, default=512)
    p.add_argument("--model", default=None)
    p.add_argument("-o", "--out", required=True)
    args = p.parse_args(argv)

    import skeleton_edit as se
    import poz_sablonu as ps

    rgba = sk.kareyi_al(args.sprite, args.frame, None)
    tahminci = se.Tahminci(args.model or se.en_guncel_model(kok))
    isk = tahminci(rgba, "east" if args.klip.endswith("_right") else "south")
    print(f"dinlenme pozu: {tahminci.ad}")
    b = max(rgba.shape[:2])
    dinlenme = {l: (x / b, y / b) for l, (x, y) in isk.noktalar.items()}

    with open(args.sablon) as f:
        sablon = json.load(f)[args.klip]
    toplam = sablon["kare_sayisi"]
    # Istenen kare sayisi sablondan AZSA esit araliklarla seyreltiliyor;
    # ardisik ilk N kareyi almak dongunun yalnizca bir yarisini verirdi.
    indeks = [round(i * toplam / args.kare) % toplam for i in range(args.kare)]
    pozlar = [ps.uygula(sablon, dinlenme, i) for i in indeks]

    # Kafa yaricapi: siluetin tepesi ile NECK arasi, YARISI. Normalize.
    opak = rgba[:, :, 3] > 0
    ys, _ = np.where(opak)
    kafa_orani = ((isk.noktalar["NECK"][1] - float(ys.min())) / 2.0 / b
                  if ys.size else None)
    print(f"kafa yaricapi: {kafa_orani*b:.1f}px (siluetten)" if kafa_orani else "")
    sf = sheet_yap(pozlar, 1.0, args.yakin, args.hucre, kafa_orani)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    sf.save(args.out)
    satir, sutun = IZGARA.get(args.kare, (2, math.ceil(args.kare / 2)))
    print(f"{args.kare} poz ({sablon['kare_sayisi']} kareli dongudan {indeks}) "
          f"-> {satir}x{sutun} izgara, {sf.width}x{sf.height}")
    print(f"cikti: {args.out}")
    print(f"\nGemini ciktisini ayirmak icin:")
    print(f"  python3 tools/split_sheet.py <cikti.png> --rows {satir} --cols {sutun}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
