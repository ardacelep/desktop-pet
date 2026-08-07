#!/usr/bin/env python3
"""
pixellab_dondur.py — mevcut ONDEN karakterleri YANDAN hale cevirip etiketler.

    ~/ComfyUI/venv/bin/python tools/pixellab_dondur.py --count 45 \
        -i _data/uretim -o _data/uretim_yan

NEDEN

    Poz modelinin yan gorunusu olculebilir sekilde zayif (dort holdout,
    Chen'li model):
        onden (idle kareler)  1.51px
        YANDAN (walk kareler) 4.06px    — faküs'te 6.97
    Sebep veri: 195 uretilen karakterin TAMAMI onden; yandan denetim yalnizca
    bes gercek karakterin 40 ham karesinden geliyor. Uygulamanin walk_right
    sprite'i yandan oldugu icin bu bosluk dogrudan is goruyor.

NEDEN `rotate`, YENI URETIM DEGIL

    Iki yol olculdu. Olcut omuz genisligi / govde boyu — profilde omuzlar ust
    uste bindigi icin dusuyor. Gercek walk sprite'larimiz 0.148 (0.098-0.225),
    onden taban 0.333:

        create-image-pixflux, direction=east   1.1 gen/ornek   0.21 - 0.30
        rotate (south -> east) + etiketle      1.1 gen/ornek   0.12 - 0.22

    Yani FIYAT AYNI; secim kaliteye dayaniyor. `direction` semada "weakly
    guiding" diye geciyor ve gercekten oyle — tek basina dortte uc gorunusten
    oteye gitmiyor. `rotate` dort denemede 4/4 kabul verdi, omuz orani medyani
    0.132, yani gercek walk sprite'larimizin tam bandinda. Ayrica zaten
    elimizdeki karakterler uzerinde calistigi icin yeni karakter uretmeye
    gerek kalmiyor.

DORTTE UC CIKTILAR ELENMIYOR
    Gercek karakterlerimiz de bir yelpazeye yayiliyor (faküs 0.098 profil,
    ael 0.225 dortte uc). Modelin onden-profil arasini gormesi ise yarar;
    elenen tek sey HIC donmemis olanlar.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import time

import numpy as np
import requests
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pose_dataset as pdset          # noqa: E402
import pixellab_generate as pgen      # noqa: E402

UC = "https://api.pixellab.ai/v2/rotate"
# Olculdu: 4 dondurme + 4 etiketleme bakiyeyi 28.4 -> 24.1 dusurdu (4.3),
# yani dondurme 1.0 generation. Ilk olcumum (iki cagriyi hemen ardindan
# okuyup 0.5 bulmustum) YANLISTI — bakiye ucu gecikmeli guncelleniyor
# olmali. Yani dondurme, yeni karakter uretmekle AYNI fiyata.
DONDURME_BASI = 1.0

# Omuz genisligi / govde boyu. Onden taban 0.333; gercek walk sprite'lari
# 0.098-0.225. 0.28 ustu "donmemis" sayiliyor — dortte uce yer birakiyor ama
# onden kalanlari eliyor.
OMUZ_ESIGI = 0.28


def omuz_orani(kp: dict) -> float:
    boy = abs((kp["LEFT LEG"][1] + kp["RIGHT LEG"][1]) / 2 - kp["NECK"][1])
    return abs(kp["LEFT SHOULDER"][0] - kp["RIGHT SHOULDER"][0]) / max(boy, 1e-6)


def dondur(gizli: str, rgba: np.ndarray, boyut: int, tohum: int,
           deneme: int = 3) -> np.ndarray | None:
    t = io.BytesIO()
    Image.fromarray(rgba).save(t, format="PNG")
    govde = {
        "image_size": {"width": boyut, "height": boyut},
        "from_image": {"type": "base64",
                       "base64": base64.b64encode(t.getvalue()).decode()},
        "from_view": "side", "to_view": "side",
        "from_direction": "south", "to_direction": "east",
        "image_guidance_scale": 3.0, "seed": int(tohum),
    }
    for i in range(deneme):
        try:
            r = requests.post(UC, headers={"Authorization": f"Bearer {gizli}"},
                              json=govde, timeout=600)
            r.raise_for_status()
            b = r.json()["image"]["base64"]
            return np.array(Image.open(io.BytesIO(base64.b64decode(b))).convert("RGBA"))
        except requests.RequestException as err:
            if i == deneme - 1:
                print(f"    dondurme basarisiz: {str(err)[:90]}", file=sys.stderr)
            time.sleep(3 * (i + 1))
    return None


def main(argv=None):
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = argparse.ArgumentParser(
        description="Onden karakterleri yandan hale cevirip etiketler.")
    p.add_argument("-i", "--input", default=os.path.join(kok, "_data", "uretim"))
    p.add_argument("-o", "--output", default=os.path.join(kok, "_data", "uretim_yan"))
    p.add_argument("--count", type=int, default=10)
    p.add_argument("--canvas", type=int, default=128, choices=(64, 128))
    p.add_argument("--augment", type=int, default=6)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    gizli = pdset.anahtar_oku(kok)
    kaynak = [json.loads(l) for l in open(os.path.join(args.input, "etiketler.jsonl"))]
    ham = [r for r in kaynak if r.get("artirma") == "ham"]

    # Kaldigi yerden devam: cikti dosyasindaki kimlikler atlaniyor.
    yol = os.path.join(args.output, "etiketler.jsonl")
    islenmis: set[str] = set()
    if os.path.exists(yol):
        islenmis = {json.loads(l)["kaynak"].split("|")[0]
                    for l in open(yol) if l.strip()}
    kalan = [r for r in ham if r["kaynak"] not in islenmis][:args.count]

    tahmin = len(kalan) * (DONDURME_BASI + pdset.CAGRI_BASI)
    bakiye, toplam = pdset.bakiye(gizli)
    print(f"{len(ham)} onden karakter, {len(islenmis)} zaten islenmis. "
          f"{len(kalan)} dondurulecek -> tahmini {tahmin:.1f} generation "
          f"(bakiye {bakiye:.1f}/{toplam:.0f})")
    if tahmin > bakiye:
        print("HATA: bakiye yetmiyor. --count azaltin.", file=sys.stderr)
        return 1
    if args.dry_run:
        return 0

    gorseller = os.path.join(args.output, "gorseller")
    onbellek = os.path.join(args.output, "onbellek")
    os.makedirs(gorseller, exist_ok=True)
    os.makedirs(onbellek, exist_ok=True)

    rng = np.random.default_rng(args.seed)
    ef = open(yol, "a" if islenmis else "w", buffering=1)   # satir satir: her cagri para
    elenen: dict[str, int] = {}
    oranlar: list[float] = []
    yazilan = 0

    for i, r in enumerate(kalan):
        kaynak_rgba = np.array(Image.open(
            os.path.join(args.input, r["gorsel"])).convert("RGBA"))
        yeni = dondur(gizli, kaynak_rgba, args.canvas, int(rng.integers(1, 2**31)))
        if yeni is None:
            elenen["dondurme"] = elenen.get("dondurme", 0) + 1
            continue
        tamam, sebep = pgen.kabul_edilebilir(yeni)
        if not tamam:
            elenen[sebep] = elenen.get(sebep, 0) + 1
            print(f"  [{i+1}/{len(kalan)}] elendi: {sebep}", flush=True)
            continue

        tuval, _, _, _ = pdset.kanvasa_yerlestir(yeni, args.canvas)
        kp = pdset.etiketle(tuval, gizli, onbellek)
        oran = omuz_orani(kp)
        if oran > OMUZ_ESIGI:
            elenen["donmemis"] = elenen.get("donmemis", 0) + 1
            print(f"  [{i+1}/{len(kalan)}] elendi: donmemis (omuz {oran:.3f})",
                  flush=True)
            continue
        oranlar.append(oran)

        ornekler = [("ham", tuval, kp)]
        # Aynalamak sola bakan karakter veriyor — uygulamada walk_left zaten
        # aynadan uretiliyor, yani bu gecerli veri.
        a_t, a_k = pdset.aynala(tuval, kp)
        ornekler.append(("ayna", a_t, a_k))
        for j in range(args.augment):
            ad, t, k = ornekler[j % 2]
            t2 = pdset.ton_kaydir(t, float(rng.uniform(0, 1)), rng)
            s = pdset.olcekle(t2, k, float(rng.uniform(0.7, 1.0)),
                              int(rng.integers(-8, 9)), int(rng.integers(-8, 9)))
            if s:
                ornekler.append((f"{ad}+art{j}", s[0], s[1]))

        for ad, t, k in ornekler:
            dosya = f"{pdset._hash(t)}.png"
            Image.fromarray(t).save(os.path.join(gorseller, dosya))
            ef.write(json.dumps({
                "gorsel": f"gorseller/{dosya}",
                # Kimlik KAYNAGI tasiyor: ayni karakterin onden ve yandan hali
                # boldede AYRI karakter sayilmamali, yoksa biri egitime biri
                # teste duser ve sahte yuksek skor cikar.
                "kaynak": f"{r['kaynak']}|yan",
                "artirma": ad, "keypoints": k, "omuz_orani": oran,
            }, ensure_ascii=False) + "\n")
            yazilan += 1
        print(f"  [{i+1}/{len(kalan)}] ok  omuz {oran:.3f}  ({len(ornekler)} ornek)",
              flush=True)

    ef.close()
    kalan_b, _ = pdset.bakiye(gizli)
    print(f"\n{yazilan} ornek yazildi ({len(oranlar)} karakterden)")
    if oranlar:
        print(f"omuz orani: medyan {np.median(oranlar):.3f}  "
              f"({min(oranlar):.3f}-{max(oranlar):.3f})   hedef ~0.148")
    if elenen:
        print("Elenen:", ", ".join(f"{k}={v}" for k, v in sorted(elenen.items())))
    print(f"Bakiye {bakiye:.1f} -> {kalan_b:.1f}   cikti: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
