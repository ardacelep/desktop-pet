#!/usr/bin/env python3
"""
poz_sablonu.py — animasyon poz dizilerini KEMIK ACISI olarak tutar ve
istenen karakterin kendi oranlarina uyarlar.

    python3 tools/poz_sablonu.py cikar -o _data/sablonlar.json
    python3 tools/poz_sablonu.py uygula _data/sablonlar.json walk \
        --sprite characters/ael/walk_right_spritesheet.png --onizleme poz.png

NEDEN ACI, MUTLAK KOORDINAT DEGIL

    Ayni yuruyus dongusunu farkli karakterlere uygulayacagiz ve oranlari
    tutmuyor: olculdu, govde/kafa orani g1'de 3.02, faküs'te 4.53, uretilen
    havuzda 5.38. Mutlak keypoint kopyalamak kisa bacakli bir karaktere uzun
    bacakli birinin adimini giydirir — ayaklar govdenin disina duser.

    Aci + KENDI kemik uzunlugu bu sorunu tumden ortadan kaldiriyor: sablon
    "kalca 25 derece one" der, uzunlugu karakter kendi getirir.

SABLON UYDURULMADI, OLCULDU

    Elimizde PixelLab'in etiketledigi bes karakterin 8'er yuruyus karesi var.
    Kareler faz olarak hizali — ayak acikligi (govde boyuna oranli) kare kare:

        k0     k1     k2     k3     k4     k5     k6     k7
      +0.20  +0.59  +0.77  +0.67  +0.31  +0.07  -0.48  -0.75   (omerhan)
      +0.20  +0.61  +0.79  +0.68  +0.31  -0.01  -0.46  -0.76   (g1)
      +0.25  +0.60  +0.80  +0.66  +0.31  +0.08  -0.46  -0.75   (mag)

    Bes karakterin acilarinin MEDYANI aliniyor. Medyan, cunku faküs belirgin
    sekilde dusuk genlikli (k2'de 0.47, digerleri 0.77-0.80) ve ortalama onu
    tum sablona yayardi.

KOK HAREKETI
    Yuruyusta govde dikeyde inip cikiyor. NECK'in dikey kaymasi da sablona
    giriyor, govde boyuna oranli olarak — yani o da olcek bagisik.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skeleton as sk  # noqa: E402

# Kok NECK. Her kemik (ebeveyn, cocuk); sira onemli — cocuk kendinden onceki
# bir eklemin konumuna dayaniyor.
HIYERARSI = (
    ("NECK", "NOSE"),
    ("NOSE", "RIGHT EYE"), ("NOSE", "LEFT EYE"),
    ("RIGHT EYE", "RIGHT EAR"), ("LEFT EYE", "LEFT EAR"),
    ("NECK", "RIGHT SHOULDER"), ("RIGHT SHOULDER", "RIGHT ELBOW"),
    ("RIGHT ELBOW", "RIGHT ARM"),
    ("NECK", "LEFT SHOULDER"), ("LEFT SHOULDER", "LEFT ELBOW"),
    ("LEFT ELBOW", "LEFT ARM"),
    ("NECK", "RIGHT HIP"), ("RIGHT HIP", "RIGHT KNEE"),
    ("RIGHT KNEE", "RIGHT LEG"),
    ("NECK", "LEFT HIP"), ("LEFT HIP", "LEFT KNEE"),
    ("LEFT KNEE", "LEFT LEG"),
)


def govde_boyu(kp: dict) -> float:
    """NECK'ten ayak bileklerinin ortasina — tum olcekleme bunun uzerinden."""
    ayak_y = (kp["LEFT LEG"][1] + kp["RIGHT LEG"][1]) / 2.0
    return max(abs(ayak_y - kp["NECK"][1]), 1e-6)


