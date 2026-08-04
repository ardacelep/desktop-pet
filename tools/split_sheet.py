#!/usr/bin/env python3
"""
split_sheet.py — cikarilmis bir sprite sheet'i tek tek karelere boler.

NEDEN BU SIRA (once cikar, sonra bol)
    Gemini'ye animasyonu tek bir sheet olarak urettirdiginizde akis su olmali:

        1. pixelart_extract.py  — TUM sheet'i bir kez native cozunurluge indir
        2. split_sheet.py       — native cozunurlukte kareleri ayir
        3. pack_sheet.py        — kareleri hizalayip temiz bir sheet uret

    Sezgisel olan sira (once bol, sonra her kareyi ayri cikar) YANLIS: izgara
    tespiti her kare icin bagimsiz calisir ve bir kare 100x100, digeri 97x97
    tespit edilebilir. O noktada kareler farkli piksel olceginde olur ve bunu
    duzeltmenin tek yolu olceklemektir — yani piksel sanatini bozmaktir.
    Pixel art izgarasi sheet'in tamaminda TEK bir kafes; bir kez olculunce tum
    kareler garantili ayni olcekte cikar. Ayrica dar bir seritte izgara tespiti
    tum goruntudekinden daha az veriyle calisir, yani daha az guvenilirdir.

NASIL BOLUYOR
    Cikarim sonrasi arka plan gercekten seffaf oldugu icin kareler arasindaki
    bosluk TAMAMEN BOS satir/sutunlardir. Once bos satir bantlari (grid duzeni
    icin), sonra her bant icinde bos sutun bantlari araniyor. Boylece 1xN, Nx1
    ve RxC duzenlerinin hepsi ayni kodla calisiyor.

    Kareler birbirine degiyorsa otomatik ayirma tek kare bulur; o zaman
    --rows/--cols ile esit bolme yapilir. Esit bolmenin kareleri tam ortalamasi
    gerekmez — pack_sheet zaten icerige gore yeniden hizaliyor.

KULLANIM
    python3 tools/pixelart_extract.py sheet_ham.png sheet_native.png
    python3 tools/split_sheet.py sheet_native.png -o kareler/ --frames 7
    python3 tools/pack_sheet.py kareler/kare_*.png -o walk_right_spritesheet.png --gif on.gif
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
from PIL import Image


def bands(occupied: np.ndarray, min_gap: int = 1) -> list[tuple[int, int]]:
    """Dolu olan indekslerin ardisik bloklarini dondurur: [(bas, bit), ...].

    `min_gap`ten kisa bosluklar ayirici sayilmaz — karakterin icindeki tek
    piksellik bir bosluk kareyi ikiye bolmesin diye."""
    idx = np.flatnonzero(occupied)
    if idx.size == 0:
        return []
    kesikler = np.flatnonzero(np.diff(idx) > min_gap)
    baslar = np.concatenate(([idx[0]], idx[kesikler + 1]))
    bitisler = np.concatenate((idx[kesikler], [idx[-1]])) + 1
    return [(int(a), int(b)) for a, b in zip(baslar, bitisler)]


def detect_frames(rgba: np.ndarray, min_gap: int = 1
                  ) -> tuple[list[tuple[int, int, int, int]], int, int]:
    """Kareleri bulur. Doner: (kutular, satir_sayisi, en_fazla_sutun).

    Kutular okuma sirasinda: ustten alta, her satirda soldan saga."""
    opaque = rgba[:, :, 3] > 0
    satir_bantlari = bands(opaque.any(axis=1), min_gap)
    kutular: list[tuple[int, int, int, int]] = []
    en_fazla_sutun = 0
    for y0, y1 in satir_bantlari:
        serit = opaque[y0:y1]
        sutun_bantlari = bands(serit.any(axis=0), min_gap)
        en_fazla_sutun = max(en_fazla_sutun, len(sutun_bantlari))
        for x0, x1 in sutun_bantlari:
            # kareyi kendi icinde de sikilastir (bant yuksekligi tum satiri kapsar)
            hucre = opaque[y0:y1, x0:x1]
            ys = np.flatnonzero(hucre.any(axis=1))
            kutular.append((y0 + int(ys[0]), y0 + int(ys[-1]) + 1, x0, x1))
    return kutular, len(satir_bantlari), en_fazla_sutun


def uniform_frames(rgba: np.ndarray, rows: int, cols: int
                   ) -> list[tuple[int, int, int, int]]:
    """Icerigi esit RxC hucreye boler — kareler birbirine degiyorsa son care."""
    opaque = rgba[:, :, 3] > 0
    if not opaque.any():
        raise ValueError("goruntude opak piksel yok")
    ys, xs = np.where(opaque)
    y0, y1, x0, x1 = int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1
    h, w = y1 - y0, x1 - x0
    kutular = []
    for r in range(rows):
        for c in range(cols):
            kutular.append((y0 + r * h // rows, y0 + (r + 1) * h // rows,
                            x0 + c * w // cols, x0 + (c + 1) * w // cols))
    return kutular


def preview(rgba: np.ndarray, kutular: list[tuple[int, int, int, int]],
            path: str, scale: int = 4) -> None:
    """Bulunan kare sinirlarini gorselin uzerine cizer — bolme yanlissa hemen gorulur."""
    h, w = rgba.shape[:2]
    yy, xx = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    desen = ((yy // 4) + (xx // 4)) % 2
    zemin = np.where(desen[..., None] == 0,
                     np.array([60, 60, 66], np.uint8), np.array([44, 44, 50], np.uint8))
    alfa = rgba[:, :, 3:4].astype(np.float32) / 255.0
    tuval = (rgba[:, :, :3] * alfa + zemin * (1 - alfa)).astype(np.uint8)
    for y0, y1, x0, x1 in kutular:
        tuval[y0:y1, x0] = tuval[y0:y1, x1 - 1] = (255, 60, 60)
        tuval[y0, x0:x1] = tuval[y1 - 1, x0:x1] = (255, 60, 60)
    Image.fromarray(tuval).resize((w * scale, h * scale), Image.NEAREST).save(path)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Cikarilmis bir sprite sheet'i tek tek karelere boler.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("sheet", help="pixelart_extract.py'den cikmis sheet PNG")
    parser.add_argument("-o", "--outdir", required=True, help="Karelerin yazilacagi klasor")
    parser.add_argument("--frames", type=int, default=None,
                        help="Beklenen kare sayisi. Verilirse dogrulanir; "
                             "tutmazsa hata verir (sessizce yanlis bolme yapmaz).")
    parser.add_argument("--rows", type=int, default=None,
                        help="Otomatik ayirma calismazsa esit bolme icin satir sayisi")
    parser.add_argument("--cols", type=int, default=None,
                        help="Otomatik ayirma calismazsa esit bolme icin sutun sayisi")
    parser.add_argument("--min-gap", type=int, default=1,
                        help="Kareleri ayiran en kisa bos serit (varsayilan 1 piksel)")
    parser.add_argument("--prefix", default="kare", help="Dosya adi oneki (varsayilan kare)")
    parser.add_argument("--preview", help="Bulunan kare sinirlarini cizen PNG")
    args = parser.parse_args(argv)

    try:
        img = Image.open(args.sheet)
    except (FileNotFoundError, OSError) as err:
        print(f"HATA: {err}", file=sys.stderr)
        return 1
    rgba = np.array(img.convert("RGBA"))
    if args.min_gap < 1:
        print("HATA: --min-gap en az 1 olmali (0 verilirse her sutun ayri kare sayilir).",
              file=sys.stderr)
        return 1

    if (rgba[:, :, 3] == 255).all():
        print("HATA: goruntude seffaf piksel yok. Bu araci HAM Gemini ciktisina degil, "
              "once pixelart_extract.py'den gecirilmis dosyaya uygulayin — kareleri "
              "ayiran boslugu bulabilmek icin arka planin gercekten seffaf olmasi gerekiyor.",
              file=sys.stderr)
        return 1

    if args.rows or args.cols:
        rows, cols = args.rows or 1, args.cols or 1
        try:
            kutular = uniform_frames(rgba, rows, cols)
        except ValueError as err:
            print(f"HATA: {err}", file=sys.stderr)
            return 1
        print(f"Esit bolme: {rows} satir x {cols} sutun = {len(kutular)} kare")
    else:
        kutular, satir, sutun = detect_frames(rgba, args.min_gap)
        if not kutular:
            print("HATA: hic kare bulunamadi — goruntu tamamen seffaf.", file=sys.stderr)
            return 1
        duzen = f"{satir} satir x {sutun} sutun" if satir > 1 else f"{len(kutular)} kare tek sirada"
        print(f"Bulunan duzen: {duzen} -> {len(kutular)} kare")

    if args.frames is not None and len(kutular) != args.frames:
        print(f"HATA: {args.frames} kare bekleniyordu, {len(kutular)} bulundu.\n"
              f"  Fazla cikiyorsa: karakterden kopuk bir leke ayri kare sayilmis olabilir; "
              f"--min-gap degerini artirin ya da cikarimda --speck-size buyutun.\n"
              f"  Az cikiyorsa: kareler birbirine degiyor; --rows/--cols ile esit bolun.\n"
              f"  Her durumda --preview ile bolmeyi gozle kontrol edin.", file=sys.stderr)
        return 1

    os.makedirs(args.outdir, exist_ok=True)
    genislik = len(str(len(kutular)))
    yollar = []
    print("\nKareler:")
    for i, (y0, y1, x0, x1) in enumerate(kutular, start=1):
        kare = rgba[y0:y1, x0:x1]
        yol = os.path.join(args.outdir, f"{args.prefix}_{i:0{genislik}d}.png")
        Image.fromarray(kare).save(yol)
        yollar.append(yol)
        print(f"  {os.path.basename(yol)}  {x1 - x0}x{y1 - y0}  "
              f"({int((kare[:, :, 3] > 0).sum())} opak piksel)")

    yukseklikler = [y1 - y0 for y0, y1, _, _ in kutular]
    if len(yukseklikler) > 1 and max(yukseklikler) > 1.2 * min(yukseklikler):
        print(f"\nUYARI: kare yukseklikleri cok farkli ({min(yukseklikler)}-"
              f"{max(yukseklikler)}). Gemini kareleri farkli boyda cizmis olabilir; "
              f"pack_sheet ayak cizgisine hizalar ama boy farki kalir.", file=sys.stderr)

    if args.preview:
        preview(rgba, kutular, args.preview)
        print(f"\nOnizleme: {args.preview} — kare sinirlari kirmizi cerceveyle isaretli")

    print(f"\nSiradaki adim:\n  python3 tools/pack_sheet.py "
          f"{os.path.join(args.outdir, args.prefix)}_*.png -o walk_right_spritesheet.png --gif on.gif")
    return 0


if __name__ == "__main__":
    sys.exit(main())
