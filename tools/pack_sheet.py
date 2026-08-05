#!/usr/bin/env python3
"""
pack_sheet.py — tek tek cikarilmis animasyon karelerini TEK bir sprite sheet'te hizalar.

SORUN
    Gemini'ye bir yuruyusun 7 karesini ayri ayri urettirip her birini
    pixelart_extract.py'den gecirdiginizde, kareler birbirine gore KAYIK olur:
      - her kare ayri bir uretim oldugu icin karakter tuval icinde farkli yerde
        duruyor (Gemini kareyi ayni yere koymak zorunda degil),
      - kirpma her kareyi KENDI icerigine gore kirpiyor, yani kolunu uzatan kare
        birkac piksel daha genis cikiyor.
    Kareler yan yana dizilince karakter her karede baska yerde durur ve animasyon
    boyunca TITRER. Bu, kaynak gorsellerin degil, hizalamanin sorunudur.

BU SCRIPT NE YAPAR
    1. Her karenin gercek icerigini (opak piksellerin sinir kutusu) bulur.
    2. Kareleri birbirine hizalar:
         - dikeyde AYAK CIZGISINE (en alt opak satir) — karakter yere basar,
         - yatayda REFERANS KAREYLE ORTUSMEYI en buyuten kaymayi arayarak.
       Yataydaki secim onemli: sinir kutusunun ortasini almak, kolunu uzatan
       karede merkezi kaydirip titreme uretir. Ortusme aramasi govde ve basi
       cakistirir, cunku piksellerin cogunlugu oradadir.
    3. Hepsini ORTAK ve KARE bir kutuya seffaf piksel ekleyerek yerlestirir.
       Motor kareyi kare varsayiyor: sprite-animator.js canvas'i frameSize x
       frameSize yapip sheet'ten ayni boyutta dilim aliyor.
    4. Yatay sheet'i yazar ve meta.json blogunu ekrana basar.

HICBIR ZAMAN OLCEKLEME YAPMAZ
    Kareler yalnizca kaydirilir ve seffaf piksel eklenir. Tek bir piksel bile
    yeniden orneklenmez, tek bir renk bile uydurulmaz. Karelerin native
    cozunurlugu birbirinden farkliysa script UYARIR ama kucultmez — bu, piksel
    sanatinin bozulmadan sag cikamayacagi tek islemdir. Cozum uretim
    asamasindadir: kareleri ayni izgara yogunlugunda yeniden urettirin.

KULLANIM
    python3 tools/pack_sheet.py kare_*.png -o characters/kedi/walk_right_spritesheet.png
    python3 tools/pack_sheet.py kare_*.png -o walk.png --gif onizleme.gif --gif-scale 6
    python3 tools/pack_sheet.py kare_*.png -o walk.png --clip walk_right --duration 120

NOT
    Girdilerin kirpilmis olup olmamasi onemli degil — hizalama zaten icerige
    gore yapiliyor. pixelart_extract.py'yi --no-crop ile calistirmaniz gerekmez.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np
from PIL import Image


def load_frame(path: str) -> np.ndarray:
    """PNG'yi RGBA olarak okur."""
    img = Image.open(path)
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    return np.array(img)


def content_box(rgba: np.ndarray) -> tuple[int, int, int, int]:
    """Opak piksellerin sinir kutusu: (y0, y1, x0, x1), ust/sol dahil alt/sag haric."""
    opaque = rgba[:, :, 3] > 0
    if not opaque.any():
        raise ValueError("kare tamamen seffaf")
    ys, xs = np.where(opaque)
    return int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1


def tight(rgba: np.ndarray) -> np.ndarray:
    y0, y1, x0, x1 = content_box(rgba)
    return rgba[y0:y1, x0:x1]


def _blit(canvas: np.ndarray, patch: np.ndarray, y: int, x: int) -> None:
    """Yalnizca opak pikselleri yazar; seffaf alan altini silmez."""
    h, w = patch.shape[:2]
    hedef = canvas[y:y + h, x:x + w]
    maske = patch[:, :, 3] > 0
    hedef[maske] = patch[maske]


