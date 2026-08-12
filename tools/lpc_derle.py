#!/usr/bin/env python3
"""
lpc_derle.py — LPC katmanlarindan karakter uretir ve karelere ayirir.

    python3 tools/lpc_derle.py --sayi 40 --animasyon walk -o _data/lpc_walk

NEDEN BU KAYNAK

    Onarim modeli (kukla -> temiz kare) icin AYNI karakterin COK POZU gerekiyor
    ve elimizde animasyonlu karakter sayisi 7'ydi. LPC bunu aciyor:

        64x64 NATIVE          — 512'de uretip indirgemek olculdu ve kimligi
                                olduruyordu; burada indirgeme adimi hic yok
        9 kare x 4 yon        — her animasyon icin
        15 animasyon          — walk, run, slash, thrust, spellcast, jump...
        8 vucut tipi          — child, teen, male, female, muscular, pregnant,
                                skeleton, zombie: oran cesitliligi VAR
        ORTAK ISKELET         — butun karakterler ayni animasyondan turuyor

    Sonuncusu carpan: iskelet etiketi vucut tipi basina BIR KEZ cikariliyor,
    kiyafet/sac/aksesuar katmanlari serbestce degisirken ayni poz dizisi
    gecerli kaliyor.

LISANS
    Taban govdelerin hicbiri CC0 DEGIL (CC-BY-SA 3.0 / GPL 3.0 / OGA-BY 3.0,
    coklu ve "veya"). Katmanlarin yalnizca %8'i CC0 ve legs/feet'te hic yok.
    `--lisans` ile suzuluyor; kullanilan her katmanin kunyesi cikti klasorune
    KREDILER.csv olarak yaziliyor — atif yukumlulugu boyle karsilaniyor.

KATMAN YOLU KURALI
    variants varsa   <yol><animasyon>/<varyant>.png
    yoksa            <yol><animasyon>.png
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import random
import sys

import numpy as np
from PIL import Image

KOK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "_data", "harici", "lpc")

# LPC sheet'inde satir sirasi. Bizim konvansiyonumuza cevriliyor: LPC'de
# "up" karakterin ARKASINI gosteriyor (kameradan uzaklasiyor) = north.
YON_SIRASI = ("north", "west", "south", "east")

# Karakteri olusturan katmanlar. Secim KATEGORI adiyla degil YOL ONEKIYLE
# yapiliyor, cunku LPC'nin "head" kategorisi kafa DEGIL: jabot, kolye, yuz
# detayi gibi seyler de orada. Yol onekiyle secmezsek karakter kafasiz
# ciziliyor — LPC taban govdesi kafasiz, kafa ayri bir katman.
#
# Sira onemli degil, cizim sirasini zPos belirliyor.
PARCA_ONEK = {
    "body":  ("body/body.json",),           # tek tanim: govde rengi/tipi
    "head":  ("head/heads/",),              # human, elf, goblin, lizard...
    "hair":  ("hair/",),
    "torso": ("torso/clothes/", "torso/shirts/", "torso/armour/"),
    "legs":  ("legs/",),
    "feet":  ("feet/",),
}
# Govde ve kafa zorunlu; digerleri olmayabilir (ciplak karakter de gecerli).
ZORUNLU = ("body", "head")


def tanimlar() -> list[dict]:
    """Tum sheet tanimlarini okur. meta_* dosyalari sema, atlaniyor."""
    out = []
    for y in sorted(glob.glob(os.path.join(KOK, "sheet_definitions", "**", "*.json"),
                              recursive=True)):
        if os.path.basename(y).startswith("meta_"):
            continue
        with open(y) as f:
            d = json.load(f)
        d["_yol"] = os.path.relpath(y, os.path.join(KOK, "sheet_definitions"))
        d["_kategori"] = d["_yol"].split(os.sep)[0]
        d["_onek"] = d["_yol"].replace(os.sep, "/")
        out.append(d)
    return out


def _lisanslar(d: dict) -> set[str]:
    return {L for c in d.get("credits", []) for L in c.get("licenses", [])}


def katman_yollari(d: dict, vucut: str, animasyon: str,
                   varyant: str | None) -> list[tuple[int, str]]:
    """(zPos, dosya yolu) listesi. Bulunamayan katman sessizce atlaniyor —
    her kiyafet her vucut tipinde ve her animasyonda cizilmis degil."""
    out = []
    for k, v in d.items():
        if not k.startswith("layer_") or not isinstance(v, dict):
            continue
        temel = v.get(vucut)
        if not temel:
            continue
        vary = d.get("variants") or []
        if vary:
            se = varyant if varyant in vary else vary[0]
            p = os.path.join(KOK, "spritesheets", temel, animasyon, f"{se}.png")
        else:
            p = os.path.join(KOK, "spritesheets", temel, f"{animasyon}.png")
        if os.path.exists(p):
            out.append((int(v.get("zPos", 0)), p))
    return out


def karakter_uret(secim: list[tuple[dict, str | None]], vucut: str,
                  animasyon: str) -> Image.Image | None:
    """Secilen katmanlari zPos sirasiyla ust uste bindirir."""
    parcalar = []
    for d, varyant in secim:
        parcalar += katman_yollari(d, vucut, animasyon, varyant)
    if not parcalar:
        return None
    parcalar.sort(key=lambda t: t[0])
    taban = None
    for _, p in parcalar:
        im = Image.open(p).convert("RGBA")
        if taban is None:
            taban = Image.new("RGBA", im.size, (0, 0, 0, 0))
        if im.size != taban.size:      # buyuk silahlar farkli tuvalde
            continue
        taban.alpha_composite(im)
    return taban


def karelere_ayir(sheet: Image.Image, kare: int = 64):
    """Sheet'i (yon, kare no) -> 64x64 goruntu sozlugune ayirir."""
    a = np.array(sheet)
    satir, sutun = a.shape[0] // kare, a.shape[1] // kare
    out = {}
    for r in range(min(satir, len(YON_SIRASI))):
        for c in range(sutun):
            p = a[r * kare:(r + 1) * kare, c * kare:(c + 1) * kare]
            if (p[:, :, 3] > 0).sum() < 20:      # bos kare (kisa animasyonlar)
                continue
            out[(YON_SIRASI[r], c)] = p
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="LPC katmanlarindan karakter derler.")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--sayi", type=int, default=20, help="Uretilecek karakter sayisi")
    p.add_argument("--animasyon", default="walk")
    p.add_argument("--vucut", default=None,
                   help="Tek vucut tipi (male/female/child/...). Bos = hepsi.")
    p.add_argument("--lisans", default=None,
                   help="Yalnizca bu lisansi TASIYAN katmanlar (or. CC0, GPL 3.0)")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args(argv)

    if not os.path.isdir(KOK):
        raise SystemExit(f"HATA: LPC deposu yok: {KOK}")
    hepsi = tanimlar()
    if args.lisans:
        hepsi = [d for d in hepsi if args.lisans in _lisanslar(d)]
    kat = {p: [d for d in hepsi if any(d["_onek"].startswith(o) for o in onekler)]
           for p, onekler in PARCA_ONEK.items()}
    eksik = [p for p in ZORUNLU if not kat[p]]
    if eksik:
        raise SystemExit(f"HATA: zorunlu parca yok: {', '.join(eksik)} "
                         f"(lisans suzgeci fazla dar olabilir).")
    govde_tanim = kat["body"][0]
    tipler = ([args.vucut] if args.vucut
              else [x for x in govde_tanim["layer_1"] if x != "zPos"])
    print(f"tanim: {len(hepsi)}  vucut tipi: {', '.join(tipler)}")
    for k in PARCA_ONEK:
        print(f"  {k:7s} {len(kat[k]):4d} secenek")

    rng = random.Random(args.seed)
    gor = os.path.join(args.out, "gorseller")
    os.makedirs(gor, exist_ok=True)
    krediler: dict[str, tuple] = {}
    n = 0
    with open(os.path.join(args.out, "kareler.jsonl"), "w", buffering=1) as f:
        for i in range(args.sayi):
            vucut = tipler[i % len(tipler)]
            secim = [(govde_tanim, None)]
            for k in ("head", "hair", "torso", "legs", "feet"):
                aday = kat[k]
                if not aday:
                    continue
                # Kafa bu vucut tipinde cizilmis olmali; degilse baska kafa
                # dene. Kafasiz karakter uretmek egitim verisini bozar.
                for _ in range(12):
                    d = rng.choice(aday)
                    vary = d.get("variants") or []
                    v = rng.choice(vary) if vary else None
                    if katman_yollari(d, vucut, args.animasyon, v):
                        secim.append((d, v))
                        break
                else:
                    if k in ZORUNLU:
                        secim = None
                        break
            if secim is None:
                continue
            sheet = karakter_uret(secim, vucut, args.animasyon)
            if sheet is None:
                continue
            kareler = karelere_ayir(sheet)
            if not kareler:
                continue
            kimlik = f"lpc{i:04d}_{vucut}"
            for (yon, kare), a in sorted(kareler.items()):
                ad = f"{kimlik}_{yon}_{kare:02d}.png"
                Image.fromarray(a).save(os.path.join(gor, ad))
                f.write(json.dumps({"karakter": kimlik, "vucut": vucut,
                                    "animasyon": args.animasyon, "yon": yon,
                                    "kare": kare, "gorsel": f"gorseller/{ad}"}) + "\n")
                n += 1
            for d, _ in secim:
                for c in d.get("credits", []):
                    krediler[c.get("file", d["_yol"])] = (
                        "; ".join(c.get("authors", [])),
                        "; ".join(c.get("licenses", [])),
                        "; ".join(c.get("urls", [])))
            if (i + 1) % 10 == 0:
                print(f"  {i+1}/{args.sayi} karakter, {n} kare", flush=True)

    with open(os.path.join(args.out, "KREDILER.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dosya", "yazarlar", "lisanslar", "kaynaklar"])
        for k, v in sorted(krediler.items()):
            w.writerow([k, *v])
    print(f"\n{n} kare -> {args.out}   ({len(krediler)} katman kunyesi KREDILER.csv'de)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
