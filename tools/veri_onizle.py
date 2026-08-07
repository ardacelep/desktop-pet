#!/usr/bin/env python3
"""
veri_onizle.py — bir egitim veri setini iskeletleriyle birlikte goze getirir.

    python3 tools/veri_onizle.py _data/chen_px_tam --sort iou -n 36
    python3 tools/veri_onizle.py _data/karisik --filter uretim/z --rastgele
    python3 tools/veri_onizle.py _data/chen_px_tam --izle

NEDEN VAR

    Kapilar sayiyla eliyor, ama esigin DOGRU YERDE olup olmadigini sayi
    soylemez. Onu ancak kilpayi gecen ornege bakarak anlarsin: `--sort iou`
    en dusuk skorla KABUL EDILMIS ornekleri one alir. Oradaki karakterler
    saglamsa esik cok sikidir, bozuksa cok gevsek. Rastgele orneklere bakmak
    bu soruyu cevaplamaz — ortalama ornek zaten iyi gorunur.

    Ikinci isi ilerleme takibi: `--izle` ile ayni sayfayi belirli araliklarla
    yeniden uretir, boylece uzun bir donusum kosarken ara sonuca bakilabilir
    (etiketler aninda yazildigi icin yarim veri seti de okunabilir).

VERI BICIMI
    <dizin>/etiketler.jsonl   her satir {gorsel, kaynak, keypoints, olcum?}
    <dizin>/gorseller/*.png   0-1 araligindaki keypoint'ler bu tuvale gore
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skeleton as sk  # noqa: E402

ZEMIN = (20, 22, 26)
KEMIK = (0, 200, 255, 210)
EKLEM = (255, 70, 70, 255)
YAZI = (150, 155, 165)


def satirlari_oku(dizin: str) -> list[dict]:
    """Yarim yazilmis son satiri TOLERE eder — kosu surerken de okunabilsin."""
    yol = os.path.join(dizin, "etiketler.jsonl")
    if not os.path.exists(yol):
        raise SystemExit(f"HATA: {yol} yok.")
    satirlar = []
    with open(yol) as f:
        for ham in f:
            ham = ham.strip()
            if not ham:
                continue
            try:
                satirlar.append(json.loads(ham))
            except json.JSONDecodeError:
                break
    return satirlar


def sec(satirlar: list[dict], sayi: int, sirala: str | None, rastgele: bool,
        suzgec: str | None, tohum: int) -> list[dict]:
    if suzgec:
        satirlar = [s for s in satirlar if suzgec in s.get("kaynak", "")]
    if sirala:
        ters = sirala.startswith("-")
        ad = sirala.lstrip("-")
        var = [s for s in satirlar if ad in s.get("olcum", {})]
        if not var:
            alanlar = sorted({k for s in satirlar for k in s.get("olcum", {})})
            raise SystemExit(f"HATA: '{ad}' olcumu yok. Mevcut: {alanlar or 'hicbiri'}")
        satirlar = sorted(var, key=lambda s: s["olcum"][ad], reverse=ters)
    elif rastgele:
        satirlar = random.Random(tohum).sample(satirlar, min(sayi, len(satirlar)))
    return satirlar[:sayi]


def hucre(dizin: str, s: dict, boy: int, alan: str | None) -> Image.Image:
    rgba = np.array(Image.open(os.path.join(dizin, s["gorsel"])).convert("RGBA"))
    h, w = rgba.shape[:2]
    olcek = max(1, boy // max(h, w))
    im = Image.fromarray(rgba).resize((w * olcek, h * olcek), Image.NEAREST)
    kart = Image.new("RGBA", (boy, boy + 14), ZEMIN + (255,))
    kart.paste(im, ((boy - im.width) // 2, (boy - im.height) // 2), im)

    kp = s["keypoints"]
    d = ImageDraw.Draw(kart)
    dx, dy = (boy - im.width) // 2, (boy - im.height) // 2
    p = lambda a: (kp[a][0] * im.width + dx, kp[a][1] * im.height + dy)
    for a, b in sk.KEMIKLER:
        if a in kp and b in kp:
            d.line([p(a), p(b)], fill=KEMIK, width=max(1, boy // 96))
    r = max(1.5, boy / 64)
    for a in kp:
        x, y = p(a)
        d.ellipse([x - r, y - r, x + r, y + r], fill=EKLEM)

    ad = s.get("kaynak", "?").split("/")[-1][:18]
    if alan and alan.lstrip("-") in s.get("olcum", {}):
        ad += f"  {alan.lstrip('-')}={s['olcum'][alan.lstrip('-')]:.2f}"
    d.text((3, boy + 2), ad, fill=YAZI)
    return kart


def sayfa(dizin: str, secilen: list[dict], sut: int, boy: int,
          alan: str | None) -> Image.Image:
    sat = (len(secilen) + sut - 1) // sut
    sf = Image.new("RGB", (sut * boy, sat * (boy + 14)), ZEMIN)
    for j, s in enumerate(secilen):
        sf.paste(hucre(dizin, s, boy, alan).convert("RGB"),
                 ((j % sut) * boy, (j // sut) * (boy + 14)))
    return sf


def ozet(satirlar: list[dict]) -> str:
    alanlar = sorted({k for s in satirlar for k in s.get("olcum", {})
                      if isinstance(s["olcum"][k], (int, float))})
    parca = []
    for a in alanlar:
        v = [s["olcum"][a] for s in satirlar if a in s.get("olcum", {})]
        parca.append(f"{a} medyan {np.median(v):.2f} en dusuk {min(v):.2f}")
    return " | ".join(parca)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Veri setini iskeletleriyle birlikte sayfa halinde goster.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Ornek:\n"
               "  python3 tools/veri_onizle.py _data/chen_px_tam --sort iou\n"
               "  python3 tools/veri_onizle.py _data/karisik --rastgele -n 36")
    p.add_argument("veri", help="Veri seti dizini (etiketler.jsonl iceren)")
    p.add_argument("-n", "--sayi", type=int, default=24)
    p.add_argument("--sut", type=int, default=6, help="Sutun sayisi")
    p.add_argument("--boy", type=int, default=192, help="Hucre kenari (piksel)")
    p.add_argument("--sort", default=None, metavar="ALAN",
                   help="olcum alanina gore sirala; en DUSUK once. "
                        "Basina - koyarsan en yuksek once (or. --sort iou)")
    p.add_argument("--rastgele", action="store_true")
    p.add_argument("--tohum", type=int, default=0)
    p.add_argument("--filter", default=None, help="kaynak icinde gecen metin")
    p.add_argument("-o", "--out", default=None)
    p.add_argument("--izle", type=int, nargs="?", const=30, default=None,
                   metavar="SANIYE", help="Belirtilen aralikla yeniden uret")
    args = p.parse_args(argv)

    cikti = args.out or os.path.join(args.veri, "onizleme.png")
    while True:
        satirlar = satirlari_oku(args.veri)
        if not satirlar:
            print("Henuz kabul edilmis ornek yok.", flush=True)
        else:
            secilen = sec(satirlar, args.sayi, args.sort, args.rastgele,
                          args.filter, args.tohum)
            sayfa(args.veri, secilen, args.sut, args.boy, args.sort).save(cikti)
            print(f"{len(satirlar)} kabul edilmis ornek | {len(secilen)} gosterildi "
                  f"-> {cikti}", flush=True)
            o = ozet(satirlar)
            if o:
                print(f"  {o}", flush=True)
        if args.izle is None:
            return 0
        time.sleep(args.izle)


if __name__ == "__main__":
    sys.exit(main())
