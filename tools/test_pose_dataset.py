#!/usr/bin/env python3
"""
pose_dataset.py icin testler.

Buradaki asil risk SESSIZ: artirma matematigi yanlis olursa hicbir sey hata
vermez, sadece model bozuk etiketlerle egitilir ve bunu ancak egitim sonunda
fark ederiz. O yuzden donusumlerin etiketi DOGRU tasidigi tek tek olculuyor.

Etiketleme ucretli oldugu icin hicbir test API'ye gitmez.

Calistirma:
    python3 tools/test_pose_dataset.py
"""

import json
import os
import sys
import tempfile

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pose_dataset as pd  # noqa: E402
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


def sahne(h=40, w=24, tuval=90):
    """Asimetrik bir figur: sag tarafta isaret var, ayna testini anlamli kilar."""
    im = np.zeros((tuval, tuval, 4), np.uint8)
    y0, x0 = 20, 30
    im[y0:y0 + h, x0:x0 + w] = (200, 100, 80, 255)
    im[y0 + 2:y0 + 8, x0 + w - 6:x0 + w - 2] = (40, 220, 40, 255)   # sag omuz isareti
    return im


def kp_ornek():
    """Bilinen, asimetrik bir keypoint kumesi (normalize)."""
    rng = np.random.default_rng(5)
    return {l: [float(0.3 + 0.4 * rng.random()), float(0.2 + 0.6 * rng.random())]
            for l in sk.LABELS}


def test_kanvasa_yerlestirme():
    im = sahne()
    t, olcek, _, _ = pd.kanvasa_yerlestir(im, 128)
    check("tuval: istenen boyut", t.shape == (128, 128, 4), str(t.shape))
    check("tuval: buyutme YOK", olcek <= 1.0, f"olcek={olcek}")

    ys, xs = np.where(t[:, :, 3] > 0)
    my, mx = (ys.min() + ys.max()) / 2, (xs.min() + xs.max()) / 2
    check("tuval: ortalanmis", abs(my - 63.5) <= 1.5 and abs(mx - 63.5) <= 1.5,
          f"merkez ({mx:.1f},{my:.1f})")

    # Icerik korunmali: opak piksel sayisi degismemeli (kucultme olmadiginda)
    check("tuval: icerik korundu",
          int((t[:, :, 3] > 0).sum()) == int((im[:, :, 3] > 0).sum()),
          f"{int((t[:,:,3]>0).sum())} vs {int((im[:,:,3]>0).sum())}")

    # Tuvalden buyuk figur KUCULTULMELI, tasmamali
    buyuk = np.zeros((300, 300, 4), np.uint8)
    buyuk[10:290, 10:290] = (1, 2, 3, 255)
    t2, o2, _, _ = pd.kanvasa_yerlestir(buyuk, 128)
    check("tuval: buyuk figur kucultuldu", o2 < 1.0 and t2.shape == (128, 128, 4),
          f"olcek={o2}")


def test_ayna_etiketi_dogru_tasiyor():
    """Ayna hem x'i cevirmeli hem sol/sag etiketlerini TAKAS etmeli.

    Takas edilmezse veri sessizce bozulur: model sol omuzu sag omuz diye
    ogrenir. Iki kez aynalamak kimlik olmali."""
    im, kp = sahne(), kp_ornek()
    t1, k1 = pd.aynala(im, kp)
    t2, k2 = pd.aynala(t1, k1)

    check("ayna: goruntu iki kez cevrilince ayni", np.array_equal(t2, im))
    en = max(max(abs(k2[l][0] - kp[l][0]), abs(k2[l][1] - kp[l][1])) for l in kp)
    check("ayna: etiket iki kez cevrilince ayni", en < 1e-9, f"{en:.2e}")

    # Tek aynada sag/sol GERCEKTEN takas olmali
    check("ayna: RIGHT <- LEFT'ten geliyor",
          abs(k1["RIGHT SHOULDER"][0] - (1 - kp["LEFT SHOULDER"][0])) < 1e-9
          and abs(k1["RIGHT SHOULDER"][1] - kp["LEFT SHOULDER"][1]) < 1e-9)
    check("ayna: orta noktalar da cevriliyor",
          abs(k1["NOSE"][0] - (1 - kp["NOSE"][0])) < 1e-9)


