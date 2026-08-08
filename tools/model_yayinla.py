#!/usr/bin/env python3
"""
model_yayinla.py — uretim modelini depoya konabilecek hale getirir.

    python3 tools/model_yayinla.py _data/modeller/uretim.pt -o models/poz_modeli.pt

NEDEN

    `npm run skeleton` ile gelen iskelet duzenleyici poz modelini kullaniyor
    ve model olmadan sezgisel algoritmaya dusuyor — olculdu, o algoritma
    gorulmemis karakterde 13.46px, model 1.51-4.06px. Yani depoyu klonlayan
    biri model olmadan belirgin sekilde kotu bir araca bakar.

    Egitim verisi (`_data/`) gitignore'da ve olmali: gigabaytlarca gorsel ve
    PixelLab bakiyesiyle uretildi. Ama MODEL tek dosya ve klonlayanin
    ihtiyaci olan tek sey o.

BOYUT

    Checkpoint fp32'de ~34 MB. Git her surumu KALICI olarak sakliyor, yani
    her yeniden egitim depoya 34 MB daha ekliyor ve geri alinamiyor.

    Bu arac fp16'ya cevirip yaklasik yariya indiriyor. Cikarim icin fp16
    yeterli — kayip olculuyor ve raporlaniyor; esigi asarsa arac DURUYOR,
    cunku sessizce bozulmus bir model en kotu sonuc olurdu.

    Yine de seyrek yayinlayin: her tur degil, olculebilir sekilde iyilesince.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skeleton as sk  # noqa: E402

# fp16 cevirisinin izin verilen en buyuk konum kaymasi (128 tuval pikseli).
# Tolerans olcumumuz 8px'lik iskelet hatasinin animasyona 1.9px yansidigini
# gosterdi; 0.05px onun yaninda hicbir sey, ama sifir da degil — o yuzden
# olculuyor.
KAYMA_ESIGI = 0.05


def main(argv=None):
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = argparse.ArgumentParser(description="Uretim modelini depoya hazirlar.")
    p.add_argument("ckpt", help="Kaynak checkpoint (_data/modeller/uretim.pt)")
    p.add_argument("-o", "--out", default=os.path.join(kok, "models", "poz_modeli.pt"))
    p.add_argument("--ornek", default=os.path.join(kok, "_data", "karisik_yan"),
                   help="Kayma olcumu icin kullanilacak veri seti")
    p.add_argument("--fp32", action="store_true", help="fp16'ya cevirme")
    args = p.parse_args(argv)

    import torch
    import pose_model as pm

    d = torch.load(args.ckpt, map_location="cpu")
    k = d.get("kunye") or {}
    if not k.get("uretim"):
        print("UYARI: bu bir URETIM modeli degil — kunyesine gore bir karakter "
              "disarida birakilarak egitilmis. Kullanim icin tum veriyle "
              "egitilmis model gerekir (--holdout yok).", file=sys.stderr)

    if not args.fp32:
        d["model"] = {a: (v.half() if v.is_floating_point() else v)
                      for a, v in d["model"].items()}
        d["fp16"] = True

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    torch.save(d, args.out)

    kaynak_mb = os.path.getsize(args.ckpt) / 1048576
    cikti_mb = os.path.getsize(args.out) / 1048576
    print(f"{kaynak_mb:.1f} MB -> {cikti_mb:.1f} MB   {args.out}")

    # KAYMA OLCUMU: fp16 ciktiyi ne kadar kaydirdi?
    if args.fp32 or not os.path.exists(os.path.join(args.ornek, "etiketler.jsonl")):
        return 0
    satirlar = pm.veri_oku(args.ornek)[:64]
    kume = pm.Kume(args.ornek, satirlar, d["tuval"])
    dev = torch.device("cpu")

    def tahmin(sd, dtype):
        m = pm.PozModeli(d["tuval"], len(sk.LABELS), on_egitimli=False,
                         derinlik=d["derinlik"])
        m.load_state_dict({a: v.float() for a, v in sd.items()})
        m.to(dev).eval()
        cikti = []
        with torch.no_grad():
            for i in range(0, len(kume), 16):
                x, _, _, _ = pm.toplu([kume[j] for j in range(i, min(i + 16, len(kume)))])
                xl, yl = m(x.to(dev))
                px, py = pm.koordinat_coz(xl, yl, d["tuval"])
                cikti.append(torch.stack([px, py], -1).cpu().numpy())
        return np.concatenate(cikti)

    ham = torch.load(args.ckpt, map_location="cpu")["model"]
    a, b = tahmin(ham, torch.float32), tahmin(d["model"], torch.float16)
    kayma = float(np.mean(np.linalg.norm(a - b, axis=-1)))
    print(f"fp16 kaymasi: {kayma:.4f}px  (esik {KAYMA_ESIGI})")
    if kayma > KAYMA_ESIGI:
        print("HATA: fp16 ciktiyi esikten fazla kaydirdi; --fp32 ile yayinlayin.",
              file=sys.stderr)
        os.remove(args.out)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
