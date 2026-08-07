#!/usr/bin/env python3
"""iki_gorunus.py testleri."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import iki_gorunus as ig  # noqa: E402

gecti = basarisiz = 0


def check(ad: str, kosul: bool, ayrinti: str = "") -> None:
    global gecti, basarisiz
    if kosul:
        gecti += 1
        print(f"  ok   {ad}")
    else:
        basarisiz += 1
        print(f"  HATA {ad}" + (f" — {ayrinti}" if ayrinti else ""))


def _tuval(h: int = 60, w: int = 120) -> np.ndarray:
    return np.zeros((h, w, 4), np.uint8)


def _figur(t: np.ndarray, x0: int, genislik: int, yukseklik: int,
           kafa: int, y0: int = 4) -> None:
    """Kafasi genis, govdesi dar basit bir figur — boyun en dar satir olur."""
    kx = x0 + (genislik - kafa) // 2
    t[y0:y0 + kafa, kx:kx + kafa] = (200, 150, 100, 255)          # kare kafa
    boyun = y0 + kafa
    t[boyun:boyun + 2, x0 + genislik // 2 - 1:x0 + genislik // 2 + 1] = (200, 150, 100, 255)
    t[boyun + 2:y0 + yukseklik, x0:x0 + genislik] = (60, 80, 140, 255)


def test_filigran_eleniyor():
    """REGRESYON: Gemini kosede parilti isareti birakiyor ve otomatik bolme onu
    UCUNCU bir kare sayiyor (olculdu: 9x9, 29 opak piksel; karakterler 3455 ve
    4215). Sayiya degil BOYUTA bakiliyor."""
    t = _tuval()
    _figur(t, 6, 20, 48, 14)
    _figur(t, 60, 18, 48, 14)
    t[54:57, 112:115] = (255, 255, 255, 255)      # filigran taklidi
    kutular = ig.kareleri_bul(t)
    check("filigran elendi, iki kare kaldi", len(kutular) == 2, f"{len(kutular)} kare")
    check("kareler soldan saga sirali", kutular[0][2] < kutular[1][2])


def test_iki_kareden_az_ise_durur():
    t = _tuval()
    _figur(t, 6, 20, 48, 14)
    try:
        ig.kareleri_bul(t)
        check("tek kare varken duruyor", False, "hata vermedi")
    except SystemExit:
        check("tek kare varken duruyor", True)


def test_olcum_kafa_oranini_buluyor():
    t = _tuval()
    _figur(t, 6, 20, 48, 14)
    kutular = ig.kareleri_bul(np.concatenate([t, t], axis=1))
    o = ig.olc(np.concatenate([t, t], axis=1), kutular[0])
    check("yukseklik olculdu", o["yukseklik"] == 48, f"{o['yukseklik']}")
    check("kafa orani makul", 20 <= o["kafa_orani"] <= 45, f"%{o['kafa_orani']:.0f}")


def test_olcek_kaymasi_yakalaniyor():
    """En sert olcut: iki sprite ayni nativeFrameSize'i paylasmak zorunda.
    Olculdu — ayri uretimde boy orani 1.12 cikiyordu, iki kareli duzende 0.99."""
    esit = ({"genislik": 40, "yukseklik": 100, "kafa": 30, "kafa_orani": 30.0},
            {"genislik": 30, "yukseklik": 100, "kafa": 30, "kafa_orani": 30.0})
    kaymis = ({"genislik": 40, "yukseklik": 100, "kafa": 30, "kafa_orani": 30.0},
              {"genislik": 30, "yukseklik": 112, "kafa": 34, "kafa_orani": 30.0})
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        a = ig.rapor(*esit)
        b = ig.rapor(*kaymis)
    check("esit boy kabul ediliyor", a)
    check("%12 boy kaymasi reddediliyor", not b)


def test_kafa_orani_kaymasi_yakalaniyor():
    """Olculdu: ayri uretimde kafa orani 6 puan kayiyordu (%42 -> %48)."""
    import contextlib, io
    iyi = ({"genislik": 40, "yukseklik": 100, "kafa": 42, "kafa_orani": 42.0},
           {"genislik": 34, "yukseklik": 100, "kafa": 43, "kafa_orani": 43.4})
    kotu = ({"genislik": 40, "yukseklik": 100, "kafa": 42, "kafa_orani": 42.0},
            {"genislik": 34, "yukseklik": 100, "kafa": 48, "kafa_orani": 48.0})
    with contextlib.redirect_stdout(io.StringIO()):
        a, b = ig.rapor(*iyi), ig.rapor(*kotu)
    check("+1.4 puan kabul", a)
    check("+6.0 puan reddedildi", not b)


def test_genislik_sert_kapi_degil():
    """Olculdu: dolgun bir karakterin iki uretiminde genislik orani 0.906 ve
    1.000 cikti, ama ikisi de dogru profildi. Genislik uyari, ret sebebi degil."""
    import contextlib, io
    dolgun = ({"genislik": 40, "yukseklik": 100, "kafa": 42, "kafa_orani": 42.0},
              {"genislik": 40, "yukseklik": 100, "kafa": 42, "kafa_orani": 42.0})
    with contextlib.redirect_stdout(io.StringIO()):
        sonuc = ig.rapor(*dolgun)
    check("genislik daralmasa da reddedilmiyor", sonuc)


if __name__ == "__main__":
    for t in (test_filigran_eleniyor, test_iki_kareden_az_ise_durur,
              test_olcum_kafa_oranini_buluyor, test_olcek_kaymasi_yakalaniyor,
              test_kafa_orani_kaymasi_yakalaniyor, test_genislik_sert_kapi_degil):
        print(f"\n{t.__name__}:")
        t()
    print("\n" + "=" * 50)
    print(f"{gecti} gecti, {basarisiz} basarisiz")
    sys.exit(1 if basarisiz else 0)
