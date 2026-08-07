#!/usr/bin/env python3
"""
iki_gorunus.py — Gemini'nin IKI GORUNUSLU ciktisini onden+yandan kareye ayirir.

    python3 tools/iki_gorunus.py gemini.png -o _calisma/ardus
    python3 tools/iki_gorunus.py gemini.png -o _calisma/ardus --period 10.24

NEDEN AYRI BIR ARAC

    Uygulama karakter basina iki sprite kumesi kullaniyor: onden `idle`, yandan
    `walk_right` (sola yuruyus meta.json'daki "flip": true ile aynadan
    uretiliyor). Yani gereken tek donusum onden -> saga bakan.

    Bu donusumu Gemini'ye AYRI bir uretim olarak yaptirmak olcek kaydiriyor —
    olculdu: boy %12, kafa/govde orani 6 puan. Care ikisini TEK gorselde
    istemek; "tum gorsel tek piksel izgarasinda cizilsin" kurali devreye
    girince bir cizim iki olcek tasiyamiyor (olculdu: kayma %1'e indi).
    Prompt icin bkz. PROMPTS.md bolum 5.

    Bunun sonucu: ANA KARAKTER de bu ciktidan gelmeli. Eski onden gorseli
    saklayip yalnizca yandan kareyi almak, cipayi bosa dusurur — iki sprite
    yine farkli olcekte olur.

MEVCUT ARACLARLA NEDEN OLMUYORDU

    `menu.py`'deki tam boru hatti kareleri sprite sheet'e PAKETLIYOR; bu ikisi
    ise ayni animasyonun kareleri degil, iki ayri gorunus.

    `split_sheet --rows 2 --cols 2` de yanlis: `pixelart_extract` bos alt satiri
    zaten kirpiyor, geriye 1x2 duzen kaliyor ve 2x2 zorlamak her karakteri
    ortadan ikiye biciyor (olculdu: 53x108 yerine dort adet 75x54).

    Otomatik bolme dogru calisiyor ama filigran ucuncu bir "kare" olarak
    cikabiliyor (olculdu: 9x9, 29 opak piksel). Burada en buyuk IKI bilesen
    aliniyor ve soldan saga siralaniyor.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pixelart_extract as px  # noqa: E402
import split_sheet as ss       # noqa: E402

# PROMPTS.md bolum 5'te olculen kabul araliklari.
YUKSEKLIK_TOL = 0.03      # iki karenin boy orani bundan fazla sapmamali
KAFA_TOL = 3.0            # kafa/govde orani, puan


def kareleri_bul(rgba: np.ndarray) -> list[tuple[int, int, int, int]]:
    """En buyuk iki bileseni soldan saga siralayarak dondurur.

    Filigran ucuncu bir kare olarak cikabildigi icin sayiya degil BOYUTA
    bakiliyor — olculen filigran 29 opak piksel, karakterler 3455 ve 4215."""
    kutular, _, _ = ss.detect_frames(rgba)
    if len(kutular) < 2:
        raise SystemExit(f"HATA: {len(kutular)} kare bulundu, 2 bekleniyordu. "
                         "Kareler arasinda bos serit var mi?")
    opak = rgba[:, :, 3] > 0
    boy = [(int(opak[y0:y1, x0:x1].sum()), (y0, y1, x0, x1))
           for (y0, y1, x0, x1) in kutular]
    boy.sort(reverse=True)
    ikisi = [k for _, k in boy[:2]]
    return sorted(ikisi, key=lambda k: k[2])          # soldan saga


def olc(rgba: np.ndarray, kutu: tuple[int, int, int, int]) -> dict:
    y0, y1, x0, x1 = kutu
    m = rgba[y0:y1, x0:x1, 3] > 0
    ys, xs = np.where(m)
    h = int(ys.max() - ys.min() + 1)
    gen = np.array([int(m[y].sum()) for y in range(ys.min(), ys.max() + 1)])
    # boyun = ust yarinin en dar satiri; kafa yuksekligi onun uzerinde kalan
    bas, son = int(h * 0.15), int(h * 0.5)
    kafa = int(np.argmin(gen[bas:son])) + bas if son > bas else 0
    return {"genislik": int(xs.max() - xs.min() + 1), "yukseklik": h,
            "kafa": kafa, "kafa_orani": 100.0 * kafa / max(h, 1)}


def rapor(onden: dict, yandan: dict) -> bool:
    print(f"\n{'':8s} {'genislik':>9s} {'yukseklik':>10s} {'kafa/govde':>11s}")
    print(f"{'onden':8s} {onden['genislik']:9d} {onden['yukseklik']:10d} "
          f"{onden['kafa_orani']:10.0f}%")
    print(f"{'yandan':8s} {yandan['genislik']:9d} {yandan['yukseklik']:10d} "
          f"{yandan['kafa_orani']:10.0f}%")

    boy_orani = yandan["yukseklik"] / max(onden["yukseklik"], 1)
    gen_orani = yandan["genislik"] / max(onden["genislik"], 1)
    kafa_fark = yandan["kafa_orani"] - onden["kafa_orani"]
    print(f"\nyukseklik orani {boy_orani:.3f}   genislik orani {gen_orani:.3f}   "
          f"kafa farki {kafa_fark:+.1f} puan")

    tamam = True
    # En sert olcut: iki sprite ayni nativeFrameSize'i paylasmak zorunda ve
    # araclar olcek farkini duzeltemez (buyutmek piksel uydurur).
    if abs(boy_orani - 1.0) > YUKSEKLIK_TOL:
        print(f"  ✗ YUKSEKLIK: %{100*abs(boy_orani-1):.0f} sapma "
              f"(sinir %{100*YUKSEKLIK_TOL:.0f}). Olcek cipasi tutmamis — "
              f"yeniden urettirin, arac bunu duzeltemez.")
        tamam = False
    else:
        print(f"  ✓ yukseklik %{100*abs(boy_orani-1):.0f} sapma")

    if abs(kafa_fark) > KAFA_TOL:
        print(f"  ✗ KAFA ORANI: {kafa_fark:+.1f} puan (sinir ±{KAFA_TOL:.0f}). "
              f"Profilde kafa buyumus, chibi orani kayar.")
        tamam = False
    else:
        print(f"  ✓ kafa orani {kafa_fark:+.1f} puan")

    # Genislik SERT KAPI DEGIL: olculdu, dolgun karakterlerde profil derinligi
    # onden genislige yaklasiyor (0.906 ve 1.000 ciktigi halde ikisi de dogru
    # profildi). Guvenilir olcut yuz — ona gozle bakilmali.
    if gen_orani > 1.05:
        print(f"  ! genislik {gen_orani:.2f} — daralmamis. Dolgun karakterde "
              f"normal olabilir; yandan karede TEK GOZ ve TEK KULAK var mi, "
              f"gozle dogrulayin.")
    else:
        print(f"  ✓ genislik {gen_orani:.2f}")
    return tamam


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Gemini'nin iki gorunuslu ciktisini onden+yandan kareye ayirir.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Ornek:\n  python3 tools/iki_gorunus.py gemini.png -o _calisma/ardus")
    p.add_argument("girdi", help="Ham Gemini PNG (2x2 duzen, alt satir bos)")
    p.add_argument("-o", "--out", required=True, help="Cikti dizini")
    p.add_argument("--period", type=float, default=None,
                   help="Izgara periyodunu elle ver. 2048'lik Gemini "
                        "ciktilarinda 10.24 cikiyor; eksenlerden biri "
                        "harmonige kilitlenirse (en-boy orani ~1:4 gibi "
                        "imkansiz cikar) bunu kullanin.")
    p.add_argument("--bg-tol", type=int, default=None,
                   help="Dama toleransi. Karakter tuvalin kenarina degdiyse "
                        "olculen tolerans sisiyor; o zaman dusuk bir deger verin.")
    args = p.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    native = os.path.join(args.out, "native.png")
    print("[1/3] Native cozunurluge indiriliyor…")
    px.extract(args.girdi, native, period=args.period, bg_tol=args.bg_tol)

    print("\n[2/3] Kareler ayriliyor…")
    rgba = np.array(Image.open(native).convert("RGBA"))
    kutular = kareleri_bul(rgba)
    yollar = []
    for ad, (y0, y1, x0, x1) in zip(("onden", "yandan"), kutular):
        yol = os.path.join(args.out, f"{ad}.png")
        Image.fromarray(rgba[y0:y1, x0:x1]).save(yol)
        yollar.append(yol)
        print(f"  {ad:7s} -> {yol}  ({x1-x0}x{y1-y0})")

    print("\n[3/3] Kabul olcumleri")
    onden, yandan = (olc(rgba, k) for k in kutular)
    tamam = rapor(onden, yandan)

    print("\n" + "=" * 58)
    if tamam:
        print("Kabul edilebilir. Siradaki adimlar:")
        print(f"  - ana karakter  : {yollar[0]}  (idle kaynagi)")
        print(f"  - yuruyus refs. : {yollar[1]}  (PROMPTS.md bolum 3'e ver)")
        print("  ANA KARAKTERI DE bu ciktidan al — eskisini saklamak olcek")
        print("  cipasini bosa dusurur, iki sprite yine farkli olcekte kalir.")
    else:
        print("Yeniden urettirin. Isaretli olcut arac tarafindan duzeltilemez.")
    return 0 if tamam else 1


if __name__ == "__main__":
    sys.exit(main())
