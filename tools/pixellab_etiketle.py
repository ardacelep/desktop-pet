#!/usr/bin/env python3
"""
pixellab_etiketle.py — bir klasordeki sprite'lari `estimate-skeleton` ile etiketler.

    python3 tools/pixellab_etiketle.py _data/lpc_etiket/gorseller

NEDEN BU YOL

    Kendi poz modelimiz LPC karelerinde cokuyor — olculdu, iskelet govdenin
    sol ustunde topluyor ve buyutme katini 2/3/4/6 denemek duzeltmiyor. Sorun
    olcek degil TARZ: LPC'nin kalin konturlu, bloklu cizimi egitim
    dagilimimizin disinda.

    `estimate-skeleton` bu isi zaten yapiyor ve EGITIM VERIMIZIN TAMAMINI o
    etiketledi. Yani konvansiyon birebir tutuyor: NECK = iki omuzun orta
    noktasi, LEG = ayak bilegi, SOL/SAG = karakterin kendi soli/sagi. Baska
    bir kaynaktan etiket almak sessiz bir konvansiyon kaymasi olurdu.

    MALIYET: cagri basina 0.1 generation (olculdu — 37 cagri bakiyeyi
    40.0'dan 36.3'e dusurdu). 40'lik bir abonelik 400 kareye yetiyor.

    Ilk olcumde "bedava" sandim: cagridan HEMEN SONRA bakiyeye bakinca hala
    40.0 gorunuyor. Bakiye ucu gecikmeli guncelleniyor ve bu tuzaga bu
    projede uc kez dusuldu (`rotate` 0.5 sanildi, gercek 1.0;
    `animate-with-skeleton` 0.1 sanildi, gercek ~1.0). Bu yuzden maliyet
    artik BAKIYEDEN CIKARILMIYOR: yanitin kendi `usage` alani okunuyor.

CIKTI ARAYUZUN OKUDUGU BICIMDE
    `skeleton_edit.py`nin JSONL'ine yaziliyor, `elle: false` ile. Yani
    `npm run etiketle` acildiginda bu tahminler yuklu geliyor ve is elle
    NOKTA YERLESTIRMEK degil DUZELTMEK oluyor. Elle kaydedilen bir kare
    `elle: true` aliyor ve VARSAYILAN OLARAK korunuyor; uzerine yazmak icin
    `--uzerine-yaz` gerekiyor.
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request

UC = "https://api.pixellab.ai/v2/estimate-skeleton"


def _anahtar(kok: str) -> str:
    yol = os.path.join(kok, ".env")
    for satir in open(yol):
        if satir.startswith("PIXELLAB_API_KEY="):
            return satir.split("=", 1)[1].strip()
    raise SystemExit(f"HATA: {yol} icinde PIXELLAB_API_KEY yok.")


def iskelet_cikar(anahtar: str, png: str, deneme: int = 3) -> tuple[list[dict], dict]:
    """(18 keypoint, usage) dondurur. Keypoint'ler 0-1 normalize.

    `usage` yanitin kendi maliyet raporu — bakiyeden cikarim yapmak yanlis
    sonuc veriyor, cunku bakiye gecikmeli guncelleniyor."""
    with open(png, "rb") as f:
        img = base64.b64encode(f.read()).decode()
    govde = json.dumps({"image": {"type": "base64", "base64": img}}).encode()
    basliklar = {"Authorization": f"Bearer {anahtar}",
                 "Content-Type": "application/json"}
    for i in range(deneme):
        try:
            r = urllib.request.Request(UC, data=govde, headers=basliklar)
            with urllib.request.urlopen(r, timeout=120) as y:
                d = json.load(y)
                return d["keypoints"], (d.get("usage") or {})
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and i < deneme - 1:
                time.sleep(2 * (i + 1))
                continue
            raise SystemExit(f"HATA {e.code}: {e.read().decode()[:300]}")
        except (urllib.error.URLError, TimeoutError):
            if i < deneme - 1:
                time.sleep(2 * (i + 1))
                continue
            raise
    return [], {}


def main(argv=None):
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = argparse.ArgumentParser(description="Klasoru estimate-skeleton ile etiketler.")
    p.add_argument("klasor")
    p.add_argument("--kayit", default=None,
                   help="Cikti JSONL. Varsayilan: klasor/iskeletler.jsonl "
                        "(arayuzun okudugu yer).")
    # Elle duzeltilmis kareler VARSAYILAN OLARAK korunuyor. Bunun tersi bir
    # kez yapildi ve 36 karelik elle duzeltmeyi yok etti: koruma bayrak
    # ardinda oldugu surece unutulabiliyor, unutulunca da geri donusu yok.
    # Uzerine yazmak artik acikca istenmeli.
    p.add_argument("--uzerine-yaz", action="store_true",
                   help="Elle duzeltilmis kareleri de YENIDEN etiketle. "
                        "DIKKAT: yapilan duzeltmeler geri donusu olmadan silinir.")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args(argv)

    if not os.path.isdir(args.klasor):
        raise SystemExit(f"HATA: klasor yok: {args.klasor}")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import skeleton_edit as se

    durum = se.Durum(None, None, se.Tahminci(None),
                     kayit=args.kayit, klasor=args.klasor)
    var = durum.kayitlar()
    anahtar = _anahtar(kok)
    dosyalar = sorted(glob.glob(os.path.join(args.klasor, "*.png")))
    if args.limit:
        dosyalar = dosyalar[:args.limit]

    yazilan = atlanan = 0
    toplam_maliyet: dict[str, float] = {}
    piksel_gelen: list[str] = []
    for i, y in enumerate(dosyalar):
        ad = os.path.basename(y)
        eski = var.get((ad, 0))
        if not args.uzerine_yaz and eski and eski.get("elle"):
            atlanan += 1
            continue
        kp, kullanim = iskelet_cikar(anahtar, y)
        for k, v in kullanim.items():
            if isinstance(v, (int, float)):
                toplam_maliyet[k] = toplam_maliyet.get(k, 0.0) + float(v)
        from PIL import Image
        with Image.open(y) as im:
            w, h = im.size
        # API BAZEN NORMALIZE, BAZEN PIKSEL DONUYOR. Olculdu: 36 karenin
        # 3'unde (%8) koordinatlar 0-1 yerine piksel geldi (64px karede 57-58).
        # Sema "normalize" diyor ama gercek boyle degil. Kontrolsuz birakmak
        # o kareleri sessizce cope atiyor — kukla 0 piksel cikiyordu.
        enb = max((max(abs(k["x"]), abs(k["y"])) for k in kp), default=0.0)
        if enb > 1.05:
            kp = [dict(k, x=k["x"] / w, y=k["y"] / h) for k in kp]
            piksel_gelen.append(ad)
        # Kayit ICI koordinatlar PIKSEL; API 0-1 normalize donuyor. Arayuz
        # piksel bekliyor, donusum burada yapilmali yoksa noktalar sol ust
        # kosede toplanir.
        noktalar = {k["label"]: [round(k["x"] * w, 2), round(k["y"] * h, 2)]
                    for k in kp}
        durum.kaydet({"dosya": ad, "kare": 0,
                      "yon": ("east" if "_east_" in ad else
                              "south" if "_south_" in ad else
                              "west" if "_west_" in ad else
                              "north" if "_north_" in ad else "south"),
                      "keypoints": kp, "noktalar": noktalar, "elle": False})
        yazilan += 1
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(dosyalar)}", flush=True)

    print(f"\n{yazilan} etiketlendi, {atlanan} elle duzeltilmis kare KORUNDU")
    if args.uzerine_yaz:
        print("  (--uzerine-yaz aciktı: elle duzeltmeler de yeniden etiketlendi)")
    if toplam_maliyet:
        print("maliyet: " + ", ".join(f"{k}={v:.4g}" for k, v in
                                      sorted(toplam_maliyet.items()))
              + "   (yanitin kendi usage alanindan, bakiyeden cikarim degil)")
    if piksel_gelen:
        print(f"UYARI: {len(piksel_gelen)} kare NORMALIZE DEGIL piksel koordinat "
              f"dondu, cevrildi: {', '.join(piksel_gelen[:5])}"
              + (" ..." if len(piksel_gelen) > 5 else ""))
    print(f"kayit: {durum.kayit}")
    print(f"duzeltmek icin: npm run etiketle")
    return 0


if __name__ == "__main__":
    sys.exit(main())
