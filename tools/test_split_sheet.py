#!/usr/bin/env python3
"""
split_sheet.py icin regresyon testleri.

En onemlisi test_uctan_uca_titremiyor: bol -> hizala -> birlestir zincirinin
sonunda kareler BIREBIR ayni konumda olmali. Zincirin amaci zaten bu.

Calistirma:
    python3 tools/test_split_sheet.py
"""

import os
import sys
import tempfile

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import split_sheet as ss  # noqa: E402
import pack_sheet as ps  # noqa: E402


PASSED, FAILED = 0, 0


def check(name: str, condition: bool, detail: str = ""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  HATA {name}" + (f" — {detail}" if detail else ""))


def karakter(bacak: int = 0, ton: int = 0) -> np.ndarray:
    a = np.zeros((20, 16, 4), np.uint8)
    a[2:6, 6:10] = (240, 200, 170, 255)
    a[6:14, 5:11] = (60, 70 + ton, 120, 255)
    a[14:20, 5 - bacak:7 - bacak] = (40, 40, 45, 255)
    a[14:20, 9 + bacak:11 + bacak] = (40, 40, 45, 255)
    return a


def sheet_yap(kareler: list[np.ndarray], satir: int, sutun: int,
              hucre_w: int = 26, hucre_h: int = 30,
              kaydir=None) -> np.ndarray:
    """Kareleri bir sheet'e dizer. `kaydir` her kare icin (dy, dx) verirse
    Gemini'nin kareleri hucre icinde farkli yerlere koymasi taklit edilir."""
    sheet = np.zeros((satir * hucre_h, sutun * hucre_w, 4), np.uint8)
    for i, k in enumerate(kareler):
        r, c = divmod(i, sutun)
        dy, dx = kaydir[i] if kaydir else (0, 0)
        y = r * hucre_h + (hucre_h - k.shape[0]) // 2 + dy
        x = c * hucre_w + (hucre_w - k.shape[1]) // 2 + dx
        sheet[y:y + k.shape[0], x:x + k.shape[1]] = k
    return sheet


def test_tek_sira():
    kareler = [karakter(b) for b in (0, 1, 2, 1)]
    sheet = sheet_yap(kareler, 1, 4)
    kutular, satir, sutun = ss.detect_frames(sheet)
    check("tek sira: 4 kare bulundu", len(kutular) == 4, f"{len(kutular)}")
    check("tek sira: duzen 1x4", (satir, sutun) == (1, 4), f"{satir}x{sutun}")


def test_grid_duzeni():
    kareler = [karakter(i % 3) for i in range(6)]
    sheet = sheet_yap(kareler, 2, 3)
    kutular, satir, sutun = ss.detect_frames(sheet)
    check("grid: 6 kare bulundu", len(kutular) == 6, f"{len(kutular)}")
    check("grid: duzen 2x3", (satir, sutun) == (2, 3), f"{satir}x{sutun}")


def test_okuma_sirasi():
    """Kareler ustten alta, soldan saga sirali gelmeli — animasyon sirasi bu."""
    kareler = [karakter(0, ton=i * 20) for i in range(6)]
    sheet = sheet_yap(kareler, 2, 3)
    kutular, _, _ = ss.detect_frames(sheet)
    tonlar = []
    for y0, y1, x0, x1 in kutular:
        k = sheet[y0:y1, x0:x1]
        govde = k[k.shape[0] // 2]
        tonlar.append(int(govde[govde[:, 3] > 0][:, 1].max()))
    check("sira: kareler okuma sirasinda", tonlar == sorted(tonlar), f"{tonlar}")


def test_kare_icerigi_bozulmuyor():
    kareler = [karakter(b) for b in (0, 2)]
    sheet = sheet_yap(kareler, 1, 2)
    kutular, _, _ = ss.detect_frames(sheet)
    for kutu, orijinal in zip(kutular, kareler):
        y0, y1, x0, x1 = kutu
        kesilen = sheet[y0:y1, x0:x1]
        beklenen = ps.tight(orijinal)
        check(f"icerik: {beklenen.shape[1]}x{beklenen.shape[0]} kare birebir kesildi",
              np.array_equal(kesilen, beklenen),
              f"kesilen {kesilen.shape[1]}x{kesilen.shape[0]}")


def test_esit_bolme():
    """Kareler birbirine DEGIYORSA otomatik ayirma calismaz — aralarinda bos
    sutun kalmadigi icin tek kare gorunur. Esit bolme son care olarak devreye
    girer; tam ortalamasi gerekmez, pack_sheet zaten yeniden hizaliyor."""
    bitisik = np.hstack([ps.tight(karakter(0)) for _ in range(3)])
    kutular, _, _ = ss.detect_frames(bitisik)
    check("esit bolme: bitisik kareler otomatik ayrilamiyor (beklenen)",
          len(kutular) == 1, f"{len(kutular)} kare bulundu")

    esit = ss.uniform_frames(bitisik, 1, 3)
    check("esit bolme: 3 hucreye bolundu", len(esit) == 3, f"{len(esit)}")
    genislikler = {x1 - x0 for _, _, x0, x1 in esit}
    check("esit bolme: hucreler esit genislikte", len(genislikler) == 1, f"{genislikler}")


def test_min_gap():
    """min_gap = ayirici sayilan EN KISA bos serit. 1 piksellik bosluga
    duyarli olmak varsayilan; karakterin icinde bos sutun kalabilen nadir
    durumlarda deger buyutulur."""
    a = np.zeros((10, 9, 4), np.uint8)
    a[2:8, 0:4] = (100, 100, 100, 255)
    a[2:8, 5:9] = (100, 100, 100, 255)          # ortada 1 piksellik bos sutun
    check("min-gap: varsayilanda 1 piksellik bosluk ayiriyor",
          len(ss.detect_frames(a, min_gap=1)[0]) == 2, f"{len(ss.detect_frames(a, 1)[0])}")
    check("min-gap: 2 verilince ayirmiyor",
          len(ss.detect_frames(a, min_gap=2)[0]) == 1, f"{len(ss.detect_frames(a, 2)[0])}")


def test_opak_girdi_reddediliyor():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "opak.png")
        Image.fromarray(np.full((20, 20, 4), 255, np.uint8)).save(p)
        kod = ss.main([p, "-o", os.path.join(tmp, "out")])
        check("opak girdi: anlamli hatayla reddedildi", kod == 1, f"cikis kodu {kod}")


def test_frames_dogrulamasi():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "sheet.png")
        Image.fromarray(sheet_yap([karakter(b) for b in (0, 1, 2)], 1, 3)).save(p)
        out = os.path.join(tmp, "kareler")
        check("--frames: dogru sayida gecti",
              ss.main([p, "-o", out, "--frames", "3"]) == 0)
        check("--frames: yanlis sayida reddedildi",
              ss.main([p, "-o", out, "--frames", "5"]) == 1)