def best_dx(mask: np.ndarray, ref: np.ndarray, search: int) -> tuple[int, float]:
    """`mask`i yatayda kaydirip `ref` ile ortusmeyi en buyuten kaymayi bulur.

    Olcut IoU (kesisim / birlesim). Yuruyus dongusunde bacaklar gercekten
    hareket ettigi icin tam ortusme beklenmez; ama piksellerin cogunlugu govde
    ve bas oldugundan en iyi kayma onlari cakistirir — istenen de budur."""
    en_iyi, en_iyi_dx = -1.0, 0
    for dx in range(-search, search + 1):
        kaydirilmis = np.roll(mask, dx, axis=1)
        if dx > 0:
            kaydirilmis[:, :dx] = False
        elif dx < 0:
            kaydirilmis[:, dx:] = False
        kesisim = int((kaydirilmis & ref).sum())
        birlesim = int((kaydirilmis | ref).sum())
        skor = kesisim / birlesim if birlesim else 0.0
        if skor > en_iyi:
            en_iyi, en_iyi_dx = skor, dx
    return en_iyi_dx, en_iyi


def align(frames: list[np.ndarray], align_x: str = "correlate",
          align_y: str = "bottom") -> tuple[list[tuple[int, int]], list[float], int, int, float]:
    """Her kare icin ortak calisma tuvalindeki (y, x) konumunu hesaplar.

    Doner: (konumlar, ortusme skorlari, tuval yuksekligi, genisligi, capa sutunu)
    Capa ONDALIKLI doner; yuvarlamak kaydirmayi hesaplayan yere birakiliyor."""
    kirpik = [tight(f) for f in frames]
    yukseklikler = [k.shape[0] for k in kirpik]
    genislikler = [k.shape[1] for k in kirpik]

    arama = max(4, max(genislikler) // 3)
    H = max(yukseklikler)
    W = max(genislikler) + 2 * arama

    # dikey: ayak cizgisi
    def dikey(i: int) -> int:
        if align_y == "center":
            return (H - yukseklikler[i]) // 2
        return H - yukseklikler[i]              # bottom

    # yatay: once ortala, sonra referansa gore duzelt
    def orta(i: int) -> int:
        return (W - genislikler[i]) // 2

    ref_maske = np.zeros((H, W), dtype=bool)
    k0 = kirpik[0]
    ref_maske[dikey(0):dikey(0) + k0.shape[0],
              orta(0):orta(0) + k0.shape[1]] = k0[:, :, 3] > 0

    konumlar: list[tuple[int, int]] = [(dikey(0), orta(0))]
    skorlar: list[float] = [1.0]
    for i in range(1, len(kirpik)):
        k = kirpik[i]
        maske = np.zeros((H, W), dtype=bool)
        maske[dikey(i):dikey(i) + k.shape[0],
              orta(i):orta(i) + k.shape[1]] = k[:, :, 3] > 0
        if align_x == "center":
            dx, skor = 0, float((maske & ref_maske).sum()) / max(1, int((maske | ref_maske).sum()))
        else:
            dx, skor = best_dx(maske, ref_maske, arama)
        konumlar.append((dikey(i), orta(i) + dx))
        skorlar.append(skor)
    # Capa: TUM hizalanmis karelerin ortalama kutle merkezi. Kutu bunun
    # ETRAFINA kuruluyor.
    #
    # Neden referans karesi degil: eskiden capa yalnizca ilk karenin sinir
    # kutusu ortasiydi. Kareler birbirine korelasyonla dogru hizalaniyordu
    # ama yiginin kutuya yerlesimi tek bir kareye baglanmis oluyordu; ilk
    # kare temsili degilse butun sheet kayiyordu. Olculdu: karakter1'in
    # yuruyusunde referans capa 33, karelerin ortalama kutle merkezi 34.42
    # -- 1.42 piksel sistematik sapma. Ayni seti bu araclarla yeniden
    # paketlemek flip sicramasini 0.29'dan 1.85 piksele CIKARIYORDU.
    #
    # Kutle merkezi, sinir kutusu ortasindan daha saglam: bir karede uzanan
    # kol sinir kutusunu asimetrik yapar ama govdenin agirligini kaydirmaz.
    toplam = 0.0
    for i, k in enumerate(kirpik):
        _, xs = np.where(k[:, :, 3] > 0)
        toplam += float(xs.mean()) + konumlar[i][1]
    return konumlar, skorlar, H, W, toplam / len(kirpik)


def pack(frames: list[np.ndarray], align_x: str = "correlate", align_y: str = "bottom",
         box: int | None = None, padding: int = 0
         ) -> tuple[np.ndarray, int, list[float]]:
    """Kareleri ortak kare kutuya hizalayip yatay sheet uretir."""
    kirpik = [tight(f) for f in frames]
    konumlar, skorlar, H, W, capa = align(frames, align_x, align_y)

    # Tum karelerin kapladigi ortak alan
    y0 = min(y for y, _ in konumlar)
    y1 = max(y + k.shape[0] for (y, _), k in zip(konumlar, kirpik))
    x0 = min(x for _, x in konumlar)
    x1 = max(x + k.shape[1] for (_, x), k in zip(konumlar, kirpik))

    # Kutu, sinir kutusunun degil CAPANIN etrafina kuruluyor. Sebebi motorda:
    # sola yurume flip ile uretiliyor ve aynalama canvas'in ortasina gore
    # yapiliyor (sprite-animator.js). Karakter kutuda ortali degilse her yon
    # degistirdiginde yana ziplar. Bir karede uzanan kol sinir kutusunu
    # asimetrik yaptigi icin "sinir kutusunu ortala" bunu garanti etmiyor —
    # olculen bir sette govde merkezi kutu ortasindan 3 piksel kaciyordu.
    # capa ondalikli oldugu icin gerekli de ondalikli cikiyor; tavana
    # yuvarlanmazsa kutu float kalir ve np.zeros patlar. Yukseklik terimi
    # cogu karakterde baskin oldugu icin bu ancak kolu genis uzanan
    # figurlerde tetikleniyordu -- yani tam olarak capa-etrafinda-kutu
    # mantiginin var olma sebebi olan durumda.
    yari = max(capa - x0, x1 - capa)
    gerekli = int(math.ceil(max(y1 - y0, 2 * yari) + 2 * padding))

    kutu = gerekli if box is None else box
    if kutu < gerekli:
        raise ValueError(f"--box {kutu} yetmiyor, en az {gerekli} olmali "
                         f"(capa etrafinda {2 * yari}, yukseklik {y1 - y0}, "
                         f"dolgu {padding})")

    # Ayna ekseni (kutu-1)/2, kutu/2 DEGIL. Motor flip'i
    # ctx.translate(canvas.width, 0) + ctx.scale(-1, 1) ile yapiyor
    # (sprite-animator.js); bu, x indeksini W-1-x'e goturur. kutu // 2
    # sadece tek sayi kutularda dogru sonucu veriyordu, cift kutularda
    # yarim piksellik sabit hata birakiyordu.
    #
    # Kaydirma TAM SAYI olmak zorunda: yarim piksel kaydirmak pixel art'i
    # yeniden ornekler. Dolayisiyla artik hata, hedefin en yakin tam sayiya
    # uzakligi kadar kaliyor -- tek kutuda frac(capa), cift kutuda
    # frac(capa - 0.5). --box verilirken pariteyi buna gore secmek artigi
    # 0.25 pikselin altina indiriyor.
    kaydir_x = int(round((kutu - 1) / 2.0 - capa))
    kaydir_y = (kutu - (y1 - y0) - padding) - y0 if align_y == "bottom" \
        else (kutu - (y1 - y0)) // 2 - y0

    sheet = np.zeros((kutu, kutu * len(frames), 4), dtype=np.uint8)
    for i, (k, (y, x)) in enumerate(zip(kirpik, konumlar)):
        _blit(sheet, k, y + kaydir_y, x + kaydir_x + i * kutu)
    return sheet, kutu, skorlar


def checker_background(h: int, w: int, cell: int = 8) -> np.ndarray:
    yy, xx = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    desen = ((yy // cell) + (xx // cell)) % 2
    out = np.zeros((h, w, 3), dtype=np.uint8)
    out[:] = np.where(desen[..., None] == 0,
                      np.array([60, 60, 66], np.uint8),
                      np.array([44, 44, 50], np.uint8))
    return out


def write_gif(sheet: np.ndarray, box: int, count: int, path: str,
              scale: int = 6, duration: int = 120) -> None:
    """Animasyonun gercekten titremedigini GOZLE dogrulamak icin GIF yazar."""
    kareler = []
    zemin = checker_background(box * scale, box * scale)
    for i in range(count):
        kare = sheet[:, i * box:(i + 1) * box]
        buyuk = np.array(Image.fromarray(kare).resize(
            (box * scale, box * scale), Image.NEAREST))
        alfa = buyuk[:, :, 3:4].astype(np.float32) / 255.0
        birlesik = (buyuk[:, :, :3] * alfa + zemin * (1 - alfa)).astype(np.uint8)
        kareler.append(Image.fromarray(birlesik))
    kareler[0].save(path, save_all=True, append_images=kareler[1:],
                    duration=duration, loop=0)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Tek tek cikarilmis animasyon karelerini hizalayip sprite sheet yapar.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("frames", nargs="+", help="Kare PNG'leri (sirayla)")
    parser.add_argument("-o", "--output", required=True, help="Cikti sprite sheet PNG")
    parser.add_argument("--align-x", choices=("correlate", "center"), default="correlate",
                        help="Yatay hizalama. correlate: referans kareyle ortusmeyi "
                             "en buyuten kayma (varsayilan). center: sinir kutusunun "
                             "ortasi — kol uzayinca merkez kayar, titreme uretebilir.")
    parser.add_argument("--align-y", choices=("bottom", "center"), default="bottom",
                        help="Dikey hizalama. bottom: ayak cizgisi (varsayilan). "
                             "center: zipla/dus gibi havada gecen animasyonlar icin.")
    parser.add_argument("--box", type=int, default=None,
                        help="Kare kutu boyutu. Varsayilan: gereken en kucuk kare.")
    parser.add_argument("--padding", type=int, default=0,
                        help="Kutu kenarinda birakilacak seffaf pay (varsayilan 0)")
    parser.add_argument("--gif", help="Onizleme GIF'i — animasyonu gozle dogrulamak icin")
    parser.add_argument("--gif-scale", type=int, default=6, help="GIF buyutme orani (varsayilan 6)")
    parser.add_argument("--duration", type=int, default=120,
                        help="Kare basina milisaniye; meta.json ve GIF icin (varsayilan 120)")
    parser.add_argument("--clip", default="walk_right", help="meta.json'daki klip adi")
    parser.add_argument("--min-overlap", type=float, default=0.55,
                        help="Bu ortusmenin altindaki kareler icin uyari verilir (varsayilan 0.55)")
    args = parser.parse_args(argv)

    try:
        frames = [load_frame(p) for p in args.frames]
    except (FileNotFoundError, OSError) as err:
        print(f"HATA: {err}", file=sys.stderr)
        return 1

    try:
        kirpik = [tight(f) for f in frames]
    except ValueError as err:
        print(f"HATA: {err}", file=sys.stderr)
        return 1

    yukseklikler = [k.shape[0] for k in kirpik]
    if max(yukseklikler) > 1.15 * min(yukseklikler):
        print(f"UYARI: kare yukseklikleri cok farkli ({min(yukseklikler)}-{max(yukseklikler)} "
              f"piksel). Kareler farkli native cozunurlukte uretilmis olabilir. Script "
              f"OLCEKLEMEZ — duzeltmek isterseniz kareleri ayni izgara yogunlugunda "
              f"yeniden urettirin.", file=sys.stderr)

    try:
        sheet, kutu, skorlar = pack(frames, args.align_x, args.align_y,
                                    args.box, args.padding)
    except ValueError as err:
        print(f"HATA: {err}", file=sys.stderr)
        return 1

    Image.fromarray(sheet).save(args.output)
    print(f"Kaydedildi: {args.output} ({sheet.shape[1]}x{sheet.shape[0]}) "
          f"— {len(frames)} kare x {kutu}x{kutu}")

    print("\nHizalama (referans: ilk kare):")
    for path, k, skor in zip(args.frames, kirpik, skorlar):
        isaret = "  <-- DUSUK, gozle kontrol edin" if skor < args.min_overlap else ""
        print(f"  {os.path.basename(path):32s} icerik {k.shape[1]:3d}x{k.shape[0]:<3d} "
              f"ortusme %{skor * 100:.0f}{isaret}")

    if args.gif:
        write_gif(sheet, kutu, len(frames), args.gif, args.gif_scale, args.duration)
        print(f"\nOnizleme GIF: {args.gif} — titreme varsa burada gorunur")

    blok = {
        "file": os.path.basename(args.output),
        "frameSize": kutu,
        "frameCount": len(frames),
        "frameDuration": args.duration,
    }
    print(f"\nmeta.json icin:\n  \"{args.clip}\": {json.dumps(blok)}")
    print(f"  \"nativeFrameSize\": {kutu},\n  \"displayScale\": 1")

    # Ekrandaki boyu belirleyen, kutu degil karakterin KENDI boyu. Kutu capanin
    # etrafina kare kuruldugu icin kolunu acan karakterde boydan buyuk cikiyor;
    # iki karakteri kutuya bakarak kiyaslamak yaniltir.
    boy = max(k.shape[0] for k in kirpik)
    print(f"\nKarakterin boyu {boy}px; displayScale 1 ile ekranda da {boy}px olacak.")
    print("Diger karakterlerle kiyaslamak icin: npm run check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