# Bu orandan KISA kemikler acisiyla degil, kartezyen kaymasiyla tutuluyor.
# Kisa kemikte aci kotu kosullu: 1-2 piksellik fark aciyi savuruyor. Olculdu,
# kare-ici aci yayilimi (bes karakter):
#     NECK>SHOULDER   oran 0.083  ->  60.7°   <-- kararsiz
#     NOSE>RIGHT EYE  oran 0.142  ->  29.0°
#     NECK>HIP        oran 0.535  ->   7.5°
# Ve zararı yerel kalmiyor: omuz acisi yanlis olunca dirsek ve bilek de
# onunla birlikte kayiyor (olculdu, ael kare 0: omuz 8.3 / dirsek 8.4 /
# bilek 9.1px). Kisa kemikler zaten yapisal kaymalar — govde boyuyla
# olceklemek dogal ve kararli.
KISA_KEMIK_ORANI = 0.15


def acilara_cevir(kp: dict) -> dict:
    """Poza kemik ACILARI ve govde boyuna ORANLI uzunluklar olarak bakar.

    Kisa kemikler icin aci yerine kartezyen kayma tutuluyor (bkz.
    KISA_KEMIK_ORANI)."""
    boy = govde_boyu(kp)
    cikti = {}
    for ebeveyn, cocuk in HIYERARSI:
        dx = kp[cocuk][0] - kp[ebeveyn][0]
        dy = kp[cocuk][1] - kp[ebeveyn][1]
        # dx/dy HER kemik icin tutuluyor; kisa mi uzun mu karari KEMIK BAZINDA
        # ve tum orneklerin medyaniyla veriliyor (asagida). Ornek basina karar
        # vermek sinirdaki bir kemigi bazi karelerde kisa bazilarinda uzun
        # yapiyor ve sablon tutarsiz kaliyor.
        cikti[f"{ebeveyn}>{cocuk}"] = {
            "aci": math.atan2(dy, dx), "oran": math.hypot(dx, dy) / boy,
            "dx": dx / boy, "dy": dy / boy,
        }
    return cikti


def sablon_cikar(kayitlar: list[dict], kare_sayisi: int) -> dict:
    """Ayni animasyonun cok karakterli orneklerinden kanonik sablon uretir."""
    kare_kayit: dict[int, list[dict]] = {i: [] for i in range(kare_sayisi)}
    # Kok hareketi ZEMINE gore olculuyor: basan ayak (iki bilekten ALTTAKI)
    # yerde duruyor, yer oynamiyor.
    #
    # Onceden tuvale gore olculuyordu (NECK.y / boy) ve karakterin kendi
    # kare-ortalamasindan sapmasi aliniyordu. Bu, karakterin tuvalde SABIT bir
    # ofsette oturmasini varsayiyor — ama her kare ayri kirpilip ortalandigi
    # icin sinirlayici kutu kare kare oynuyor. Yani olculen sey salinim degil,
    # KIRPMA TITREMESIYDI. Olculdu, sapmanin yayilimi (govde boyuna oranli):
    #
    #             ael   faküs    g1    mag  omerhan
    #   tuvale   0.334  0.105  0.333  0.310  0.221    <- karakterler tutmuyor
    #   ZEMINE   0.067  0.049  0.067  0.076  0.075    <- bes egri ust uste
    #
    # Govde boyunun %33'u kadar salinim yuruyuste yok; %7 var. Zemine gore
    # olcunce bes karakterin egrisi ortusuyor (k3'te hepsi -0.03/-0.04),
    # tuvale gore olcunce ortusmuyor — dogru olcut bu.
    #
    # Uygulama formulu DEGISMIYOR: her iki durumda da tutulan sey karakterin
    # kendi dinlenme pozundan SAPMASI, degisen yalnizca sapmanin neye gore
    # olculdugu.
    per_kar: dict[str, dict[int, float]] = {}
    for r in kayitlar:
        i = int(r["kaynak"].rsplit("/", 1)[1])
        if i >= kare_sayisi:
            continue
        kp = r["keypoints"]
        kare_kayit[i].append(acilara_cevir(kp))
        ad = r["kaynak"].split("/")[0]
        zemin = max(kp["LEFT LEG"][1], kp["RIGHT LEG"][1])
        per_kar.setdefault(ad, {})[i] = ((kp["NECK"][1] - zemin)
                                         / max(govde_boyu(kp), 1e-6))

    kok: dict[int, list[float]] = {i: [] for i in range(kare_sayisi)}
    for ad, kareler_ in per_kar.items():
        if len(kareler_) < kare_sayisi:
            continue
        ort = float(np.mean(list(kareler_.values())))
        for i, v in kareler_.items():
            kok[i].append(v - ort)
    taban_kok = 0.0

    # Hangi kemik KISA — tum karelerin tum orneklerinden, kemik bazinda.
    hepsi = [k for liste in kare_kayit.values() for k in liste]
    kisa = {ad for ad in hepsi[0]
            if float(np.median([k[ad]["oran"] for k in hepsi])) < KISA_KEMIK_ORANI}
    kareler = []
    for i in range(kare_sayisi):
        if not kare_kayit[i]:
            raise SystemExit(f"HATA: {i}. kare icin ornek yok.")
        kemikler = {}
        for ad in kare_kayit[i][0]:
            # Aci ORTALAMASI dairesel olmali: -179 ile +179 komsudur.
            aci = [k[ad]["aci"] for k in kare_kayit[i]]
            kayit = {
                "aci": float(math.atan2(float(np.median(np.sin(aci))),
                                        float(np.median(np.cos(aci))))),
                "oran": float(np.median([k[ad]["oran"] for k in kare_kayit[i]])),
            }
            if ad in kisa:
                kayit["dx"] = float(np.median([k[ad]["dx"] for k in kare_kayit[i]]))
                kayit["dy"] = float(np.median([k[ad]["dy"] for k in kare_kayit[i]]))
            kemikler[ad] = kayit
        kareler.append({"kemikler": kemikler,
                        "kok_dy": float(np.median(kok[i])) - taban_kok})
    return {"kare_sayisi": kare_sayisi, "kareler": kareler,
            "karakter_sayisi": len({r["kaynak"].split("/")[0] for r in kayitlar})}