def test_dosya_sirasi_glob_uyumlu():
    """10+ kare olunca kare_1.png ... kare_10.png yanlis siralanir; sifir dolgusu sart."""
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "sheet.png")
        Image.fromarray(sheet_yap([karakter(i % 3) for i in range(12)], 1, 12)).save(p)
        out = os.path.join(tmp, "kareler")
        ss.main([p, "-o", out])
        adlar = sorted(os.listdir(out))
        check("dosya sirasi: alfabetik sira = kare sirasi",
              adlar == [f"kare_{i:02d}.png" for i in range(1, 13)], f"{adlar[:3]}")


def test_uctan_uca_titremiyor():
    """ASIL AMAC: Gemini kareleri hucre icinde farkli yerlere koymus olsa bile
    bol -> hizala zincirinin sonunda kareler birebir ayni konumda olmali."""
    kareler = [karakter(0) for _ in range(4)]
    kaydir = [(0, 0), (-3, 4), (2, -5), (-1, 2)]        # her kare baska yerde
    sheet = sheet_yap(kareler, 1, 4, kaydir=kaydir)

    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "sheet.png")
        Image.fromarray(sheet).save(p)
        out = os.path.join(tmp, "kareler")
        check("uctan uca: bolme basarili", ss.main([p, "-o", out, "--frames", "4"]) == 0)
        yollar = sorted(os.path.join(out, f) for f in os.listdir(out))
        paketli, kutu, skorlar = ps.pack([ps.load_frame(y) for y in yollar])

    hucre = [paketli[:, i * kutu:(i + 1) * kutu] for i in range(4)]
    check("uctan uca: tum kareler birebir ayni konumda",
          all(np.array_equal(hucre[0], h) for h in hucre[1:]),
          "kareler arasinda fark var — animasyon titrerdi")
    check("uctan uca: ortusme tam", all(s > 0.99 for s in skorlar), f"{skorlar}")


if __name__ == "__main__":
    import contextlib
    import io

    tests = [
        test_tek_sira,
        test_grid_duzeni,
        test_okuma_sirasi,
        test_kare_icerigi_bozulmuyor,
        test_esit_bolme,
        test_min_gap,
        test_opak_girdi_reddediliyor,
        test_frames_dogrulamasi,
        test_dosya_sirasi_glob_uyumlu,
        test_uctan_uca_titremiyor,
    ]
    for fn in tests:
        print(f"\n{fn.__name__}:")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                fn()
            except Exception as err:            # noqa: BLE001
                FAILED += 1
                print(f"  ISTISNA {fn.__name__}: {err}")
        sys.stdout.write(buf.getvalue())

    print(f"\n{'=' * 50}\n{PASSED} gecti, {FAILED} basarisiz")
    sys.exit(1 if FAILED else 0)
