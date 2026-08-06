#!/usr/bin/env python3
"""
skeleton.py icin regresyon testleri.

Yontem iki katmanli:

  SENTETIK — boyun cukuru, bacak araligi gibi landmark'lari BILDIGIMIZ basit
    figurler uretip tahmincinin onlari bulup bulmadigini olcuyoruz. Boylece
    "yaklasik dogru" degil, birebir dogrulanabilir bir cevap elde ediliyor.

  GERCEK — depodaki dort karakterin her karesi uzerinde degismezleri
    kontrol ediyoruz (eklemler siluetin icinde mi, boyun kalcanin ustunde mi,
    zincir caprazliyor mu). Sentetik testlerin kacirdigi seyi bunlar yakaliyor:
    bulunan iki hatanin ikisi de gercek karelerde ortaya cikti.

Calistirma:
    python3 tools/test_skeleton.py
"""

import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skeleton as sk  # noqa: E402


PASSED, FAILED = 0, 0
KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check(name: str, condition: bool, detail: str = ""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  HATA {name}" + (f" — {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# Sentetik figur
# ---------------------------------------------------------------------------

def figur(kafa_w=20, kafa_h=24, boyun_w=8, boyun_h=4, govde_w=26, govde_h=26,
          bacak_w=8, bacak_h=22, ara=6, kol_w=5, kol_kisa=0, tuval=90) -> np.ndarray:
    """Landmark'lari BILINEN bir onden gorunus figuru.

    Boyun cukuru, kalca ayrimi ve iki ayak bilerek olculebilir yerlerde."""
    im = np.zeros((tuval, tuval, 4), np.uint8)

    def kutu(y, h, w, x=None):
        x = tuval // 2 - w // 2 if x is None else x
        im[y:y + h, x:x + w] = (200, 100, 80, 255)

    y = 6
    kutu(y, kafa_h, kafa_w); y += kafa_h
    kutu(y, boyun_h, boyun_w); y += boyun_h
    govde_y = y
    kutu(y, govde_h, govde_w)
    # kollar govdenin iki yaninda. `kol_kisa` kollari govdeden once bitirir —
    # gercek karakterlerde oldugu gibi (el, kasiktan yukarida kalir).
    kol_h = govde_h - 2 - kol_kisa
    kutu(govde_y + 2, kol_h, kol_w, tuval // 2 - govde_w // 2 - kol_w)
    kutu(govde_y + 2, kol_h, kol_w, tuval // 2 + govde_w // 2)
    y += govde_h
    for dx in (-(ara // 2 + bacak_w), ara // 2):
        kutu(y, bacak_h, bacak_w, tuval // 2 + dx)
    return im


def test_boyun_olculuyor():
    """Boyun, satir genisligi profilinin %25-55 bandindaki minimumu olmali."""
    im = figur()
    op = im[:, :, 3] > 0
    ys, _ = np.where(op)
    y0, y1 = int(ys.min()), int(ys.max())
    b = sk.boyun_satiri(op, y0, y1)
    beklenen = 6 + 24                      # kafa bitisi = boyun baslangici
    check("boyun: cukurun icinde", beklenen <= b < beklenen + 4,
          f"bulundu y={b}, beklenen {beklenen}-{beklenen + 3}")
    check("boyun: govdeden dar", int(op[b].sum()) < 12, f"{int(op[b].sum())}px")


def test_boyun_tabani_aliniyor():
    """REGRESYON: boyun, dar bolgenin TEPESI (cene alti) olarak olculuyordu.

    Eklem olarak istenen sey boynun TABANI; omuz satiri da boyundan
    turetildigi icin hata iki katina cikiyordu. Olculdu: tepe alinirken
    boyun yuksekligi dort karakterde %30/%37/%41/%47 diye dagiliyor, en
    dusugunde (ael) omuzlar ceketin yakasina cikip dar kaliyordu; taban
    alininca dagilim %36/%40/%42/%49'a topluyor."""
    im = figur(boyun_h=5)
    op = im[:, :, 3] > 0
    ys, _ = np.where(op)
    y0, y1 = int(ys.min()), int(ys.max())
    b = sk.boyun_satiri(op, y0, y1)
    taban = 6 + 24 + 5 - 1                 # boyun bolgesinin son satiri
    check("boyun: tabanda", b == taban, f"bulundu y={b}, beklenen {taban}")

    # Omuz boyundan turetildigi icin taban duzeltmesi omuzu da asagi almali
    isk = sk.estimate(im, direction="south")
    check("boyun: omuz boynun altinda",
          isk.noktalar["RIGHT SHOULDER"][1] > b,
          f"omuz {isk.noktalar['RIGHT SHOULDER'][1]:.1f} <= boyun {b}")


def test_goz_scleradan_olculuyor():
    """REGRESYON: gozler kafa KUTUSUNUN ortasindan turetiliyordu; kutu saci
    da icerdigi icin topuzlu/uzun sacli karakterde noktalar alina biniyordu
    ve uc karakterde tutarsiz cikiyordu."""
    im = figur()
    goz_y = 16
    im[goz_y, 38:41] = (250, 250, 250, 255)      # sol sclera
    im[goz_y, 49:52] = (250, 250, 250, 255)      # sag sclera

    sonuc = sk.goz_satiri(im, 6, 30)
    check("goz: sclera satiri bulundu", sonuc is not None and sonuc[0] == goz_y,
          f"{sonuc[0] if sonuc else None}, beklenen {goz_y}")
    check("goz: iki kume", sonuc is not None and len(sonuc[1]) == 2,
          f"{len(sonuc[1]) if sonuc else 0} kume")

    isk = sk.estimate(im, direction="south")
    check("goz: olculen olarak isaretlendi", "RIGHT EYE" in isk.olculen)
    check("goz: satir sclera hizasinda",
          isk.noktalar["RIGHT EYE"][1] == goz_y,
          f"y={isk.noktalar['RIGHT EYE'][1]}")
    check("goz: RIGHT solda (south)",
          isk.noktalar["RIGHT EYE"][0] < isk.noktalar["LEFT EYE"][0])

    # Sclera yoksa turetilmeye dusmeli ve OLCULDU diye isaretlenmemeli
    isk2 = sk.estimate(figur(), direction="south")
    check("goz: sinyal yokken turetiliyor", "RIGHT EYE" not in isk2.olculen)


def test_kalca_bacak_ayriminda():
    im = figur()
    op = im[:, :, 3] > 0
    ys, _ = np.where(op)
    y0, y1 = int(ys.min()), int(ys.max())
    k = sk.kalca_satiri(op, y0, y1)
    beklenen = 6 + 24 + 4 + 26             # govde bitisi = bacak baslangici
    check("kalca: bacak ayriminda", abs(k - beklenen) <= 2,
          f"bulundu y={k}, beklenen ~{beklenen}")


def test_kalca_bacaklar_bitisikken_dibe_dusmuyor():
    """REGRESYON: bacaklar bitisik oldugunda kalca tuvalin dibine kaciyordu.

    Eski olcut "asagidan yukari ILK tek bant satiri" idi; bacaklar arasinda
    bosluk olmayan pozlarda en alt satir zaten tek bant oldugu icin fonksiyon
    hemen y1'i donduruyordu. Olculdu: mag'in yurume sheet'inde 8 karenin
    3'unde kasik %99'a, yani ayak tabanina cikiyordu."""
    im = figur(ara=0)                      # bacaklar bitisik
    op = im[:, :, 3] > 0
    ys, _ = np.where(op)
    y0, y1 = int(ys.min()), int(ys.max())
    h = y1 - y0 + 1
    k = sk.kalca_satiri(op, y0, y1)
    check("kalca: bitisik bacakta tabana dusmuyor", (k - y0) / h < 0.95,
          f"%{100 * (k - y0) / h:.0f}")


def test_ayak_bantlari_konturu_delmiyor():
    """REGRESYON: tek satir kullanmak ayakkabi konturundaki bir piksellik
    bosluktan sahte bant uretiyordu. Serit birlestirmesi bunu kapatmali."""
    im = figur()
    im[-3, :, 3] = 0                       # en alt satirda kontur bosluğu
    op = im[:, :, 3] > 0
    ys, _ = np.where(op)
    y0, y1 = int(ys.min()), int(ys.max())
    b = sk.ayak_bantlari(op, y0, y1)
    check("ayak: tam iki bant", len(b) == 2, f"{len(b)} bant: {b}")


def test_onden_zincir_caprazlamiyor():
    """REGRESYON: onden gorunuste omuz/kalca kucuk x'e (RIGHT), ayak buyuk x'e
    atandigi icin iskelet X ciziyordu."""
    isk = sk.estimate(figur(), direction="south")
    sag = [isk.noktalar[a][0] for a in ("RIGHT SHOULDER", "RIGHT HIP", "RIGHT LEG")]
    sol = [isk.noktalar[a][0] for a in ("LEFT SHOULDER", "LEFT HIP", "LEFT LEG")]
    check("onden: RIGHT zinciri tek tarafta", max(sag) < min(sol),
          f"sag={[round(v, 1) for v in sag]} sol={[round(v, 1) for v in sol]}")


def test_dirsek_kolun_uzerinde():
    """REGRESYON: dirsek omuz ile elin duz orta noktasiydi; omuz siluetin
    iceride, el dis kenarda oldugu icin orta nokta GOVDENIN ICINE dusuyordu."""
    im = figur()
    isk = sk.estimate(im, direction="south")
    op = im[:, :, 3] > 0
    govde_yari = 26 / 2
    merkez = im.shape[1] / 2
    for a in ("RIGHT ELBOW", "LEFT ELBOW"):
        x, y = isk.noktalar[a]
        check(f"dirsek {a.split()[0]}: govdenin disinda",
              abs(x - merkez) > govde_yari - 1,
              f"x={x:.1f}, govde kenari {merkez - govde_yari:.0f}-{merkez + govde_yari:.0f}")
        check(f"dirsek {a.split()[0]}: siluetin icinde", bool(op[int(round(y)), int(round(x))]),
              f"({x:.1f},{y:.1f}) seffaf")


def test_el_kolun_bittigi_yerde():
    """REGRESYON: el yuksekligi kalcadan turetiliyordu (`kalca - %2h`) ve
    kollar kasiktan once bittiginde noktalar BACAKLARA tasiyordu.

    Kalca dogru olculur olmaz ortaya cikti: mag'de kalca %77'ye oturunca el
    hizasi %75'e indi, ama mag'in kollari %73'te bitiyor — o satirda siluet
    artik yalnizca pantolon (bant (31,55)) ve "el" noktalari pacanin kenarina
    dusuyordu. Simdi el, kolun dis kenarinin uc degerine yakin kaldigi son
    satirda."""
    kol_kisa = 10
    im = figur(kol_kisa=kol_kisa)
    op = im[:, :, 3] > 0
    govde_y = 6 + 24 + 4
    kol_alt = govde_y + 2 + (26 - 2 - kol_kisa) - 1      # kolun son satiri
    bacak_ust = govde_y + 26

    isk = sk.estimate(im, direction="south")
    for a in ("RIGHT ARM", "LEFT ARM"):
        x, y = isk.noktalar[a]
        check(f"{a}: kolun bittigi satirda", abs(y - kol_alt) <= 2,
              f"y={y:.1f}, kol {kol_alt}'de bitiyor, bacaklar {bacak_ust}'de basliyor")
        check(f"{a}: bacaklarin ustunde", y < bacak_ust,
              f"y={y:.1f} >= bacak ust {bacak_ust}")
        check(f"{a}: siluetin icinde", bool(op[int(round(y)), int(round(x))]),
              f"({x:.1f},{y:.1f}) seffaf")

    # Govdenin disinda, yani KOLUN uzerinde olmali
    merkez, govde_yari = im.shape[1] / 2, 26 / 2
    check("el: govdenin disinda",
          all(abs(isk.noktalar[a][0] - merkez) > govde_yari - 1
              for a in ("RIGHT ARM", "LEFT ARM")),
          f"{[round(isk.noktalar[a][0], 1) for a in ('RIGHT ARM', 'LEFT ARM')]}")


def test_yuz_renkten_bulunuyor():
    """Sacli karakterde yuz SILUETTEN degil RENKTEN bulunmali.

    Siluet kafayi sacla birlikte tek kutle sayiyor; gozler ve kulaklar kafa
    kutusundan turetilince saca biniyor. Olculdu — faküs'te kulaklar x28/62
    cikiyordu, oysa yuz x42-52 arasinda.

    Yuz semantikle degil YAPIYLA taniniyor: goruntunun ust yarisina tamamen
    sigan en buyuk bagli renk bolgesi. Boylece "ten rengi su araliktadir"
    gibi, cizim tarzi degisince kirilacak bir kural gerekmiyor."""
    im = figur(kafa_w=26, tuval=90)
    # Sac: kafanin iki yanina, yuzden farkli renkte ve ASAGI TASAN
    im[6:46, 26:32] = (60, 30, 20, 255)
    im[6:46, 58:64] = (60, 30, 20, 255)
    # Yuz: kafanin ortasi
    im[8:28, 34:56] = (230, 180, 150, 255)

    yuz = sk.yuz_bolgesi(im)
    check("yuz: bulundu", yuz is not None)
    if yuz is None:
        return
    y_ust, y_alt, x_sol, x_sag = yuz
    check("yuz: sac degil yuz secildi", 32 < x_sol and x_sag < 58,
          f"x{x_sol}-{x_sag}, sac 26-32 ve 58-64'te")
    check("yuz: dikey kutu dogru", 6 <= y_ust and y_alt <= 30,
          f"y{y_ust}-{y_alt}")

    isk = sk.estimate(im, direction="south")
    check("yuz: kulaklar yuzun kenarinda",
          x_sol - 1 <= isk.noktalar["RIGHT EAR"][0] <= x_sag + 1
          and x_sol - 1 <= isk.noktalar["LEFT EAR"][0] <= x_sag + 1,
          f"{isk.noktalar['RIGHT EAR'][0]:.1f} / {isk.noktalar['LEFT EAR'][0]:.1f}")
    check("yuz: gozler yuz kutusunda",
          all(x_sol <= isk.noktalar[a][0] <= x_sag and y_ust <= isk.noktalar[a][1] <= y_alt
              for a in ("RIGHT EYE", "LEFT EYE")),
          f"{[tuple(round(v, 1) for v in isk.noktalar[a]) for a in ('RIGHT EYE', 'LEFT EYE')]}")


def test_zayif_sinyal_isaretleniyor():
    """Olcum YAPILDI ile olcum ANLAMLI ayni sey degil.

    Karakterlerin cizim tarzi ayni olmadigi icin bir karakterde net olan
    isaret digerinde hic olmayabiliyor. faküs boyle: sac omuzlara indigi ve
    govde ince oldugu icin boyun cukuru YOK (olculdu — boyunda 26 piksel,
    gogüste 25-27), gozlerinde parlak sclera yok, bol pacali pantolon iki
    bacagi birlestiriyor. Deger yine uretiliyor ama guvenilmez; bunu sessizce
    yutmak yanlisi dogru gibi gosterirdi.

    Olculdu: dar bolge orani bes karakterde %2.4/%3.5/%3.6/%7.1 ve faküs'te
    %13.2 — esik ikisinin arasina konuldu ve yalnizca faküs isaretleniyor."""
    # Boyun cukuru olmayan figur: kafa, boyun ve govde ayni genislikte
    duz = figur(kafa_w=26, boyun_w=26, govde_w=26)
    isk = sk.estimate(duz, direction="south")
    check("zayif sinyal: cukursuz boyun isaretlendi", "NECK" in isk.supheli,
          f"supheli={sorted(isk.supheli)}")
    check("zayif sinyal: omuzlar da isaretlendi",
          "RIGHT SHOULDER" in isk.supheli and "LEFT SHOULDER" in isk.supheli)

    # Bacaklari birlesik figur (bol paca / cubbe)
    birlesik = figur(ara=0)
    isk2 = sk.estimate(birlesik, direction="south")
    check("zayif sinyal: birlesik bacak isaretlendi",
          "RIGHT LEG" in isk2.supheli and "LEFT KNEE" in isk2.supheli,
          f"supheli={sorted(isk2.supheli)}")

    # Sclera yoksa yuz noktalari supheli
    check("zayif sinyal: sclera yokken gozler isaretlendi",
          "RIGHT EYE" in isk2.supheli and "NOSE" in isk2.supheli)

    # Normal figurde bunlarin hicbiri isaretlenmemeli
    goz = figur()
    goz[16, 38:41] = (250, 250, 250, 255)
    goz[16, 49:52] = (250, 250, 250, 255)
    isk3 = sk.estimate(goz, direction="south")
    check("zayif sinyal: saglam figurde bos", not isk3.supheli,
          f"supheli={sorted(isk3.supheli)}")

    # rige_oturt bilgiyi kaybetmemeli
    rig = sk.rig_olustur([isk, isk])
    check("zayif sinyal: rige oturunca korunuyor",
          sk.rige_oturt(isk, rig).supheli == isk.supheli)


def test_gercek_karakterlerde_zayif_sinyal():
    """faküs disindaki karakterlerde uyari cikmamali (yanlis alarm olcumu)."""
    for ad, meta, dizin in karakterler():
        if "idle" not in meta:
            continue
        k = meta["idle"]["frameSize"]
        sh = np.array(Image.open(os.path.join(dizin, meta["idle"]["file"]))
                      .convert("RGBA"))
        isk = sk.estimate(sh[:, :k], direction="south")
        if ad == "faküs":
            check(f"{ad}: yapisal farklilik yakalandi", len(isk.supheli) >= 6,
                  f"{len(isk.supheli)} isaret")
            check(f"{ad}: bel isaretlenmedi", "RIGHT HIP" not in isk.supheli)
        else:
            check(f"{ad}: yanlis alarm yok", not isk.supheli,
                  f"supheli={sorted(isk.supheli)}")


def test_pixellab_formati():
    isk = sk.estimate(figur(), direction="south")
    kp = isk.to_pixellab()
    check("pixellab: 18 keypoint", len(kp) == 18, f"{len(kp)}")
    check("pixellab: etiketler birebir",
          [k["label"] for k in kp] == list(sk.LABELS))
    check("pixellab: alanlar tam",
          all({"x", "y", "label", "z_index"} == set(k) for k in kp))
    check("pixellab: JSON'a yazilabiliyor", isinstance(json.dumps(kp), str))


def test_profilde_z_ayiriyor():
    """Yandan bakista sol/sag ayni x'te; ayrimi z_index tasimali."""
    isk = sk.estimate(figur(), direction="east")
    check("profil: on uzuv z=1",
          all(isk.z[a] == 1.0 for a in ("RIGHT SHOULDER", "RIGHT HIP", "RIGHT LEG")))
    check("profil: arka uzuv z=0",
          all(isk.z[a] == 0.0 for a in ("LEFT SHOULDER", "LEFT HIP", "LEFT LEG")))


def test_bos_ve_bozuk_girdi():
    try:
        sk.estimate(np.zeros((20, 20, 4), np.uint8), "south")
        check("bos kare: hata veriyor", False, "hata vermedi")
    except ValueError:
        check("bos kare: hata veriyor", True)
    try:
        sk.estimate(np.zeros((20, 20, 3), np.uint8), "south")
        check("RGB girdi: hata veriyor", False, "hata vermedi")
    except ValueError:
        check("RGB girdi: hata veriyor", True)
    try:
        sk.estimate(figur(), "yukari")
        check("gecersiz yon: hata veriyor", False, "hata vermedi")
    except ValueError:
        check("gecersiz yon: hata veriyor", True)


# ---------------------------------------------------------------------------
# Gercek karakterler
# ---------------------------------------------------------------------------

def karakterler():
    kok = os.path.join(KOK, "characters")
    if not os.path.isdir(kok):
        return
    for ad in sorted(d for d in os.listdir(kok) if os.path.isdir(os.path.join(kok, d))):
        yol = os.path.join(kok, ad, "meta.json")
        if os.path.exists(yol):
            with open(yol) as f:
                yield ad, json.load(f), os.path.join(kok, ad)


def test_gercek_karakterlerde_degismezler():
    """Dort karakterin HER karesinde tutmasi gereken sartlar.

    Sentetik figur bunlarin hicbirini yakalayamazdi: bulunan iki hata da
    (capraz zincir, yurumede kacan kalca) ancak gercek karelerde ortaya
    cikti."""
    bakilan = 0
    for ad, meta, dizin in karakterler():
        for klip, yon in (("idle", "south"), ("walk_right", "east")):
            if klip not in meta:
                continue
            # Sert degismezler yalnizca TEMEL POZDA aranir. Yurume sheet'leri
            # farkli yollarla uretildi ve kendileri tutarsiz (olculdu: rig'e
            # oturttuktan sonra bile %60-124 sapma); onlarda yalnizca
            # "cikarim cokmeden calisti" bekleniyor.
            temel = klip == "idle"
            k = meta[klip]["frameSize"]
            sh = np.array(Image.open(os.path.join(dizin, meta[klip]["file"]))
                          .convert("RGBA"))
            for i in range(meta[klip]["frameCount"]):
                kare = sh[:, i * k:(i + 1) * k]
                if not (kare[:, :, 3] > 0).any():
                    continue
                bakilan += 1
                etiket = f"{ad}/{klip}[{i}]"
                try:
                    isk = sk.estimate(kare, direction=yon)
                except Exception as err:                    # noqa: BLE001
                    check(f"{etiket}: cikarim calisti", False, str(err))
                    continue

                ys, xs = np.where(kare[:, :, 3] > 0)
                y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
                h = y1 - y0 + 1

                disari = [a for a, (x, y) in isk.noktalar.items()
                          if not (x0 - 2 <= x <= x1 + 2 and y0 - 2 <= y <= y1 + 2)]
                check(f"{etiket}: eklemler siluet kutusunda", not disari, str(disari))
                if not temel:
                    continue

                boyun_y = isk.noktalar["NECK"][1]
                kalca_y = isk.noktalar["RIGHT HIP"][1]
                check(f"{etiket}: boyun kalcanin ustunde", boyun_y < kalca_y,
                      f"boyun {boyun_y:.0f} kalca {kalca_y:.0f}")
                check(f"{etiket}: kalca makul yukseklikte",
                      0.45 < (kalca_y - y0) / h < 0.92,
                      f"%{100 * (kalca_y - y0) / h:.0f}")

                # Zincir TERS donmemeli. Esitlik hata degil: bacaklari
                # ayrilmayan bir figurde (bol pacali pantolon, cubbe) iki ayak
                # ayni noktaya dusuyor ve bu BELGELENMIS geri dusus — faküs
                # tam boyle, alt seritte tek bant veriyor. Ters donme ise
                # gercek hata: sag ile solun yer degistirdigi anlamina gelir.
                sag = max(isk.noktalar[a][0]
                          for a in ("RIGHT SHOULDER", "RIGHT HIP", "RIGHT LEG"))
                sol = min(isk.noktalar[a][0]
                          for a in ("LEFT SHOULDER", "LEFT HIP", "LEFT LEG"))
                check(f"{etiket}: zincir ters donmemis", sag <= sol,
                      f"sag {sag:.1f} > sol {sol:.1f}")
    check("gercek karakterler: kare bulundu", bakilan >= 8, f"{bakilan} kare")


def test_duzenleyici_sayfasi():
    """skeleton_edit'in urettigi sayfa KENDI KENDINE yeterli olmali.

    Sablon degistirilirken bir yer atlanirsa sayfa sessizce bozuluyor:
    doldurulmamis bir __YER_TUTUCU__ kalirsa JS ya cizim yapamiyor ya da
    hic acilmiyor. Bunu gozle fark etmek zor, testle kolay."""
    import skeleton_edit as se

    html = (se.SAYFA
            .replace("__KEMIK__", json.dumps([list(k) for k in sk.KEMIKLER]))
            .replace("__LABELS__", json.dumps(list(sk.LABELS))))
    check("duzenleyici: yer tutucu kalmadi", "__KEMIK__" not in html
          and "__LABELS__" not in html)
    check("duzenleyici: dis kaynak yok",
          "http://" not in html and "https://" not in html)
    bas = html.index("LABELS = ") + len("LABELS = ")
    check("duzenleyici: 18 etiket",
          json.loads(html[bas:html.index(";", bas)]) == list(sk.LABELS))

    # Serit ayirma: 4 karelik bir seritten dogru kare cikmali
    serit = np.zeros((20, 80, 4), np.uint8)
    for i in range(4):
        serit[:, i * 20:(i + 1) * 20] = (i * 10, 0, 0, 255)
    kare, toplam = se._kareyi_cikar(serit, 2, None)
    check("duzenleyici: serit 4 kareye bolundu", toplam == 4, f"{toplam}")
    check("duzenleyici: dogru kare secildi", int(kare[0, 0, 0]) == 20,
          f"{int(kare[0, 0, 0])}")
    check("duzenleyici: tasan kare kirpiliyor", se._kareyi_cikar(serit, 99, None)[0]
          .shape[1] == 20)
    tek, n = se._kareyi_cikar(np.zeros((20, 20, 4), np.uint8), 0, None)
    check("duzenleyici: tek kare serit sanilmiyor", n == 1, f"{n}")
    check("duzenleyici: sprite data-uri uretiliyor",
          se._png_datauri(kare).startswith("data:image/png;base64,"))


def test_duzenlenen_iskelet_geri_yuklenebiliyor():
    """Tarayicidan donen ham koordinatlar gecerli bir Iskelet vermeli."""
    isk = sk.estimate(figur(), direction="south")
    ham = {a: [x + 1.5, y - 2.0] for a, (x, y) in isk.noktalar.items()}
    geri = sk.Iskelet({a: (float(v[0]), float(v[1])) for a, v in ham.items()},
                      dict(isk.z), isk.olculen)
    kp = geri.to_pixellab()
    check("geri yukleme: 18 keypoint", len(kp) == 18)
    check("geri yukleme: kaydirma korundu",
          abs(kp[0]["x"] - (isk.noktalar["NOSE"][0] + 1.5)) < 1e-6)

    eksik = dict(ham)
    del eksik["NECK"]
    try:
        sk.Iskelet({a: (float(v[0]), float(v[1])) for a, v in eksik.items()})
        check("geri yukleme: eksik eklem reddediliyor", False, "hata vermedi")
    except ValueError:
        check("geri yukleme: eksik eklem reddediliyor", True)


def test_temel_pozda_kemikler_tutarli():
    """GUVENILIRLIK OLCUTU: ayni karakterin kareleri arasinda kemik uzunlugu
    degismemeli. Gercek bir iskelette kemik uzamaz.

    Bu olcut disarida bir modele ihtiyac duymadan calisiyor ve bize ozel bir
    avantaj: ayni karakterin 4-8 karesi elimizde. Iki hatayi da bu yakaladi —
    kasik satirinin kareden kareye %79/%86 diye ziplamasi (kemikleri %40
    oynatiyordu) ve profil tahmininin hic tutarli olmamasi.

    Olcum yalnizca TEMEL POZ (onden idle) uzerinde: animasyon iskeleti buradan
    cikarilip pozlar ondan uretiliyor. Yurume sheet'leri olcut DEGIL — farkli
    yollarla uretildikleri icin kendileri tutarsiz (olculdu: rig'e oturttuktan
    sonra bile %60-124 sapma)."""
    bakilan = 0
    for ad, meta, dizin in karakterler():
        if "idle" not in meta:
            continue
        k = meta["idle"]["frameSize"]
        sh = np.array(Image.open(os.path.join(dizin, meta["idle"]["file"]))
                      .convert("RGBA"))
        iskeletler = []
        for i in range(meta["idle"]["frameCount"]):
            kare = sh[:, i * k:(i + 1) * k]
            if (kare[:, :, 3] > 0).any():
                iskeletler.append(sk.estimate(kare, direction="south"))
        if len(iskeletler) < 2:
            continue
        bakilan += 1
        rig = sk.rig_olustur(iskeletler)
        oturmus = [sk.rige_oturt(i, rig) for i in iskeletler]

        def sapma(liste):
            """Her kemigin MEDYANINDAN sapmasi; kareler arasi %75'lik dilim.

            Uc deger (max-min) yerine dilim aliniyor cunku olcut kaynak
            sanatinin kalitesine karsi dayanikli olmali: bir karakterin tek
            bir karesi bozuk cizilmis olabilir ve bu bizim tespitimizin
            hatasi degildir. Olculdu — omerhan'in idle karelerinden birinde
            kasik satiri 3 bantli cikiyor (digerlerinde 2), cunku o kare
            kaynakta tutarsiz. Dort karenin ucunde tutmak yeterli."""
            toplu = {}
            for isk in liste:
                for kb, u in sk.kemik_uzunluklari(isk).items():
                    toplu.setdefault(kb, []).append(u)
            en_kotu = 0.0
            for v in toplu.values():
                med = float(np.median(v))
                if med < 1e-9:
                    continue
                d = sorted(100 * abs(x - med) / med for x in v)
                en_kotu = max(en_kotu, d[int(0.75 * (len(d) - 1))])
            return en_kotu

        check(f"{ad}: temel pozda kemik sapmasi dusuk", sapma(iskeletler) < 20,
              f"%{sapma(iskeletler):.0f}")
        check(f"{ad}: rige oturunca sapma neredeyse sifir", sapma(oturmus) < 5,
              f"%{sapma(oturmus):.0f}")
    check("tutarlilik: karakter bulundu", bakilan >= 1, f"{bakilan}")


def test_ik_uzunlugu_koruyor():
    """Iki kemik IK, verilen uzunluklari tutturmali; yetismeyen zincirde de
    makul bir sey dondurmeli (cokme ya da NaN yok)."""
    orta = sk._iki_kemik_ik((0.0, 0.0), (6.0, 0.0), 5.0, 5.0, tercih=(3.0, -5.0))
    check("IK: l1 korundu", abs(np.hypot(*orta) - 5.0) < 1e-6, f"{np.hypot(*orta):.3f}")
    check("IK: tercih edilen tarafa bukuldu", orta[1] < 0, f"y={orta[1]:.2f}")
    obur = sk._iki_kemik_ik((0.0, 0.0), (6.0, 0.0), 5.0, 5.0, tercih=(3.0, 5.0))
    check("IK: obur cozum de secilebiliyor", obur[1] > 0, f"y={obur[1]:.2f}")

    uzak = sk._iki_kemik_ik((0.0, 0.0), (100.0, 0.0), 5.0, 5.0, tercih=(3.0, 0.0))
    check("IK: yetismeyen zincirde cokmuyor",
          all(np.isfinite(v) for v in uzak) and 0 < uzak[0] < 100, str(uzak))


def main():
    testler = [
        test_boyun_olculuyor,
        test_boyun_tabani_aliniyor,
        test_goz_scleradan_olculuyor,
        test_kalca_bacak_ayriminda,
        test_kalca_bacaklar_bitisikken_dibe_dusmuyor,
        test_ayak_bantlari_konturu_delmiyor,
        test_onden_zincir_caprazlamiyor,
        test_dirsek_kolun_uzerinde,
        test_el_kolun_bittigi_yerde,
        test_yuz_renkten_bulunuyor,
        test_zayif_sinyal_isaretleniyor,
        test_gercek_karakterlerde_zayif_sinyal,
        test_pixellab_formati,
        test_profilde_z_ayiriyor,
        test_bos_ve_bozuk_girdi,
        test_duzenleyici_sayfasi,
        test_duzenlenen_iskelet_geri_yuklenebiliyor,
        test_ik_uzunlugu_koruyor,
        test_gercek_karakterlerde_degismezler,
        test_temel_pozda_kemikler_tutarli,
    ]
    for t in testler:
        print(f"\n{t.__name__}:")
        t()
    print("\n" + "=" * 50)
    print(f"{PASSED} gecti, {FAILED} basarisiz")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