def uygula(sablon: dict, dinlenme: dict, kare: int) -> dict:
    """Sablonun `kare` pozunu, karakterin KENDI kemik uzunluklariyla kurar.

    `dinlenme` karakterin dinlenme pozu (0-1 normalize keypoint'ler); ondan
    yalnizca KEMIK UZUNLUKLARI ve NECK'in yatay yeri aliniyor, acilar
    sablondan geliyor."""
    boy = govde_boyu(dinlenme)
    uzunluk = {f"{e}>{c}": math.hypot(dinlenme[c][0] - dinlenme[e][0],
                                      dinlenme[c][1] - dinlenme[e][1])
               for e, c in HIYERARSI}

    k = sablon["kareler"][kare]
    nokta = {"NECK": (dinlenme["NECK"][0],
                      dinlenme["NECK"][1] + k["kok_dy"] * boy)}
    for ebeveyn, cocuk in HIYERARSI:
        ad = f"{ebeveyn}>{cocuk}"
        kemik = k["kemikler"][ad]
        px, py = nokta[ebeveyn]
        if "dx" in kemik:
            # Kisa kemik: aci kararsiz, kaymayi govde boyuyla olcekle
            nokta[cocuk] = (px + kemik["dx"] * boy, py + kemik["dy"] * boy)
        else:
            a, u = kemik["aci"], uzunluk[ad]
            nokta[cocuk] = (px + u * math.cos(a), py + u * math.sin(a))
    return nokta


def veri_oku(kok: str, klip: str) -> list[dict]:
    yol = os.path.join(kok, "_data", "poz", "etiketler.jsonl")
    if not os.path.exists(yol):
        raise SystemExit(f"HATA: {yol} yok.")
    return [r for r in map(json.loads, open(yol))
            if f"/{klip}/" in r["kaynak"] and r.get("artirma") == "ham"]


