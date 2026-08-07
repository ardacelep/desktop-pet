#!/usr/bin/env python3
"""
Egitim verisi KAPILARI icin testler (chen_to_pixelart + pixellab_generate).

Kapilar bu boru hattinin en kritik parcasi: 4000 ornegi gozle denetlemek
mumkun degil, o yuzden bozuk ornegi eleme isi tumuyle bu olcutlere kalmis.
Bir kapi sessizce gevserse veri seti bozulur ve bunu ancak egitim sonunda,
kotu bir skor olarak goruruz — yani en pahali yerde.

Zemin ayiklama ozellikle kirilgan: Chen'in goruntulerinde kenar seridi
beyazlik orani ort 0.72 ama min 0.00, yani ayiklama her goruntude
tutmuyor. Tutmadigini FARK ETMEK zorundayiz.

Hicbir test API'ye gitmez.

Calistirma:
    python3 tools/test_veri_kapilari.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skeleton as sk  # noqa: E402

PASSED, FAILED = 0, 0


def check(name: str, condition: bool, detail: str = ""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  HATA {name}" + (f" — {detail}" if detail else ""))


def figur(tuval=120, zemin=(255, 255, 255), govde=(180, 90, 70)):
    """Duz zemin uzerinde basit bir figur."""
    im = np.zeros((tuval, tuval, 3), np.uint8)
    im[:, :] = zemin
    im[14:40, 48:72] = govde                 # kafa
    im[40:80, 42:78] = govde                 # govde
    im[80:110, 46:56] = govde                # bacaklar
    im[80:110, 64:74] = govde
    return im


def kp_figur(tuval=120):
    """Figurun uzerinde duran makul eklemler (normalize)."""
    n = {}
    for l in sk.LABELS:
        n[l] = [60 / tuval, 60 / tuval]
    n["NOSE"] = [60 / tuval, 26 / tuval]
    n["RIGHT LEG"] = [51 / tuval, 105 / tuval]
    n["LEFT LEG"] = [69 / tuval, 105 / tuval]
    return n


# ---------------------------------------------------------------------------
# Zemin ayiklama
# ---------------------------------------------------------------------------

def test_zemin_duz_arka_planda_ayrisiyor():
    import chen_to_pixelart as c2p
    im = figur()
    m = c2p.zemini_ayikla(im)
    check("zemin: karakter bulundu", m.sum() > 500, f"{int(m.sum())}px")
    kenar = np.concatenate([m[0], m[-1], m[:, 0], m[:, -1]])
    check("zemin: kenar seridi bosaldi", kenar.mean() < 0.05,
          f"kenar doluluk {kenar.mean():.2f}")
    check("zemin: govde korundu", bool(m[60, 60]))
    check("zemin: kose atildi", not bool(m[0, 0]))


def test_zemin_ayrismayan_yakalaniyor():
    """ASIL TEST: zemin ayiklanamadiginda bunun FARK EDILMESI.

    Gurultulu/desenli arka planda tasma-doldurma yayilamaz ve maske neredeyse
    tum goruntuyu kapsar. Bu sessizce gecerse egitim setine arka planiyla
    birlikte ornekler girer; model karakteri degil cerceveyi ogrenir."""
    rng = np.random.default_rng(3)
    im = figur()
    # kenarlara gurultu: tasma-doldurma yayilamaz
    gurultu = rng.integers(0, 255, (120, 120, 3), dtype=np.uint8)
    kenar = np.zeros((120, 120), bool)
    kenar[:6], kenar[-6:], kenar[:, :6], kenar[:, -6:] = True, True, True, True
    im[kenar] = gurultu[kenar]

    import chen_to_pixelart as c2p
    m = c2p.zemini_ayikla(im)
    kenar_doluluk = float(np.concatenate([m[0], m[-1], m[:, 0], m[:, -1]]).mean())
    check("zemin: ayrismadigi olculebiliyor", kenar_doluluk > 0.25,
          f"kenar doluluk {kenar_doluluk:.2f} — kapi bunu elemeli")


def test_zemin_kapisi_esigi_dogru_tarafta():
    """Kapi esigi (0.25) temiz ve kirli ornegi AYIRMALI."""
    import chen_to_pixelart as c2p

    def kenar_dolulugu(maske):
        return float(np.concatenate([maske[0], maske[-1],
                                     maske[:, 0], maske[:, -1]]).mean())

    temiz = kenar_dolulugu(c2p.zemini_ayikla(figur()))

    rng = np.random.default_rng(1)
    kirli_im = figur()
    kenar = np.zeros((120, 120), bool)
    kenar[:6], kenar[-6:], kenar[:, :6], kenar[:, -6:] = True, True, True, True
    kirli_im[kenar] = rng.integers(0, 255, (120, 120, 3), dtype=np.uint8)[kenar]
    kirli = kenar_dolulugu(c2p.zemini_ayikla(kirli_im))
    check("zemin: esik iki tarafi ayiriyor", temiz < 0.25 < kirli,
          f"temiz {temiz:.2f} / kirli {kirli:.2f}")


# ---------------------------------------------------------------------------
# Kalite kapilari
# ---------------------------------------------------------------------------

def test_kapilar_iyi_ornegi_geciriyor():
    import chen_to_pixelart as c2p
    tuval = 128
    t = np.zeros((tuval, tuval, 4), np.uint8)
    t[20:110, 50:78, :3] = (150, 90, 60)
    t[20:45, 55:73, :3] = (230, 190, 170)      # kafa
    t[45:70, 50:78, :3] = (60, 120, 90)        # govde
    t[95:110, 50:78, :3] = (40, 40, 50)        # ayakkabi
    t[20:110, 50:78, 3] = 255
    kp = {l: [0.5, 0.5] for l in sk.LABELS}
    maske = t[:, :, 3] > 0
    kabul, olcum = c2p.kapilar(t, kp, maske)
    check("kapi: temiz ornek gecti", kabul, str(olcum))
    check("kapi: iou yuksek", olcum["iou"] > 0.9, str(olcum.get("iou")))


def test_kapilar_kacak_eklemi_eliyor():
    """Eklemler karakterin disindaysa donusumde hata var demektir."""
    import chen_to_pixelart as c2p
    tuval = 128
    t = np.zeros((tuval, tuval, 4), np.uint8)
    t[20:110, 50:78, :3] = (150, 90, 60)
    t[20:110, 50:78, 3] = 255
    kp = {l: [0.05, 0.05] for l in sk.LABELS}      # hepsi kosede, siluet disi
    kabul, olcum = c2p.kapilar(t, kp, t[:, :, 3] > 0)
    check("kapi: kacak eklem elendi", not kabul, str(olcum))
    check("kapi: sebep eklem", olcum.get("sebep") == "eklem", str(olcum))


def test_kapilar_bos_ve_dolu_tuvali_eliyor():
    import chen_to_pixelart as c2p
    tuval = 128
    kp = {l: [0.5, 0.5] for l in sk.LABELS}

    dolu = np.zeros((tuval, tuval, 4), np.uint8)
    dolu[:, :, :3] = (100, 100, 100)
    dolu[:, :, 3] = 255
    kabul, olcum = c2p.kapilar(dolu, kp, dolu[:, :, 3] > 0)
    check("kapi: tumuyle dolu tuval elendi", not kabul, str(olcum))

    az = np.zeros((tuval, tuval, 4), np.uint8)
    az[60:64, 60:64, :3] = (100, 100, 100)
    az[60:64, 60:64, 3] = 255
    kabul2, olcum2 = c2p.kapilar(az, kp, az[:, :, 3] > 0)
    check("kapi: cok kucuk figur elendi", not kabul2, str(olcum2))


# ---------------------------------------------------------------------------
# Uretim kapilari
# ---------------------------------------------------------------------------

def yuzlu_figur(b=128):
    """Kafasinda IC AYRINTI olan figur — gorunur yuz taklidi."""
    im = np.zeros((b, b, 4), np.uint8)
    im[10:118, 45:80, :3] = (150, 90, 60)
    im[10:118, 45:80, 3] = 255
    rng = np.random.default_rng(0)
    for _ in range(30):                       # goz/agiz/burun yerine adaciklar
        y, x = int(rng.integers(14, 40)), int(rng.integers(48, 76))
        im[y:y + 2, x:x + 2, :3] = rng.integers(0, 255, 3)
    return im


def test_yuz_gorunurlugu_kapisi():
    """Yuz kapisi CALISIYOR ama VARSAYILAN OLARAK KAPALI.

    Sirti donuk / kapusonlu figurleri gercekten ayirt ediyor: olcut kafadaki
    IC AYRINTI sayisi — gercek bes karakterimizde 50-87, bozuk figurlerde 1-9.
    ("sclera var mi" olcutu OLAMAZDI: faküs'un de sclera'si yok ve o tam da
    tutmak istedigimiz karakter.)

    Ama kapali, cunku olculdu (dort holdout, son epok): kapiyi acmak
    60->53 karakterde hatayi 4.35 -> 4.50px, 94->76'da 4.33 -> 4.37px yapti.
    Yani eledigi veri gurultusunden daha degerli. Test ikisini birden
    korumali — ayirt etme yetisini VE varsayilanin kapali oldugunu."""
    import pixellab_generate as pg
    b = 128
    duz = np.zeros((b, b, 4), np.uint8)       # kapusonlu/arkadan gorunum taklidi
    duz[10:118, 45:80, :3] = (60, 60, 70)
    duz[10:118, 45:80, 3] = 255

    check("yuz kapisi: varsayilan KAPALI, duz kutle geciyor",
          pg.kabul_edilebilir(duz)[0])

    check("yuz kapisi acikken ayrintili kafa gecti",
          pg.kabul_edilebilir(yuzlu_figur(b), yuz_kapisi=True)[0])
    tamam, sebep = pg.kabul_edilebilir(duz, yuz_kapisi=True)
    check("yuz kapisi acikken duz kutle elendi",
          not tamam and sebep == "yuz gorunmuyor", sebep)

    check("yuz kapisi: ayrinti sayisi ayirt ediyor",
          pg.kafa_ayrintisi(yuzlu_figur(b)) > pg.KAFA_AYRINTI_ESIGI > pg.kafa_ayrintisi(duz),
          f"{pg.kafa_ayrintisi(yuzlu_figur(b))} vs {pg.kafa_ayrintisi(duz)}")


def test_uretim_kapisi():
    """Uretilen gorsel ETIKETLEMEDEN once eleniyor — etiketleme ayrica
    ucretli, bozuk ornege para harcamanin anlami yok."""
    import pixellab_generate as pg
    b = 128

    iyi = yuzlu_figur(b)
    tamam, sebep = pg.kabul_edilebilir(iyi)
    check("uretim: saglam gorsel gecti", tamam, sebep)

    bos = np.zeros((b, b, 4), np.uint8)
    bos[60:63, 60:63, 3] = 255
    check("uretim: bos gorsel elendi", not pg.kabul_edilebilir(bos)[0])

    dolu = np.zeros((b, b, 4), np.uint8)
    dolu[:, :, 3] = 255
    tamam3, sebep3 = pg.kabul_edilebilir(dolu)
    check("uretim: zemin ayrilmamis elendi",
          not tamam3 and sebep3 == "zemin ayrilmamis", sebep3)

    # Genis ama KISA: doluluk kapisini gecmeli ki yukseklik kapisi olculsun
    kisa = np.zeros((b, b, 4), np.uint8)
    kisa[50:85, 20:110, :3] = (150, 90, 60)
    kisa[50:85, 20:110, 3] = 255
    tamam4, sebep4 = pg.kabul_edilebilir(kisa)
    check("uretim: kisa figur elendi", not tamam4 and sebep4 == "figur kisa kalmis",
          sebep4)


def test_etiket_esleme_tam():
    """Chen'in 17 noktasi + turetilen NECK = bizim 18 etiket, eksiksiz."""
    import chen_to_pixelart as c2p
    hedef = set(c2p.ESLEME.values()) | {"NECK"}
    check("esleme: 18 etiketin hepsi kapsandi", hedef == set(sk.LABELS),
          f"eksik {set(sk.LABELS) - hedef}, fazla {hedef - set(sk.LABELS)}")
    check("esleme: sol/sag karismamis",
          c2p.ESLEME["shoulder_right"] == "RIGHT SHOULDER"
          and c2p.ESLEME["ankle_left"] == "LEFT LEG")


def main():
    testler = [
        test_zemin_duz_arka_planda_ayrisiyor,
        test_zemin_ayrismayan_yakalaniyor,
        test_zemin_kapisi_esigi_dogru_tarafta,
        test_kapilar_iyi_ornegi_geciriyor,
        test_kapilar_kacak_eklemi_eliyor,
        test_kapilar_bos_ve_dolu_tuvali_eliyor,
        test_yuz_gorunurlugu_kapisi,
        test_uretim_kapisi,
        test_etiket_esleme_tam,
    ]
    for t in testler:
        print(f"\n{t.__name__}:")
        t()
    print("\n" + "=" * 50)
    print(f"{PASSED} gecti, {FAILED} basarisiz")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
