#!/usr/bin/env python3
"""
iskelet_rig.py — iskeletten kukla (rig) ve poz dosyasi turetir.

    python3 tools/iskelet_rig.py characters/ael/walk_right_spritesheet.png \
        --sablon _data/sablonlar.json --klip walk_right -o _cikti/ael

NEDEN BU MODUL VAR

    Boru hattinda iki ucu birbirine bakan ama birbirine degmeyen iki parca
    vardi:

        poz_sablonu.py  KEYPOINT uretiyor  (hedef pozun eklem yerleri)
        rig_pose.py     PARCA ACISI istiyor (her uzvun kac derece donecegi)
                        ve ustelik parca kutularini `rig.json` olarak
                        DISARIDAN bekliyor — depoda oyle bir dosya hic yoktu,
                        yani hat bu noktada kopuktu.

    Ikisi de artik iskeletten turetilebiliyor: poz modeli eklem yerlerini
    yeterince dogru veriyor (dort holdout ortalamasi 3.10px).

PARCA ATAMASI DIKDORTGENLE DEGIL, EN YAKIN KEMIKLE

    `rig_pose.parcalara_bol` parcalari eksen-hizali dikdortgenlerle kesiyor
    ve cakismayi liste sirasiyla cozuyor. Elle yazilmis bir rig'de bu yeterli,
    ama OTOMATIK uretimde cokuyor: capraz duran bir ust kolun sinirlayici
    kutusu govdenin buyuk kismini kapsiyor ve uzuvlar listede once geldigi
    icin o pikselleri kol calıyor.

    Bunun yerine her opak piksel, DOGRU PARCASINI kendisi seciyor: hangi
    kemik parcasina daha yakinsa ona gidiyor. Kemik bir dogru parcasi, uzaklik
    da noktanin o parcaya olan dik uzakligi. Cizim tarzindan bagimsiz calisiyor
    — kutu ayarlamak gerekmiyor.

ORAN BAGISIK

    Uzuv kalinligi olculuyor, varsayilmiyor: her kemik boyunca ornek alinip
    siluetin dik yondeki genisligine bakiliyor. Sisman bir karakterde govde
    kemigi genis bir bant, ince bir karakterde dar bir bant kapiyor — ikisinde
    de kendi olcusuyle. Sabit bir kalinlik yazsaydik model chibi'de calisip
    baska oranlarda cokerdi.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rig_pose as rp  # noqa: E402
import skeleton as sk  # noqa: E402


# (parca adi, kemigin ust eklemi, alt eklemi, ata parca, z)
#
# z sirasi SAGA BAKAN yandan gorunuse gore: uzak uzuvlar govdenin arkasinda,
# yakin uzuvlar onunde. "yakin_"/"uzak_" onekleri rig_pose'un faz takasi
# mekanizmasinin bekledigi adlandirma — o mekanizma yalnizca bu onekleri
# tanidigi icin ad serbest degil.
PARCA_SEMASI = (
    ("uzak_ust_kol",   "UZAK SHOULDER", "UZAK ELBOW", "govde",         -4),
    ("uzak_alt_kol",   "UZAK ELBOW",    "UZAK ARM",   "uzak_ust_kol",  -3),
    ("uzak_ust_bacak", "UZAK HIP",      "UZAK KNEE",  "govde",         -2),
    ("uzak_alt_bacak", "UZAK KNEE",     "UZAK LEG",   "uzak_ust_bacak", -1),
    ("govde",          "NECK",          "KALCA",      None,             0),
    ("kafa",           "NECK",          "BAS",        "govde",          1),
    ("yakin_ust_bacak", "YAKIN HIP",    "YAKIN KNEE", "govde",          2),
    ("yakin_alt_bacak", "YAKIN KNEE",   "YAKIN LEG",  "yakin_ust_bacak", 3),
    ("yakin_ust_kol",  "YAKIN SHOULDER", "YAKIN ELBOW", "govde",        4),
    ("yakin_alt_kol",  "YAKIN ELBOW",   "YAKIN ARM",  "yakin_ust_kol",  5),
)


def _turetilmis(kp: dict[str, tuple[float, float]], yakin: str
                ) -> dict[str, tuple[float, float]]:
    """Semadaki sanal eklemleri ekler ve YAKIN/UZAK'i sol/saga baglar.

    KALCA iki kalcanin orta noktasi: govde kemigi tek olmali, yoksa govde iki
    ayri parcaya bolunurdu.

    BAS kafa kemiginin alt ucu. NOSE degil, cunku NOSE kafanin ON yuzunde ve
    o kemige en yakin piksel ataması kafatasinin arkasini govdeye birakirdi.
    Kafa kemigi bunun yerine NECK'ten YUKARI dikey uzatiliyor; uzunlugu
    NECK ile burun arasindaki dikey mesafenin iki kati — kafatasi burnun
    yaklasik o kadar ustune cikiyor."""
    uzak = "LEFT" if yakin == "RIGHT" else "RIGHT"
    d = dict(kp)
    d["KALCA"] = ((kp["LEFT HIP"][0] + kp["RIGHT HIP"][0]) / 2,
                  (kp["LEFT HIP"][1] + kp["RIGHT HIP"][1]) / 2)
    kafa_boyu = max(kp["NECK"][1] - kp["NOSE"][1], 1e-6)
    d["BAS"] = (kp["NECK"][0], kp["NECK"][1] - 2 * kafa_boyu)
    for uzuv in ("SHOULDER", "ELBOW", "ARM", "HIP", "KNEE", "LEG"):
        d[f"YAKIN {uzuv}"] = kp[f"{yakin} {uzuv}"]
        d[f"UZAK {uzuv}"] = kp[f"{uzak} {uzuv}"]
    return d


def uzuv_kalinligi(maske: np.ndarray, a: tuple[float, float],
                   b: tuple[float, float]) -> float:
    """Parcanin kemige olan dik uzakliginin %90'lik dilimi.

    Ortalama degil %90: uzvun UCU inceliyor (el, ayak) ve ortalama o incelmeyi
    tum uzva yayardi. En buyuk degeri almak da yanlis olurdu, tek bir taşan
    piksel (sac teli, aksesuar) kalinligi ucurur."""
    ys, xs = np.nonzero(maske)
    if ys.size == 0:
        return 0.0
    return float(np.percentile(
        rp.nokta_kemik_uzakligi(xs.astype(np.float64), ys.astype(np.float64), a, b), 90))


# Bir uzvun UST parcasi (ust kol, uyluk) kendi kalinligini olcemiyor: govdenin
# onunde durdugu icin olctugu sey govdenin genisligi oluyor. UC parcasi (on kol,
# baldir) siluetten disari tastigi icin olcebiliyor. Ust parcanin yaricapi
# bu yuzden ucundan aliniyor, biraz payla — ust kol on koldan kalin.
UC_PARCA = {"uzak_ust_kol": "uzak_alt_kol", "yakin_ust_kol": "yakin_alt_kol",
            "uzak_ust_bacak": "uzak_alt_bacak", "yakin_ust_bacak": "yakin_alt_bacak"}
UC_PAYI = 1.25


def govde_yaricapi(rgba: np.ndarray, a: tuple[float, float],
                   b: tuple[float, float]) -> float:
    """Govde/kafa kemiginin yaricapi: SILUETTEN olculuyor, atamadan degil.

    Atamadan olcmek dongusel olurdu — govde pikselini kollara kaptirdigi icin
    dar cikar, dar ciktigi icin daha da kaptirirdi. Siluet ise atamadan
    bagimsiz: kemik boyunca ornek alinip her ornekte siluetin DIK yondeki
    yarim genisligi olculuyor, medyani aliniyor.

    Sisman bir karakterde bu deger kendiliginden buyuyor ve govde gogsu geri
    aliyor; ince bir karakterde kuculuyor. Sabit bir sayi yazmak modeli tek
    bir vucut tipine baglardi."""
    opak = rgba[:, :, 3] > 0
    h, w = opak.shape
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    uz = math.hypot(dx, dy)
    if uz < 1e-6:
        return 1.0
    nx, ny = -dy / uz, dx / uz          # kemige dik birim vektor
    genislikler = []
    for t in np.linspace(0.2, 0.8, 7):  # uclar hariç: orada uzuv zaten inceliyor
        cx, cy = ax + t * dx, ay + t * dy
        for yon in (1, -1):
            k = 0.0
            while k < uz:               # siluet bitene kadar dik yonde yuru
                x, y = int(round(cx + yon * k * nx)), int(round(cy + yon * k * ny))
                if not (0 <= x < w and 0 <= y < h) or not opak[y, x]:
                    break
                k += 0.5
            genislikler.append(k)
    return max(float(np.median(genislikler)), 1.0)


def rig_uret(rgba: np.ndarray, kp: dict, yakin: str = "RIGHT") -> dict:
    """Sprite + iskeletten `rig_pose.py`nin bekledigi rig sozlugunu kurar."""
    eklem = _turetilmis(kp, yakin)

    # 1) Ham uzaklikla bol — uc parcalarin (on kol, baldir) kalinligini
    #    olcebilmek icin. Onlar siluetten disari tastigi icin bu asamada
    #    dogru olculuyorlar.
    gecici = [{"ad": ad, "kemik": [eklem[ust], eklem[alt]]}
              for ad, ust, alt, _, _ in PARCA_SEMASI]
    ilk = rp.kemige_gore_bol(rgba, gecici)

    # 2) Yaricaplari kur: govde/kafa siluetten, uzuvlar ucundan.
    yaricap = {}
    for ad, ust, alt, _, _ in PARCA_SEMASI:
        if ad in UC_PARCA:
            continue
        if ad in ("govde", "kafa"):
            yaricap[ad] = govde_yaricapi(rgba, eklem[ust], eklem[alt])
        else:
            yaricap[ad] = max(uzuv_kalinligi(ilk[ad], eklem[ust], eklem[alt]), 1.0)
    for ust_ad, uc_ad in UC_PARCA.items():
        yaricap[ust_ad] = yaricap[uc_ad] * UC_PAYI

    # 3) Yaricapla yeniden bol — nihai atama.
    for g in gecici:
        g["yaricap"] = yaricap[g["ad"]]
    maskeler = rp.kemige_gore_bol(rgba, gecici)

    # 4) KAFA BOYUN CIZGISININ ALTINA INEMEZ.
    #
    # Yaricap yarisi tek basina yetmiyor: sacli bir karakterde kafa kemiginin
    # yaricapi govdeninkinden buyuk cikiyor (olculdu, LPC male: kafa 11.8,
    # govde 8.5) ve kafa gogsu kazaniyor. Olculdu — kafaya 484 piksel
    # gidiyordu, karakterin yarisindan fazlasi; geriye kalan az piksel
    # yuzunden bacaklar parcalaniyordu.
    #
    # Bu bir ayar meselesi degil, anatomik kisit: kafa tanimi geregi boynun
    # ustunde. Alta dusen pikseller EN YAKIN KAFA-DISI parcaya veriliyor.
    boyun_y = eklem["NECK"][1]
    alt = maskeler["kafa"] & (np.arange(rgba.shape[0])[:, None] > boyun_y)
    if alt.any():
        ys, xs = np.nonzero(alt)
        digerleri = [g for g in gecici if g["ad"] != "kafa"]
        uz = np.stack([
            rp.nokta_kemik_uzakligi(xs.astype(np.float64), ys.astype(np.float64),
                                    g["kemik"][0], g["kemik"][1]) / g["yaricap"]
            for g in digerleri])
        sahip = uz.argmin(axis=0)
        maskeler["kafa"][ys, xs] = False
        for i, g in enumerate(digerleri):
            s = sahip == i
            maskeler[g["ad"]][ys[s], xs[s]] = True

    parcalar = []
    for ad, ust, alt, ata, z in PARCA_SEMASI:
        a, b = eklem[ust], eklem[alt]
        ys, xs = np.nonzero(maskeler[ad])
        parcalar.append({
            "ad": ad, "ata": ata, "z": z,
            # Govde uzuvlari kaybedince ICINDE delik kaliyor: kol govdenin
            # onunde durdugu icin arkasindaki govde pikselleri duz goruntude
            # zaten yok. Uzuv donunce o delik siluete acik bir kesik olarak
            # giriyor. `kapat` satir satir en yakin opak komsuyla dolduruyor;
            # dis hat degismiyor, yalnizca ici doluyor. Uzuvlarda gerekmiyor,
            # onlar butun.
            "kapat": ad == "govde",
            # capa = kemigin UST ucu: uzuv oradan donuyor
            "capa": [round(a[0], 2), round(a[1], 2)],
            "kemik": [[round(a[0], 2), round(a[1], 2)],
                      [round(b[0], 2), round(b[1], 2)]],
            "yaricap": round(yaricap[ad], 2),
            "piksel": int(ys.size),
            # rect yalnizca BILGI icin: parcalara_bol artik `kemik` kullaniyor.
            # Elle duzenlemek isteyen icin sinirlari gorunur kalsin.
            "rect": ([int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
                     if ys.size else [0, 0, 0, 0]),
        })
    return {"yakin": yakin, "parcalar": parcalar,
            "eklem": {k: [round(v[0], 2), round(v[1], 2)] for k, v in eklem.items()}}


def _kemik_acisi(kp: dict, ust: str, alt: str) -> float:
    dx = kp[alt][0] - kp[ust][0]
    dy = kp[alt][1] - kp[ust][1]
    return math.atan2(dy, dx)


def poz_cevir(rig: dict, dinlenme: dict, hedef: dict,
              olcek: float = 1.0) -> dict:
    """Iki iskelet arasindaki farki PARCA ACISI listesine cevirir.

    `dinlenme` rig'in kuruldugu poz, `hedef` uretilmek istenen poz; ikisi de
    ayni birimde olmali (`olcek` hedefi dinlenmenin birimine tasir).

    ACI NEDEN ATAYA GORE: `rig_pose.zincir_matrisi` her parcanin donusumunu
    ATA zincirini carparak kuruyor — baldirin matrisine uyluğun donusu zaten
    girmis oluyor. Buraya mutlak farki yazsaydik uyluğun donusu baldira IKI
    kere uygulanirdi ve diz asiri bukulurdu."""
    d_ek = _turetilmis(dinlenme, rig["yakin"])
    h_ek = _turetilmis({k: (v[0] * olcek, v[1] * olcek) for k, v in hedef.items()},
                       rig["yakin"])

    fark = {}
    for ad, ust, alt, _, _ in PARCA_SEMASI:
        d = _kemik_acisi(h_ek, ust, alt) - _kemik_acisi(d_ek, ust, alt)
        fark[ad] = math.degrees(math.atan2(math.sin(d), math.cos(d)))  # (-180,180]

    ata = {p["ad"]: p["ata"] for p in rig["parcalar"]}
    cikti = {}
    for ad in fark:
        gorece = fark[ad] - (fark[ata[ad]] if ata[ad] else 0.0)
        cikti[ad] = {"aci": round(gorece, 2)}
    # Kok otelemesi: govde parcasi NECK farki kadar kayiyor. Kok hareketi
    # (yuruyus salinimi) sablonda zaten var, buraya oradan geliyor.
    cikti["govde"]["dx"] = round(h_ek["NECK"][0] - d_ek["NECK"][0], 2)
    cikti["govde"]["dy"] = round(h_ek["NECK"][1] - d_ek["NECK"][1], 2)
    return {"parcalar": cikti}


def main(argv=None):
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = argparse.ArgumentParser(
        description="Iskeletten kukla ve poz dosyasi turetir.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("sprite")
    p.add_argument("--frame", type=int, default=0)
    p.add_argument("--sablon", default=os.path.join(kok, "_data", "sablonlar.json"))
    p.add_argument("--klip", default="walk_right")
    p.add_argument("--yakin", choices=("RIGHT", "LEFT"), default="RIGHT",
                   help="Izleyiciye YAKIN taraf. Saga bakan bir karakteri onden "
                        "izlerken karakterin SAGI one gelir — varsayilan o.")
    p.add_argument("--model", default=None)
    p.add_argument("-o", "--out", required=True)
    args = p.parse_args(argv)

    import skeleton_edit as se
    rgba = sk.kareyi_al(args.sprite, args.frame, None)
    tahminci = se.Tahminci(args.model or se.en_guncel_model(kok))
    isk = tahminci(rgba, "east" if args.klip.endswith("_right") else "south")
    print(f"dinlenme pozu: {tahminci.ad}")

    rig = rig_uret(rgba, isk.noktalar, args.yakin)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "rig.json"), "w") as f:
        json.dump(rig, f, indent=1)
    print(f"\n{'parca':17s} {'piksel':>7s} {'yaricap':>8s}")
    for pr in rig["parcalar"]:
        print(f"  {pr['ad']:15s} {pr['piksel']:7d} {pr['yaricap']:8.1f}")
    bos = [pr["ad"] for pr in rig["parcalar"] if pr["piksel"] == 0]
    if bos:
        print(f"  UYARI: bos parca: {', '.join(bos)}")

    import poz_sablonu as ps
    with open(args.sablon) as f:
        sablon = json.load(f)[args.klip]
    b = max(rgba.shape[:2])
    dinlenme_n = {l: (x / b, y / b) for l, (x, y) in isk.noktalar.items()}
    pozlar = [poz_cevir(rig, isk.noktalar, ps.uygula(sablon, dinlenme_n, i), olcek=b)
              for i in range(sablon["kare_sayisi"])]
    with open(os.path.join(args.out, "poz.json"), "w") as f:
        json.dump(pozlar, f, indent=1)
    print(f"\n{len(pozlar)} poz -> {args.out}/poz.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