def main(argv=None):
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = argparse.ArgumentParser(
        description="Animasyon poz sablonlarini cikarir ve karaktere uyarlar.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    alt = p.add_subparsers(dest="komut", required=True)

    c = alt.add_parser("cikar", help="Etiketli karelerden sablon uret")
    c.add_argument("-o", "--out", default=os.path.join(kok, "_data", "sablonlar.json"))

    u = alt.add_parser("uygula", help="Sablonu bir karaktere uyarla")
    u.add_argument("sablon")
    u.add_argument("klip", choices=("walk_right", "idle"))
    u.add_argument("--sprite", required=True, help="Karakterin sprite'i (dinlenme pozu icin)")
    u.add_argument("--frame", type=int, default=0, help="Sprite'in kacinci karesi")
    u.add_argument("--model", default=None,
                   help="Poz modeli checkpoint'i. Dinlenme pozu BURADAN gelmeli.")
    u.add_argument("--sezgisel", action="store_true",
                   help="Dinlenme pozunu skeleton.py'den al. TAVSIYE EDILMEZ: "
                        "olculdu, yandan gorunuste kalcayi 18.6px sasiriyor ve "
                        "NECK>HIP iki bacak zincirinin de koku oldugu icin "
                        "altindaki her sey kayiyor.")
    u.add_argument("--onizleme", default=None)
    args = p.parse_args(argv)

    if args.komut == "cikar":
        sablonlar = {}
        for klip, n in (("walk_right", 8), ("idle", 4)):
            kayit = veri_oku(kok, klip)
            sablonlar[klip] = sablon_cikar(kayit, n)
            print(f"{klip:11s} {n} kare, {sablonlar[klip]['karakter_sayisi']} karakterden "
                  f"({len(kayit)} ornek)")
        with open(args.out, "w") as f:
            json.dump(sablonlar, f, indent=1)
        print(f"-> {args.out}")
        return 0

    with open(args.sablon) as f:
        sablon = json.load(f)[args.klip]
    from PIL import Image
    rgba = sk.kareyi_al(args.sprite, args.frame, None)

    # Dinlenme pozu MODELDEN geliyor. Burasi sablonun tek girdisi: acilar
    # sablondan, uzunluklar dinlenme pozundan. Dinlenme yanlissa uretilen
    # sekiz karenin hepsi ayni sekilde yanlis oluyor — hata dizi boyunca
    # sabit kaliyor, tek karede kalmiyor.
    import skeleton_edit as se
    ckpt = None if args.sezgisel else (args.model or se.en_guncel_model(kok))
    tahminci = se.Tahminci(ckpt)
    yon = "east" if args.klip.endswith("_right") else "south"
    isk = tahminci(rgba, yon)
    print(f"dinlenme pozu: {tahminci.ad}"
          + (f" ({os.path.relpath(ckpt, kok)})" if ckpt and tahminci.ad == "model" else ""))
    b = max(rgba.shape[:2])
    dinlenme = {l: (x / b, y / b) for l, (x, y) in isk.noktalar.items()}

    pozlar = [uygula(sablon, dinlenme, i) for i in range(sablon["kare_sayisi"])]
    print(f"{sablon['kare_sayisi']} poz uretildi ({args.klip})")
    for i, poz in enumerate(pozlar):
        ayak = abs(poz["LEFT LEG"][0] - poz["RIGHT LEG"][0]) * b
        print(f"  kare {i}: ayak acikligi {ayak:5.1f}px")

    if args.onizleme:
        Z = 4
        sf = Image.new("RGB", (rgba.shape[1] * Z * len(pozlar), rgba.shape[0] * Z),
                       (20, 22, 26))
        from PIL import ImageDraw
        for i, poz in enumerate(pozlar):
            kat = Image.fromarray(rgba).resize(
                (rgba.shape[1] * Z, rgba.shape[0] * Z), Image.NEAREST).convert("RGBA")
            d = ImageDraw.Draw(kat)
            for a, bb in sk.KEMIKLER:
                d.line([(poz[a][0] * b * Z, poz[a][1] * b * Z),
                        (poz[bb][0] * b * Z, poz[bb][1] * b * Z)],
                       fill=(0, 220, 255, 255), width=2)
            for a in poz:
                x, y = poz[a][0] * b * Z, poz[a][1] * b * Z
                d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 70, 70, 255))
            sf.paste(kat.convert("RGB"), (i * rgba.shape[1] * Z, 0))
        sf.save(args.onizleme)
        print(f"onizleme -> {args.onizleme}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
