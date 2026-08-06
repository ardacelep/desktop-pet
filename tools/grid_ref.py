#!/usr/bin/env python3
"""
grid_ref.py — bitmis bir sprite sheet'i Gemini'ye verilecek IZGARA REFERANSINA cevirir.

NEDEN BU ARAC VAR
    Yurume dongusunu Gemini'ye sifirdan cizdirmek calismiyor; calisan yol,
    animasyonu dogru olan hazir bir sheet'i poz referansi verip yalnizca
    karakteri degistirtmek. Ama referansi SERIT verip cikti IZGARA istemek
    pozlamanin kalitesini dusuruyor: model ayni anda hem yeniden dizmek hem
    karakter degistirmek zorunda kaliyor ve poza ayirdigi dikkat azaliyor.

    Cozum, referansi zaten istedigimiz duzende vermek. Motorun kullandigi
    dosya yatay serit (sprite-animator oyle diliyor), o yuzden donusumu burada
    yapiyoruz: serit -> izgara.

FILIGRAN
    Gemini "filigran ekleme" densin ya da denmesin kosedeki parilti (✦)
    isaretini koyuyor; olculdu, SAG ALT'a dusuyor. Bir uretimde tam karakterin
    sortunun uzerine geldi: kopuk olmadigi icin leke temizligi yakalayamiyor,
    rengi de karakterin gri tonlariyla ayni ailede oldugu icin renk olcutu de
    ayirt edemiyor. Yani sonradan temizlenemiyor.

    Bu yuzden duzen SAG ALT HUCREYI BOS BIRAKACAK sekilde seciliyor: 8 kare
    2x4'e degil 3x3'e diziliyor, dokuzuncu hucre bos kaliyor ve filigran oraya
    dusuyor. Bos hucre karakter tasimadigi icin cikarimda zararsiz.

DIS KENAR PAYI
    Kareler arasindaki boslugun yaninda DIS kenarda da pay birakiliyor.
    Olculdu: bir Gemini ciktisinda karakterlerin ayaklari tuvalin alt kenarina
    degiyordu; `detect_background_tones` dama tonlarini tam o kenar seridinden
    ogrendigi icin ayakkabi konturu (#000000) ucuncu bir "dama tonu" sanildi,
    tolerans 60'a firladi ve karakter yendi (cikti 26x15'e dustu). Alta pay
    eklenince ayni dosyada tonlar duzeldi.

KULLANIM
    python3 tools/grid_ref.py walk_right_spritesheet.png -o izgara_referans.png
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
from PIL import Image


def duzen_sec(kare: int, bos_birak: bool = True) -> tuple[int, int]:
    """Kare sayisina gore (satir, sutun) secer.

    Iki olcut: tuval kareye yakin olsun (Gemini kare canvas'ta daha tutarli,
    ayrica asiri en-boy orani indirirken yeniden sikistirmaya yol aciyor) ve
    `bos_birak` isteniyorsa SAG ALT hucre bos kalsin (filigran oraya dussun).

    Bos hucre icin satir*sutun > kare olmasi yetmiyor; fazlaligin son satirin
    SONUNDA toplanmasi gerekiyor ki bos hucre sag altta olsun. Satir sayisi
    tarandiginda bu kendiliginden saglaniyor: kareler soldan saga dolduruluyor,
    artan yer hep en sonda kaliyor."""
    gerekli = kare + (1 if bos_birak else 0)
    en_iyi, en_iyi_puan = (1, kare), float("inf")
    for satir in range(1, gerekli + 1):
        sutun = -(-gerekli // satir)              # yukari yuvarlama
        if satir * sutun < gerekli:
            continue
        # kareye yakinlik: en-boy orani 1'e ne kadar uzak
        puan = abs(sutun / satir - 1.0) + 0.15 * (satir * sutun - gerekli)
        if puan < en_iyi_puan:
            en_iyi, en_iyi_puan = (satir, sutun), puan
    return en_iyi


def kareleri_ayir(rgba: np.ndarray, kutu: int) -> list[np.ndarray]:
    """Yatay seridi `kutu` genisliginde karelere boler."""
    h, w = rgba.shape[:2]
    if w % kutu:
        raise ValueError(f"serit genisligi {w}, kare kutusu {kutu}'ye tam bolunmuyor")
    return [rgba[:, i * kutu:(i + 1) * kutu] for i in range(w // kutu)]


def izgara_kur(kareler: list[np.ndarray], satir: int, sutun: int, kutu: int,
               olcek: int, bosluk: int, pay: int,
               tonlar: tuple[tuple[int, int, int], tuple[int, int, int]],
               dama_blok: int) -> Image.Image:
    """Kareleri izgaraya dizip dama desenli, buyutulmus bir referans uretir.

    Dama karesi `dama_blok` PIKSEL BLOGU boyunda ve izgaraya hizali; boylece
    `pixelart_extract`in izgara tespiti damayla ayni kafese oturuyor."""
    hucre = kutu + bosluk
    nat_w = pay * 2 + sutun * kutu + (sutun - 1) * bosluk
    nat_h = pay * 2 + satir * kutu + (satir - 1) * bosluk

    yerlesim = np.zeros((nat_h, nat_w, 4), dtype=np.uint8)
    for i, kare in enumerate(kareler):
        r, c = divmod(i, sutun)
        y, x = pay + r * hucre, pay + c * hucre
        yerlesim[y:y + kutu, x:x + kutu] = kare

    buyuk = np.repeat(np.repeat(yerlesim, olcek, axis=0), olcek, axis=1)
    H, W = buyuk.shape[:2]

    kare_px = max(1, dama_blok * olcek)
    yy, xx = np.meshgrid(np.arange(H), np.arange(W), indexing="ij")
    desen = ((yy // kare_px) + (xx // kare_px)) % 2
    zemin = np.where(desen[..., None] == 0,
                     np.array(tonlar[0], dtype=np.uint8),
                     np.array(tonlar[1], dtype=np.uint8))

    opak = buyuk[:, :, 3:4] > 0
    return Image.fromarray(np.where(opak, buyuk[:, :, :3], zemin).astype(np.uint8))


def renk_ayristir(metin: str) -> tuple[int, int, int]:
    m = metin.strip().lstrip("#")
    if len(m) != 6:
        raise argparse.ArgumentTypeError(f"renk '#rrggbb' olmali: {metin}")
    try:
        return tuple(int(m[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        raise argparse.ArgumentTypeError(f"gecersiz onaltilik renk: {metin}")


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Yatay sprite sheet'i Gemini'ye verilecek izgara referansina cevirir.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Ornek:\n  python3 tools/grid_ref.py walk_right_spritesheet.png -o ref.png")
    p.add_argument("sheet", help="Yatay sprite sheet PNG (seffaf arka planli)")
    p.add_argument("-o", "--output", required=True, help="Cikti PNG (izgara referansi)")
    p.add_argument("--frame-size", type=int, default=None,
                   help="Kare kutusu; varsayilan sheet yuksekligi")
    p.add_argument("--rows", type=int, default=None, help="Satir sayisi (varsayilan otomatik)")
    p.add_argument("--cols", type=int, default=None, help="Sutun sayisi (varsayilan otomatik)")
    p.add_argument("--no-reserve", action="store_true",
                   help="Sag alt hucreyi bos birakma (filigran karakterin uzerine dusebilir)")
    p.add_argument("--scale", type=int, default=None,
                   help="Buyutme; varsayilan --target'a gore secilir")
    p.add_argument("--target", type=int, default=2048,
                   help="Hedeflenen cikti kenari (varsayilan 2048)")
    p.add_argument("--gap", type=int, default=6,
                   help="Kareler arasi bosluk, native piksel (varsayilan 6)")
    p.add_argument("--margin", type=int, default=8,
                   help="Dis kenar payi, native piksel (varsayilan 8)")
    p.add_argument("--checker", type=renk_ayristir, nargs=2,
                   default=[(255, 0, 255), (192, 0, 192)],
                   metavar=("RENK1", "RENK2"), help="Dama renkleri (varsayilan magenta)")
    p.add_argument("--checker-block", type=int, default=8,
                   help="Dama karesi kac piksel blogu (varsayilan 8; 2 ve 3 KULLANMAYIN)")
    args = p.parse_args(argv)

    try:
        rgba = np.array(Image.open(args.sheet).convert("RGBA"))
    except (FileNotFoundError, OSError) as err:
        print(f"HATA: {err}", file=sys.stderr)
        return 1

    if (rgba[:, :, 3] > 0).all():
        print("HATA: sheet'te seffaf piksel yok. Bu araci pack_sheet ciktisina "
              "uygulayin — kareleri ayirabilmek icin arka planin seffaf olmasi "
              "gerekiyor.", file=sys.stderr)
        return 1

    # Olculdu: dama karesi blogun 2 ya da 3 kati oldugunda izgara tespiti
    # damanin periyoduna kilitleniyor ve karakteri yari cozunurlukte cikariyor
    # (blok 7px iken 14 ya da 10.5 buluyor, uyum %100'den %15'e dusuyor).
    # 1 ve 4+ guvenli: dama sinyali ya blokla ayni ya da yeterince uzakta.
    if args.checker_block in (2, 3):
        print(f"UYARI: --checker-block {args.checker_block} izgara tespitini bozuyor; "
              f"4 ve ustu ya da 1 kullanin.", file=sys.stderr)

    kutu = args.frame_size or rgba.shape[0]
    try:
        kareler = kareleri_ayir(rgba, kutu)
    except ValueError as err:
        print(f"HATA: {err}", file=sys.stderr)
        return 1

    if args.rows or args.cols:
        satir = args.rows or -(-len(kareler) // args.cols)
        sutun = args.cols or -(-len(kareler) // args.rows)
        if satir * sutun < len(kareler):
            print(f"HATA: {satir}x{sutun} = {satir * sutun} hucre, "
                  f"{len(kareler)} kare sigmiyor.", file=sys.stderr)
            return 1
    else:
        satir, sutun = duzen_sec(len(kareler), bos_birak=not args.no_reserve)

    nat_w = args.margin * 2 + sutun * kutu + (sutun - 1) * args.gap
    nat_h = args.margin * 2 + satir * kutu + (satir - 1) * args.gap
    olcek = args.scale or max(1, args.target // max(nat_w, nat_h))

    im = izgara_kur(kareler, satir, sutun, kutu, olcek, args.gap, args.margin,
                    tuple(args.checker), args.checker_block)
    im.save(args.output)

    bos = satir * sutun - len(kareler)
    print(f"{len(kareler)} kare -> {satir} satir x {sutun} sutun"
          + (f"  ({bos} hucre bos, sonuncusu sag altta)" if bos else ""))
    print(f"Native yerlesim: {nat_w}x{nat_h}   buyutme: {olcek}x")
    print(f"Kaydedildi: {args.output} ({im.width}x{im.height}, "
          f"dama karesi {args.checker_block * olcek}px)")
    if not bos and not args.no_reserve:
        print("UYARI: bos hucre kalmadi — Gemini'nin sag alta koydugu filigran "
              "karakterin uzerine dusebilir.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
