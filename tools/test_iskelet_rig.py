#!/usr/bin/env python3
"""iskelet_rig.py testleri."""
from __future__ import annotations

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import iskelet_rig as ir  # noqa: E402
import rig_pose as rp     # noqa: E402

gecti = basarisiz = 0


def kontrol(ad: str, kosul: bool, ek: str = ""):
    global gecti, basarisiz
    if kosul:
        gecti += 1
        print(f"  ok   {ad}")
    else:
        basarisiz += 1
        print(f"  HATA {ad}" + (f" — {ek}" if ek else ""))


def cop_adam() -> tuple[np.ndarray, dict]:
    """Basit bir yandan cop adam: 60x100 tuval, kollar ve bacaklar ayrik.

    Uzuvlarin AYRIK olmasi bilerek: bu testin konusu atama mantigi, gercek
    bir sprite'ta uzuvlarin ust uste binmesi ayri bir sorun."""
    im = np.zeros((100, 60, 4), np.uint8)

    def ciz(a, b, kalinlik, renk):
        ys, xs = np.mgrid[0:100, 0:60]
        d = rp.nokta_kemik_uzakligi(xs.astype(float), ys.astype(float), a, b)
        m = d.reshape(100, 60) <= kalinlik
        im[m] = renk

    kp = {
        "NOSE": (30, 14), "LEFT EYE": (32, 13), "RIGHT EYE": (28, 13),
        "LEFT EAR": (26, 14), "RIGHT EAR": (25, 14),
        "NECK": (30, 26),
        "LEFT SHOULDER": (30, 28), "RIGHT SHOULDER": (30, 28),
        "LEFT ELBOW": (22, 42), "RIGHT ELBOW": (38, 42),
        "LEFT ARM": (18, 56), "RIGHT ARM": (42, 56),
        "LEFT HIP": (30, 56), "RIGHT HIP": (30, 56),
        "LEFT KNEE": (22, 74), "RIGHT KNEE": (38, 74),
        "LEFT LEG": (20, 92), "RIGHT LEG": (40, 92),
    }
    ciz(kp["NECK"], kp["LEFT HIP"], 7, (90, 90, 200, 255))      # govde (kalin)
    ciz((30, 20), (30, 6), 11, (200, 170, 140, 255))            # kafa
    for u, a, renk in ((("LEFT SHOULDER", "LEFT ELBOW"), ("LEFT ELBOW", "LEFT ARM"),
                        (200, 90, 90, 255)),
                       (("RIGHT SHOULDER", "RIGHT ELBOW"), ("RIGHT ELBOW", "RIGHT ARM"),
                        (90, 200, 90, 255)),
                       (("LEFT HIP", "LEFT KNEE"), ("LEFT KNEE", "LEFT LEG"),
                        (200, 200, 90, 255)),
                       (("RIGHT HIP", "RIGHT KNEE"), ("RIGHT KNEE", "RIGHT LEG"),
                        (200, 90, 200, 255))):
        ciz(kp[u[0]], kp[u[1]], 4, renk)
        ciz(kp[a[0]], kp[a[1]], 3, renk)
    return im, kp


# --- turetilmis eklemler ----------------------------------------------------
_, KP = cop_adam()
d = ir._turetilmis(KP, "RIGHT")
kontrol("KALCA iki kalcanin ortasi",
        d["KALCA"] == (30.0, 56.0), str(d["KALCA"]))
kontrol("BAS NECK'in uzerinde", d["BAS"][1] < KP["NECK"][1] and d["BAS"][0] == KP["NECK"][0])
kontrol("yakin=RIGHT ise YAKIN ELBOW sag dirsek", d["YAKIN ELBOW"] == KP["RIGHT ELBOW"])
kontrol("yakin=RIGHT ise UZAK ELBOW sol dirsek", d["UZAK ELBOW"] == KP["LEFT ELBOW"])
ds = ir._turetilmis(KP, "LEFT")
kontrol("yakin=LEFT tarafi ters cevirir",
        ds["YAKIN ELBOW"] == KP["LEFT ELBOW"] and ds["UZAK ELBOW"] == KP["RIGHT ELBOW"])

# --- kemik uzakligi ---------------------------------------------------------
# Dirsegin OTESINDEKI nokta ust kolun dogrultusuna yakin ama parcaya uzak
# olmali: sonsuz dogru kullanilsaydi 0 cikardi ve el ust kola atanirdi.
p = np.array([0.0]), np.array([20.0])
kontrol("uzaklik dogruya degil PARCAYA olculuyor",
        abs(rp.nokta_kemik_uzakligi(p[0], p[1], (0, 0), (0, 10))[0] - 10.0) < 1e-9,
        str(rp.nokta_kemik_uzakligi(p[0], p[1], (0, 0), (0, 10))[0]))

