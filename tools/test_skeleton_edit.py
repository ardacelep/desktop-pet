#!/usr/bin/env python3
"""skeleton_edit.py testleri — model secimi ve olcek uyarlamasi."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skeleton_edit as se  # noqa: E402

gecti = basarisiz = 0


def check(ad: str, kosul: bool, ayrinti: str = "") -> None:
    global gecti, basarisiz
    if kosul:
        gecti += 1
        print(f"  ok   {ad}")
    else:
        basarisiz += 1
        print(f"  HATA {ad}" + (f" — {ayrinti}" if ayrinti else ""))


def _sprite(boy: int, tuval: int | None = None) -> np.ndarray:
    n = tuval or boy + 4
    a = np.zeros((n, n, 4), np.uint8)
    y0 = (n - boy) // 2
    a[y0:y0 + boy, n // 2 - 3:n // 2 + 3] = (200, 150, 100, 255)
    return a


def test_kucuk_sprite_buyutuluyor():
    """REGRESYON: `kanvasa_yerlestir` bilerek BUYUTMUYOR — egitim verisi
    uretirken dogru karar, cunku pixel art'i buyutmek sahte ara tonlar
    uretir. Ama cikarimda tam tersi gerekiyor: model karakteri egitimde
    gordugu boyda gormeli.

    Olculdu (ael idle karesi, farkli boylarda, yayinlanan modelle):
        21px sprite -> 29.18px hata   |  duzeltmeden sonra 6.13px
        34px        ->  9.01px        |                   3.52px
        43px        ->  6.94px        |                   1.88px
        87px        ->  0.52px        |                   0.52px  (kat 1)
    Egitim verisinde siluet yuksekligi medyani 122px; 50 pikselin altindaki
    sprite dagilimin tamamen disinda kaliyor. Pixel art genelde 32x32 ya da
    48x48 oldugu icin bu olagan durum."""
    t = se._Tahminci(None)                       # model gerekmiyor, sadece kat
    check("20px siluet buyutuluyor", t._buyutme_kati(_sprite(20)) == 5,
          f"kat {t._buyutme_kati(_sprite(20))}")
    check("33px siluet buyutuluyor", t._buyutme_kati(_sprite(33)) == 3,
          f"kat {t._buyutme_kati(_sprite(33))}")
    check("84px siluet oldugu gibi birakiliyor",
          t._buyutme_kati(_sprite(84)) == 1, f"kat {t._buyutme_kati(_sprite(84))}")
    check("126px siluet buyutulmuyor",
          t._buyutme_kati(_sprite(126, 140)) == 1)


def test_hedef_asilmiyor():
    """ASAGI yuvarlaniyor, yakina degil. Olculdu: 63px siluette `round` 2 kat
    secip 126px'e cikariyor ve hata 2.04'ten 2.90'a yukseliyor; asagi
    yuvarlayinca 1 katta kalip 2.04'te kaliyor."""
    t = se._Tahminci(None)
    for boy in range(12, 130, 7):
        kat = t._buyutme_kati(_sprite(boy, boy + 6))
        if kat == 1:
            # Zaten hedeften buyuk olan siluete dokunulmuyor; kucultme
            # `kanvasa_yerlestir`in isi, burasi yalnizca BUYUTUYOR.
            check(f"{boy}px: kat 1, dokunulmuyor", True)
            continue
        check(f"{boy}px: buyutme hedefi ({t.HEDEF_SILUET}) asmiyor",
              boy * kat <= t.HEDEF_SILUET, f"kat {kat} -> {boy*kat}px")


def test_bos_kare_cokmuyor():
    t = se._Tahminci(None)
    check("tumuyle seffaf kare kat 1 veriyor",
          t._buyutme_kati(np.zeros((32, 32, 4), np.uint8)) == 1)


def test_model_yoksa_sezgisele_dusuyor():
    t = se._Tahminci(None)
    check("checkpoint yokken sezgisel", t.ad == "sezgisel")
    t2 = se._Tahminci("/olmayan/yol/model.pt")
    check("bozuk yol sezgisele dusuyor", t2.ad == "sezgisel")


def test_model_secimi_iki_yere_bakiyor():
    """models/ (Git LFS ile gelir) ve _data/modeller/ (yerel egitim ciktisi)
    birlikte taranmali. Yalnizca _data/ aransaydi klonlayan kisi LFS ile
    modeli almis olmasina ragmen sezgisele duserdi."""
    import inspect
    kaynak = inspect.getsource(se.en_guncel_model)
    check("models/ taraniyor", '"models"' in kaynak)
    check("_data/modeller/ taraniyor", '"modeller"' in kaynak)
    check("yalnizca uretim modelleri seciliyor", 'get("uretim")' in kaynak)


if __name__ == "__main__":
    for t in (test_kucuk_sprite_buyutuluyor, test_hedef_asilmiyor,
              test_bos_kare_cokmuyor, test_model_yoksa_sezgisele_dusuyor,
              test_model_secimi_iki_yere_bakiyor):
        print(f"\n{t.__name__}:")
        t()
    print("\n" + "=" * 50)
    print(f"{gecti} gecti, {basarisiz} basarisiz")
    sys.exit(1 if basarisiz else 0)
