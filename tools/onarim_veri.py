#!/usr/bin/env python3
"""
onarim_veri.py — (bozuk kukla -> temiz kare) egitim ciftleri uretir.

    python3 tools/onarim_veri.py -i _data/blender_walk_px -o _data/onarim_walk \
        --onizleme 12

PROBLEM NEDEN BOYLE KURULUYOR

    Olculdu: SD 1.5 + ControlNet + IP-Adapter hattinda kimlik tutmuyor —
    en iyi ayarda (denoise 0.25) paletin ancak %50'si kaynakla ortak, ve
    uretilen kare KUKLANIN KENDISINDEN daha kotu duruyor. Sebep mimari:
    SD 512'de uretiyor, biz 86'ya indiriyoruz ve kimlik o inişte oluyor.
    PixelLab ayni isi 16-64 px'te, native cozunurlukte yapiyor (kendi
    semalarindaki uyari: "16x16, 32x32 ve 64x64 disindaki boyutlar uretimi
    dusuk kaliteli yapabilir").

    Bu yuzden hedef degisti: "karakteri ciz" degil, "BU KABA KAREYI TEMIZE
    CEK". Girdi cevabin buyuk kismini zaten tasiyor — poz dogru, palet
    dogru, kimlik dogru. Eksik olan yalnizca temiz cizim: dondurme
    kirintilari, uzuv diplerindeki dikisler, delik dolgusunun bulasigi.

    Cok daha kolay bir ogrenme problemi ve NATIVE cozunurlukte calisiyor.

VERI NEREDEN

    Blender birincil kaynak, cunku iskelet TAHMIN DEGIL: 3B kemiklerden
    turetiliyor. Kuklanin pozu hedefle birebir tutuyor. Poz modelinin
    ~3px hatasiyla etiketlenmis bir cift, modele "pozu da degistir" diye
    ogretirdi — istedigimiz sey bu degil.

HIZALAMA SART
    Her kare tuvale AYRI yerlestirildi, yani ayni animasyonun iki karesinde
    karakter tuvalde farkli yerde oturuyor. Kukla 0. karenin tuvalinde
    kuruluyor; hedef, iskeleti kuklanin iskeletine oturacak sekilde
    otelenmeden esleşmez.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import iskelet_rig as ir  # noqa: E402
import rig_pose as rp     # noqa: E402


def _kaynak_coz(kaynak: str) -> tuple[str, int]:
    """'blender/walk_south_00012' -> ('walk_south', 12)"""
    son = kaynak.rsplit("/", 1)[-1]
    kok, _, no = son.rpartition("_")
    return kok, int(no)


def _otele(rgba: np.ndarray, dx: int, dy: int) -> np.ndarray:
    out = np.zeros_like(rgba)
    h, w = rgba.shape[:2]
    ky0, ky1 = max(0, -dy), min(h, h - dy)
    kx0, kx1 = max(0, -dx), min(w, w - dx)
    if ky1 <= ky0 or kx1 <= kx0:
        return out
    out[ky0 + dy:ky1 + dy, kx0 + dx:kx1 + dx] = rgba[ky0:ky1, kx0:kx1]
    return out


def ciftler(kok: str, yakin: str = "RIGHT"):
    """Her (animasyon, yon) grubu icin 0. kareden rig kurup digerlerini uretir."""
    satirlar = [json.loads(l) for l in open(os.path.join(kok, "etiketler.jsonl"))
                if json.loads(l)["artirma"] == "ham"]
    gruplar: dict[str, list] = collections.defaultdict(list)
    for r in satirlar:
        g, i = _kaynak_coz(r["kaynak"])
        gruplar[g].append((i, r))

    for g, uyeler in sorted(gruplar.items()):
        uyeler.sort()
        # TABAN KARE: bacaklarin EN ACIK oldugu kare, 0. kare degil.
        #
        # 0. karede karakter genelde ayakta duruyor ve iki bacak ayni x'te.
        # O duruşta iki bacak kemigi ust uste biniyor, en-yakin-kemik
        # atamasi bacaklari rastgele SERITLERE boluyor ve iki serit ters
        # yonlere donunce bacak lime lime oluyor. rig_pose.py'nin kendi
        # belgesi de bunu soyluyor: "rig taban pozunu bacaklar yatayda ACIK
        # olarak urettiriyoruz".
        #
        # Ayrik piksel olmadan kesmek mumkun degil; en acik kare o ayrikligi
        # veren tek karedir.
        def _aciklik(r):
            kp = r["keypoints"]
            return abs(kp["LEFT LEG"][0] - kp["RIGHT LEG"][0])
        taban = max((r for _, r in uyeler), key=_aciklik)
        taban_i = next(i for i, r in uyeler if r is taban)
        t_im = np.array(Image.open(os.path.join(kok, taban["gorsel"])).convert("RGBA"))
        b = max(t_im.shape[:2])
        t_kp = {l: (v[0] * b, v[1] * b) for l, v in taban["keypoints"].items()}
        try:
            rig = ir.rig_uret(t_im, t_kp, yakin)
        except SystemExit:
            continue

        for i, r in uyeler:
            if i == taban_i:
                continue
            h_im = np.array(Image.open(os.path.join(kok, r["gorsel"])).convert("RGBA"))
            h_kp = {l: (v[0] * b, v[1] * b) for l, v in r["keypoints"].items()}
            poz = ir.poz_cevir(rig, t_kp, h_kp)
            kukla = np.array(rp.poz_uret(t_im, json.loads(json.dumps(rig)), poz))
            # poz_uret tuvali her yandan `pay` buyutuyor; hedefi ayni tuvale tasi
            pay = (kukla.shape[1] - h_im.shape[1]) // 2
            hedef = np.zeros_like(kukla)
            hedef[pay:pay + h_im.shape[0], pay:pay + h_im.shape[1]] = h_im
            # Iskelet hizalamasi: kuklanin NECK'i hedefinkine otursun
            dx = int(round(t_kp["NECK"][0] + poz["parcalar"]["govde"]["dx"]
                           - h_kp["NECK"][0]))
            dy = int(round(t_kp["NECK"][1] + poz["parcalar"]["govde"]["dy"]
                           - h_kp["NECK"][1]))
            yield g, i, kukla, _otele(hedef, dx, dy)


def main(argv=None):
    p = argparse.ArgumentParser(description="(kukla -> temiz kare) ciftleri uretir.")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--yakin", choices=("RIGHT", "LEFT"), default="RIGHT")
    p.add_argument("--onizleme", type=int, default=0,
                   help="Ilk N cifti yan yana diz ve cik (egitim verisi yazma).")
    args = p.parse_args(argv)

    if args.onizleme:
        satir = []
        for j, (g, i, kukla, hedef) in enumerate(ciftler(args.input, args.yakin)):
            if j >= args.onizleme:
                break
            satir.append((g, i, kukla, hedef))
        if not satir:
            raise SystemExit("HATA: cift uretilemedi.")
        Z, H = 2, satir[0][2].shape[0]
        sf = Image.new("RGB", (len(satir) * satir[0][2].shape[1] * Z, H * 2 * Z),
                       (20, 22, 26))
        for k, (g, i, ku, he) in enumerate(satir):
            for sira, a in ((0, ku), (1, he)):
                im = Image.new("RGB", (a.shape[1], a.shape[0]), (250, 250, 250))
                im.paste(Image.fromarray(a).convert("RGB"), (0, 0),
                         Image.fromarray(a).split()[3])
                sf.paste(im.resize((a.shape[1] * Z, a.shape[0] * Z), Image.NEAREST),
                         (k * a.shape[1] * Z, sira * H * Z))
        yol = os.path.join(args.output if args.output.endswith(".png")
                           else args.output + ".png")
        os.makedirs(os.path.dirname(yol) or ".", exist_ok=True)
        sf.save(yol)
        print(f"{len(satir)} cift -> {yol}  (ust sira kukla, alt sira hedef)")
        return 0

    gor = os.path.join(args.output, "gorseller")
    os.makedirs(gor, exist_ok=True)
    n = 0
    with open(os.path.join(args.output, "ciftler.jsonl"), "w", buffering=1) as f:
        for g, i, kukla, hedef in ciftler(args.input, args.yakin):
            ad = f"{g}_{i:05d}"
            Image.fromarray(kukla).save(os.path.join(gor, f"{ad}_kukla.png"))
            Image.fromarray(hedef).save(os.path.join(gor, f"{ad}_hedef.png"))
            f.write(json.dumps({"ad": ad, "grup": g,
                                "kukla": f"gorseller/{ad}_kukla.png",
                                "hedef": f"gorseller/{ad}_hedef.png"}) + "\n")
            n += 1
            if n % 50 == 0:
                print(f"  {n} cift", flush=True)
    print(f"{n} cift -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
