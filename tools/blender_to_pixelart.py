#!/usr/bin/env python3
"""
blender_to_pixelart.py — Blender render'larini egitim kumesi bicimine cevirir.

    ~/ComfyUI/venv/bin/python tools/blender_to_pixelart.py \
        -i _data/blender_ham -o _data/blender_px

NEDEN AYRI BIR ADIM

    Blender 3B->2B isini yapiyor (`blender_veri.py`), burasi 2B->pixel art
    isini. Ayirmanin sebebi pratik: pikselleştirmeyi degistirmek icin
    yeniden render almak gerekmiyor — 256 kare ~3 dakika, cevrim saniyeler.

    Hat CHEN'INKININ AYNISI (PixelOE -> tuvale otur), cunku o hattin
    kazandirdigi olculdu: Chen verisi 4.02 -> 3.64px. Ayni donusumu
    kullanmak, sonucu Chen'le kiyaslanabilir kiliyor.

BLENDER'DA OLMAYAN ADIM: ZEMIN AYIKLAMA
    Chen'de goruntunun arka planini tahmin etmek gerekiyordu ve kabul oraninin
    %53'te kalmasinin baslica sebebi oydu (zemin=1104, renk=765). Burada alfa
    zaten kesin, o kapi hic yok.

GORUNURLUK KORUNUYOR
    `gorunur` bayragi cikti satirlarinda tasiniyor. Model su an bunu
    kullanmiyor (18 nokta, hepsi her zaman) ama veri uretilirken atmak
    geri donusu olmayan bir kayip olurdu.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chen_to_pixelart as chen  # noqa: E402
import pose_dataset as pdset     # noqa: E402


def kapilar(tuval: np.ndarray, kp: dict, esik_doluluk=(0.05, 0.75),
            esik_eklem=0.55, esik_renk=(4, 400)) -> tuple[bool, dict]:
    """Ornek kabul edilebilir mi?

    Chen'in `iou` kapisi burada YOK: orada donusumun orijinal siluete oturup
    oturmadigi olculuyordu, cunku zemin ayiklama basarisiz olabiliyordu.
    Blender'da alfa kesin, kiyaslanacak bir "orijinal maske" yok."""
    opak = tuval[:, :, 3] > 0
    b = tuval.shape[0]
    if not opak.any():
        return False, {"sebep": "bos"}

    # Eklemler karakterin uzerinde mi (1 piksel genisletilmis siluet)
    gen = opak.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            gen |= np.roll(np.roll(opak, dy, 0), dx, 1)
    icinde = sum(1 for x, y in kp.values()
                 if 0 <= int(round(x * b)) < b and 0 <= int(round(y * b)) < b
                 and gen[int(round(y * b)), int(round(x * b))])
    eklem = icinde / max(len(kp), 1)
    doluluk = float(opak.mean())
    renk = int(len(np.unique(tuval[:, :, :3][opak].reshape(-1, 3), axis=0)))

    olcum = {"eklem": round(eklem, 3), "doluluk": round(doluluk, 3), "renk": renk}
    tamam = (eklem >= esik_eklem
             and esik_doluluk[0] <= doluluk <= esik_doluluk[1]
             and esik_renk[0] <= renk <= esik_renk[1])
    if not tamam:
        olcum["sebep"] = ("eklem" if eklem < esik_eklem else
                          "doluluk" if not (esik_doluluk[0] <= doluluk <= esik_doluluk[1])
                          else "renk")
    return tamam, olcum


