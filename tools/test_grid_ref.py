#!/usr/bin/env python3
"""
grid_ref.py icin regresyon testleri.

Yontem: bilinen bir serit sheet uretiyoruz, izgara referansina ceviriyoruz,
sonra AYNI BORU HATTINDAN geri gecirip (cikar -> bol -> paketle) orijinalle
karsilastiriyoruz. Referans Gemini'ye gidecek, yani en azindan kendi
araclarimizin onu sorunsuz okuyabilmesi gerekiyor.

Calistirma:
    python3 tools/test_grid_ref.py
"""

import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grid_ref as gr  # noqa: E402
import pixelart_extract as px  # noqa: E402
import split_sheet as ss  # noqa: E402

PASSED, FAILED = 0, 0
ARAC = os.path.dirname(os.path.abspath(__file__))


def check(name: str, condition: bool, detail: str = ""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  HATA {name}" + (f" — {detail}" if detail else ""))


def serit_uret(kare: int = 8, kutu: int = 40, seed: int = 3) -> np.ndarray:
    """Yatay bir sprite sheet taklidi: her kare farkli, hepsi tabana oturuyor."""
    rng = np.random.default_rng(seed)
    palet = np.array([[26, 26, 30], [60, 58, 70], [120, 100, 80], [210, 170, 140],
                      [40, 90, 70], [180, 60, 60], [230, 230, 235]], np.uint8)
    serit = np.zeros((kutu, kutu * kare, 4), np.uint8)
    g0, g1 = kutu // 3, kutu - kutu // 3                          # govde sutunlari
    for i in range(kare):
        m = np.zeros((kutu, kutu), bool)
        m[kutu // 6:, g0:g1] = True                               # govde
        for _ in range(5):
            by = int(rng.integers(kutu // 6, kutu - 4))
            bw = int(rng.integers(3, 7))
            # Blok govdeye DEGMELI: kopuk bir blok karenin icinde bos bir sutun
            # bandi birakir ve split_sheet o kareyi ikiye boler (testin kendi
            # kusuruydu, aracin degil).
            bx = int(rng.integers(max(0, g0 - bw + 1), g1))
            m[by:by + int(rng.integers(3, 7)), bx:bx + bw] = True
        m[-1, kutu // 3:kutu - kutu // 3] = True                  # taban cizgisi
        ys, xs = np.where(m)
        kesit = serit[:, i * kutu:(i + 1) * kutu]
        kesit[ys, xs, :3] = palet[(xs * 3 + ys * 5 + i) % len(palet)]
        kesit[ys, xs, 3] = 255
    return serit


def test_duzen_secimi():
    """Sag alt hucre bos kalmali — Gemini filigrani oraya dusuyor."""
    for kare, beklenen_hucre in ((4, 6), (6, 8), (8, 9), (9, 12)):
        satir, sutun = gr.duzen_sec(kare, bos_birak=True)
        check(f"duzen {kare} kare: bos hucre var", satir * sutun > kare,
              f"{satir}x{sutun} = {satir * sutun}")
        check(f"duzen {kare} kare: tuval kareye yakin",
              max(satir, sutun) / min(satir, sutun) <= 2.0, f"{satir}x{sutun}")
    check("duzen 8 kare: 3x3 seciliyor", gr.duzen_sec(8, True) == (3, 3),
          f"{gr.duzen_sec(8, True)}")
    check("duzen: --no-reserve bos hucre zorlamiyor",
          gr.duzen_sec(9, bos_birak=False) == (3, 3), f"{gr.duzen_sec(9, False)}")


def test_bos_hucre_gercekten_bos():
    """Bos hucrede opak piksel olmamali; yoksa filigran icin yer kalmaz."""
    serit = serit_uret(kare=8, kutu=40)
    kareler = gr.kareleri_ayir(serit, 40)
    satir, sutun = gr.duzen_sec(8, True)
    im = gr.izgara_kur(kareler, satir, sutun, 40, olcek=2, bosluk=6, pay=8,
                       tonlar=((255, 0, 255), (192, 0, 192)), dama_blok=8)
    a = np.array(im.convert("RGB")).astype(int)
    magenta = (a[:, :, 0] > 120) & (a[:, :, 2] > 120) & (a[:, :, 1] < 90)
    h, w = magenta.shape
    # sag alt hucrenin ic bolgesi tamamen arka plan olmali
    sag_alt = magenta[int(h * 0.72):int(h * 0.95), int(w * 0.72):int(w * 0.95)]
    check("bos hucre: sag alt tamamen arka plan", sag_alt.all(),
          f"{(~sag_alt).sum()} opak piksel var")


def test_dis_kenar_payi():
    """Karakter dis kenara degmemeli: dama tonlari o seritten ogreniliyor."""
    serit = serit_uret(kare=6, kutu=40)
    kareler = gr.kareleri_ayir(serit, 40)
    satir, sutun = gr.duzen_sec(6, True)
    im = gr.izgara_kur(kareler, satir, sutun, 40, olcek=3, bosluk=6, pay=8,
                       tonlar=((255, 0, 255), (192, 0, 192)), dama_blok=8)
    a = np.array(im.convert("RGB")).astype(int)
    magenta = (a[:, :, 0] > 120) & (a[:, :, 2] > 120) & (a[:, :, 1] < 90)
    for ad, dilim in (("ust", magenta[:8, :]), ("alt", magenta[-8:, :]),
                      ("sol", magenta[:, :8]), ("sag", magenta[:, -8:])):
        check(f"kenar payi: {ad} kenar temiz", dilim.all(),
              f"{(~dilim).sum()} karakter pikseli kenara degiyor")


def test_dama_blok_izgarayi_bozmuyor():
    """OLCULEN REGRESYON: dama karesi blogun 2 ya da 3 kati oldugunda izgara
    tespiti damanin periyoduna kilitleniyor ve karakteri YARI cozunurlukte
    cikariyor (blok 7px iken 14 buluyor, uyum %100'den %16'ya dusuyor).
    Varsayilan bu tuzaga dusmemeli."""
    serit = serit_uret(kare=8, kutu=40)
    kareler = gr.kareleri_ayir(serit, 40)
    satir, sutun = gr.duzen_sec(8, True)
    olcek, bosluk, pay = 6, 6, 8
    nat_w = pay * 2 + sutun * 40 + (sutun - 1) * bosluk

    im = gr.izgara_kur(kareler, satir, sutun, 40, olcek, bosluk, pay,
                       ((255, 0, 255), (192, 0, 192)), dama_blok=8)   # varsayilan
    arr = np.array(im.convert("RGB"))
    gx, gy = px.detect_grid(arr)
    check("dama blok 8: periyot dogru", abs(gx.period - olcek) < 0.5,
          f"{gx.period:.2f} bulundu, {olcek} olmaliydi")
    check("dama blok 8: native genislik dogru", gx.count == nat_w,
          f"{gx.count} bulundu, {nat_w} olmaliydi")
    check("dama blok 8: izgara uyumu yuksek", min(gx.quality, gy.quality) > 0.5,
          f"X={gx.quality:.0%} Y={gy.quality:.0%}")


def test_borudan_geri_geciyor():
    """Uretilen referans kendi boru hattimizdan gecip kareleri geri vermeli."""
    kutu, kare = 40, 8
    serit = serit_uret(kare=kare, kutu=kutu)
    with tempfile.TemporaryDirectory() as tmp:
        kaynak = os.path.join(tmp, "serit.png")
        ref = os.path.join(tmp, "ref.png")
        nat = os.path.join(tmp, "nat.png")
        Image.fromarray(serit).save(kaynak)

        r = subprocess.run([sys.executable, os.path.join(ARAC, "grid_ref.py"),
                            kaynak, "-o", ref], capture_output=True, text=True)
        check("boru hatti: grid_ref calisti", r.returncode == 0,
              (r.stderr or "").strip()[-200:])
        if r.returncode != 0:
            return

        px.extract(ref, nat, no_crop=True, cleanup=False)
        geri = np.array(Image.open(nat).convert("RGBA"))
        kutular, satir, sutun = ss.detect_frames(geri, min_gap=1)
        check("boru hatti: kare sayisi korundu", len(kutular) == kare,
              f"{len(kutular)} kare bulundu, {kare} olmaliydi")
        check("boru hatti: izgara duzeni 3x3", (satir, sutun) == (3, 3),
              f"{satir}x{sutun}")


def test_seffaf_olmayan_girdi_reddediliyor():
    """Ham Gemini ciktisi verilirse anlamli hata vermeli."""
    opak = np.zeros((20, 60, 4), np.uint8)
    opak[:, :, 3] = 255
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "o.png"), os.path.join(tmp, "c.png")
        Image.fromarray(opak).save(src)
        r = subprocess.run([sys.executable, os.path.join(ARAC, "grid_ref.py"),
                            src, "-o", dst], capture_output=True, text=True)
        check("seffaf olmayan girdi: hata kodu", r.returncode != 0)
        check("seffaf olmayan girdi: mesaj yol gosteriyor",
              "pack_sheet" in r.stderr, r.stderr.strip()[:120])


if __name__ == "__main__":
    import contextlib
    import io

    tests = [
        test_duzen_secimi,
        test_bos_hucre_gercekten_bos,
        test_dis_kenar_payi,
        test_dama_blok_izgarayi_bozmuyor,
        test_borudan_geri_geciyor,
        test_seffaf_olmayan_girdi_reddediliyor,
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