# --- yaricap agirligi -------------------------------------------------------
# Iki kemige ESIT uzaklikta bir piksel, yaricapi BUYUK olana gitmeli.
im2 = np.zeros((3, 3, 4), np.uint8)
im2[1, 1] = (255, 255, 255, 255)
esit = [{"ad": "ince", "kemik": [(1, 0), (1, 0)], "yaricap": 1.0},
        {"ad": "kalin", "kemik": [(1, 2), (1, 2)], "yaricap": 5.0}]
m = rp.kemige_gore_bol(im2, esit)
kontrol("esit uzaklikta kalin kemik kazaniyor", bool(m["kalin"][1, 1]) and not m["ince"][1, 1])

# --- rig uretimi ------------------------------------------------------------
IM, _ = cop_adam()
rig = ir.rig_uret(IM, KP, "RIGHT")
adlar = [p["ad"] for p in rig["parcalar"]]
kontrol("on parca uretiliyor", len(rig["parcalar"]) == 10, str(len(rig["parcalar"])))
kontrol("hicbir parca bos degil",
        all(p["piksel"] > 0 for p in rig["parcalar"]),
        ", ".join(p["ad"] for p in rig["parcalar"] if p["piksel"] == 0))
kontrol("her opak piksel tam bir kez atandi",
        sum(p["piksel"] for p in rig["parcalar"]) == int((IM[:, :, 3] > 0).sum()),
        f'{sum(p["piksel"] for p in rig["parcalar"])} vs {int((IM[:,:,3]>0).sum())}')
kontrol("govde kemigi kalin cizildi, yaricapi uzuvlardan buyuk",
        next(p for p in rig["parcalar"] if p["ad"] == "govde")["yaricap"]
        > next(p for p in rig["parcalar"] if p["ad"] == "yakin_alt_kol")["yaricap"])
kontrol("ata zinciri kapali",
        all(p["ata"] is None or p["ata"] in adlar for p in rig["parcalar"]))
kontrol("yalnizca govdede kapat acik",
        [p["ad"] for p in rig["parcalar"] if p.get("kapat")] == ["govde"])

# --- poz cevirisi -----------------------------------------------------------
ayni = ir.poz_cevir(rig, KP, KP)["parcalar"]
kontrol("ayni poz -> tum acilar sifir",
        all(abs(v["aci"]) < 1e-6 for v in ayni.values()),
        str({k: v["aci"] for k, v in ayni.items() if abs(v["aci"]) >= 1e-6}))
kontrol("ayni poz -> kok otelemesi sifir",
        abs(ayni["govde"]["dx"]) < 1e-6 and abs(ayni["govde"]["dy"]) < 1e-6)

# Uyluk 30 derece donsun, baldir ONUNLA gitsin (diz bukulmesin). Zincir
# matrisi ataninkini zaten uyguladigi icin baldirin KENDI acisi 0 olmali.
# Bu yanlis olsaydi diz her poz uygulamasinda iki kat bukulurdu.
hedef = dict(KP)
aci = math.radians(30)
hx, hy = KP["RIGHT HIP"]
for eklem in ("RIGHT KNEE", "RIGHT LEG"):
    x, y = KP[eklem][0] - hx, KP[eklem][1] - hy
    hedef[eklem] = (hx + x * math.cos(aci) - y * math.sin(aci),
                    hy + x * math.sin(aci) + y * math.cos(aci))
c = ir.poz_cevir(rig, KP, hedef)["parcalar"]
kontrol("uyluk donusu 30 derece olculuyor",
        abs(c["yakin_ust_bacak"]["aci"] - 30) < 0.01, str(c["yakin_ust_bacak"]["aci"]))
kontrol("baldirin acisi ATAYA gore (rijit donuste 0)",
        abs(c["yakin_alt_bacak"]["aci"]) < 0.01, str(c["yakin_alt_bacak"]["aci"]))
kontrol("dokunulmayan uzuv etkilenmiyor",
        abs(c["uzak_ust_bacak"]["aci"]) < 0.01, str(c["uzak_ust_bacak"]["aci"]))

# --- kukla gercekten cizilebiliyor mu ---------------------------------------
kare = rp.poz_uret(IM, ir.rig_uret(IM, KP, "RIGHT"), {"parcalar": c})
a = np.array(kare)[:, :, 3] > 0
kontrol("kukla bos cikmiyor", a.sum() > 0.5 * (IM[:, :, 3] > 0).sum(),
        f"{int(a.sum())} vs {int((IM[:,:,3]>0).sum())}")

print("\n" + "=" * 50)
print(f"{gecti} gecti, {basarisiz} basarisiz")
sys.exit(1 if basarisiz else 0)