def main(argv=None):
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = argparse.ArgumentParser(description="Blender render'larini pixel art'a cevirir.")
    p.add_argument("-i", "--input", default=os.path.join(kok, "_data", "blender_ham"))
    p.add_argument("-o", "--output", default=os.path.join(kok, "_data", "blender_px"))
    p.add_argument("--cell", type=int, default=4, help="PixelOE hucre boyutu")
    p.add_argument("--colors", type=int, default=48)
    p.add_argument("--canvas", type=int, default=128)
    p.add_argument("--augment", type=int, default=6)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--adim", type=int, default=1, metavar="N",
                   help="Her yonde N karede bir al. Komsu kareler birbirine cok "
                        "yakin oldugu icin hepsini almak veriyi tekrarla sisirir; "
                        "poz cesitliligi neredeyse ayni kalir.")
    args = p.parse_args(argv)

    satirlar = [json.loads(l) for l in open(os.path.join(args.input, "etiketler.jsonl"))]
    if args.adim > 1:
        # Kare indeksi kaynaktan okunuyor; seyreltme HER YON icinde ayri
        # yapilmali, yoksa bazi yonler tumuyle atlanir.
        satirlar = [r for r in satirlar
                    if int(r["kaynak"].rsplit("_", 1)[1]) % args.adim == 1]
    if args.limit:
        satirlar = satirlar[:args.limit]
    gorseller = os.path.join(args.output, "gorseller")
    os.makedirs(gorseller, exist_ok=True)

    rng = np.random.default_rng(args.seed)
    elenen: dict[str, int] = {}
    yazilan = kabul = 0
    yol = os.path.join(args.output, "etiketler.jsonl")
    with open(yol, "w", buffering=1) as f:
        for i, r in enumerate(satirlar):
            rgba = np.array(Image.open(os.path.join(args.input, r["gorsel"]))
                            .convert("RGBA"))
            px = chen.pixelize(rgba, args.cell, args.colors)
            # Keypoint'ler 0-1'de; pixelize olcegi degistirdi, tuvale_otur
            # piksel bekliyor.
            kp_px = {l: (v[0] * px.shape[1], v[1] * px.shape[0])
                     for l, v in r["keypoints"].items()}
            sonuc = chen.tuvale_otur(px, kp_px, args.canvas)
            if sonuc is None:
                elenen["bos"] = elenen.get("bos", 0) + 1
                continue
            tuval, kp = sonuc
            tamam, olcum = kapilar(tuval, kp)
            if not tamam:
                elenen[olcum["sebep"]] = elenen.get(olcum["sebep"], 0) + 1
                continue
            kabul += 1

            ornekler = [("ham", tuval, kp)]
            a_t, a_k = pdset.aynala(tuval, kp)
            # Aynalama sol/sag ETIKETLERINI de takas ediyor; gorunurluk
            # bayragi da onunla birlikte takas edilmeli.
            a_g = {pdset._es(l): v for l, v in r["gorunur"].items()}
            ornekler.append(("ayna", a_t, a_k))
            gorunurluk = {"ham": r["gorunur"], "ayna": a_g}
            for j in range(args.augment):
                ad, t, k = ornekler[j % 2]
                t2 = pdset.ton_kaydir(t, float(rng.uniform(0, 1)), rng)
                s = pdset.olcekle(t2, k, float(rng.uniform(0.7, 1.0)),
                                  int(rng.integers(-8, 9)), int(rng.integers(-8, 9)))
                if s:
                    ornekler.append((f"{ad}+art{j}", s[0], s[1]))
                    gorunurluk[f"{ad}+art{j}"] = gorunurluk[ad]

            for ad, t, k in ornekler:
                dosya = f"{pdset._hash(t)}.png"
                Image.fromarray(t).save(os.path.join(gorseller, dosya))
                f.write(json.dumps({
                    "gorsel": f"gorseller/{dosya}",
                    "kaynak": r["kaynak"],
                    "artirma": ad,
                    "keypoints": {l: [round(v[0], 6), round(v[1], 6)]
                                  for l, v in k.items()},
                    "gorunur": gorunurluk.get(ad, r["gorunur"]),
                    "yon": r.get("yon"),
                }, ensure_ascii=False) + "\n")
                yazilan += 1
            if (i + 1) % 25 == 0:
                print(f"  {i+1}/{len(satirlar)} islendi, {kabul} kabul, "
                      f"{yazilan} ornek", flush=True)

    print(f"\n{kabul}/{len(satirlar)} kare kabul edildi -> {yazilan} ornek")
    if elenen:
        print("Elenen:", ", ".join(f"{k}={v}" for k, v in sorted(elenen.items())))
    print(f"cikti: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