def test_olcekleme_etiketi_tasiyor():
    """Olcek/kaydirma sonrasi eklem AYNI piksel icerigin uzerinde kalmali.

    Sentetik bir isaret koyup once ham goruntude yerini olcuyoruz, sonra
    donusturulmus goruntude etiketin hala o isaretin uzerinde oldugunu
    dogruluyoruz — matematigi degil SONUCU olcuyor."""
    im = np.zeros((128, 128, 4), np.uint8)
    im[40:90, 50:78] = (100, 100, 100, 255)
    im[44:50, 60:66] = (255, 0, 0, 255)                 # isaret
    isaret = np.array([63.0, 47.0])                     # isaretin merkezi
    kp = {l: [isaret[0] / 128, isaret[1] / 128] for l in sk.LABELS}

    sonuc = pd.olcekle(im, kp, 0.6, 5, -7)
    check("olcek: donusum uygulandi", sonuc is not None)
    if sonuc is None:
        return
    t, k = sonuc
    kirmizi = (t[:, :, 0] > 200) & (t[:, :, 1] < 80) & (t[:, :, 3] > 0)
    check("olcek: isaret hala goruntude", bool(kirmizi.any()))
    if not kirmizi.any():
        return
    ys, xs = np.where(kirmizi)
    beklenen = np.array([(xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2])
    olculen = np.array([k["NOSE"][0] * 128, k["NOSE"][1] * 128])
    sapma = float(np.linalg.norm(beklenen - olculen))
    check("olcek: eklem isaretin uzerinde kaldi", sapma <= 2.0,
          f"{sapma:.2f}px sapma (beklenen {beklenen.round(1)}, olculen {olculen.round(1)})")

    # Tasan donusum reddedilmeli, sessizce bozuk ornek uretilmemeli
    check("olcek: tasan donusum None donuyor",
          pd.olcekle(im, kp, 0.9, 60, 0) is None)


def test_ton_kaydirma_geometriyi_bozmuyor():
    """Ton kaydirma yalnizca RENGI degistirmeli; siluet birebir ayni kalmali,
    yoksa etiket gecerliligini kaybeder."""
    im = sahne()
    rng = np.random.default_rng(0)
    t = pd.ton_kaydir(im, 0.4, rng)
    check("ton: alfa birebir ayni", np.array_equal(t[:, :, 3], im[:, :, 3]))
    check("ton: renk gercekten degisti", not np.array_equal(t[:, :, :3], im[:, :, :3]))
    check("ton: seffaf bolge temiz", int(t[im[:, :, 3] == 0].sum()) == 0)


def test_onbellek_tekrar_ucretlendirmiyor():
    """Ayni goruntu ikinci kez etiketlenmemeli. Etiketleme UCRETLI oldugu icin
    bu bir dogruluk degil MALIYET testi — ve sessizce bozulursa fatura
    buyuyor."""
    im = sahne()
    tuval, _, _, _ = pd.kanvasa_yerlestir(im, 128)
    cagri = {"n": 0}

    with tempfile.TemporaryDirectory() as tmp:
        onbellek = os.path.join(tmp, "onbellek")
        os.makedirs(onbellek)
        sahte = {l: [0.5, 0.5] for l in sk.LABELS}
        with open(os.path.join(onbellek, f"{pd._hash(tuval)}.json"), "w") as f:
            json.dump(sahte, f)

        import requests
        gercek = requests.post

        def yakala(*a, **k):
            cagri["n"] += 1
            return gercek(*a, **k)

        requests.post = yakala
        try:
            k1 = pd.etiketle(tuval, "SAHTE", onbellek)
            k2 = pd.etiketle(tuval, "SAHTE", onbellek)
        finally:
            requests.post = gercek

    check("onbellek: API'ye hic gidilmedi", cagri["n"] == 0, f"{cagri['n']} cagri")
    check("onbellek: dogru etiket dondu", k1 == sahte and k2 == sahte)

    # Hash ICERIGE bagli olmali: tek piksel degisince yeni anahtar
    farkli = tuval.copy()
    farkli[0, 0] = (1, 2, 3, 255)
    check("onbellek: hash icerige duyarli", pd._hash(farkli) != pd._hash(tuval))


def test_kaynak_kareler_gercek_depoda():
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    kar = os.path.join(kok, "characters")
    if not os.path.isdir(kar):
        check("kaynak: characters/ yok, atlandi", True)
        return
    kareler = pd.kaynak_kareler(kar)
    check("kaynak: kare bulundu", len(kareler) >= 8, f"{len(kareler)} kare")
    check("kaynak: hepsi RGBA ve dolu",
          all(k.ndim == 3 and k.shape[2] == 4 and (k[:, :, 3] > 0).any()
              for _, k in kareler))
    check("kaynak: etiketler benzersiz",
          len({e for e, _ in kareler}) == len(kareler))


def main():
    testler = [
        test_kanvasa_yerlestirme,
        test_ayna_etiketi_dogru_tasiyor,
        test_olcekleme_etiketi_tasiyor,
        test_ton_kaydirma_geometriyi_bozmuyor,
        test_onbellek_tekrar_ucretlendirmiyor,
        test_kaynak_kareler_gercek_depoda,
    ]
    for t in testler:
        print(f"\n{t.__name__}:")
        t()
    print("\n" + "=" * 50)
    print(f"{PASSED} gecti, {FAILED} basarisiz")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
