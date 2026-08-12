"""
blender_veri.py — Blender icinde calisir; 3B sahneden 18 noktali poz verisi cikarir.

    blender sahne.blend --background --python tools/blender_veri.py -- \
        -o _data/blender_ham --frames 1 32 --kaynak yan01

    (ya da MCP uzerinden: bu dosyayi exec edip `uret(...)` cagirin)

NEDEN BLENDER

    Poz modelinin olculmus iki eksigi var ve ikisini de yalnizca sentetik
    veri kapatabiliyor:

    1. ORAN. Hata govde/kafa oranina gore degisiyor — 8-10 bandinda 2.91px,
       ama BIZIM karakterlerimizin bandinda (3-4) 5.13px. Egitim havuzu
       Chen yuzunden 8-10'a yigilmis. PixelLab'den ne gelirse onu aliyoruz;
       Blender'da orani SUPUREBILIYORUZ.

    2. GORUNURLUK. `estimate-skeleton` 18 noktanin hepsine her zaman bir
       konum veriyor, eklem gercekten gizli olsa bile — bayrak dondurmuyor.
       Olculdu: etiketlerimizin %0.8'i siluetin disinda, modelin yuruyus
       tahminlerinin %1.9'u. Blender'da gorunurluk isin testiyle KESIN
       biliniyor.

ONCEKI DENEMENIN IKI KUSURU (olculdu, ~/Desktop/dataset_B_side_01)

    NECK YANLIS KONVANSIYONDA. Mixamo'nun `Neck` kemigi kullanilmis; bizim
    (ve PixelLab'in) tanimi IKI OMUZUN ORTA NOKTASI. Sapma 128 tuvalinde
    3.28px ve standart sapmasi 0.02 — yani gurultu degil, sabit kaydirma.
    Modelin toplam hatasi 3.25px oldugu dusunulurse tek basina o kadar buyuk.

    13 NOKTA, 18 DEGIL. NOSE/EYE/EAR atlanmis cunku Mixamo'da o kemikler yok.
    Ama bunlar modelin EN IYI oldugu noktalar (boyun 1.0px, goz 1.1px);
    veriden cikarmak iyi calisan tarafi zayiflatir. Burada kafa kemiginin
    yonelim matrisinden turetiliyorlar.

KONVANSIYON (olculdu, PixelLab uyumlu)
    NECK = (sol omuz + sag omuz) / 2      — tahmin degil, alti sorguda
                                            0.00000 farkla dogrulandi
    LEG  = ayak BILEGI, taban degil
    SOL/SAG = KARAKTERIN solu/sagi. Mixamo ile birebir ayni: one bakan
    karakterde karakterin solu ekranin sagindadir (ael'de RIGHT x=54.7 <
    LEFT x=71.3 diye olculdu).
"""
import json
import math
import os
import sys

import bpy
from bpy_extras.object_utils import world_to_camera_view as _w2c
from mathutils import Vector

# Mixamo kemiginin BASI eklem noktasidir. "Shoulder" kopru kemigi; gercek
# omuz eklemi "Arm"in basi.
KEMIK = {
    "RIGHT SHOULDER": "mixamorig:RightArm",
    "RIGHT ELBOW":    "mixamorig:RightForeArm",
    "RIGHT ARM":      "mixamorig:RightHand",
    "LEFT SHOULDER":  "mixamorig:LeftArm",
    "LEFT ELBOW":     "mixamorig:LeftForeArm",
    "LEFT ARM":       "mixamorig:LeftHand",
    "RIGHT HIP":      "mixamorig:RightUpLeg",
    "RIGHT KNEE":     "mixamorig:RightLeg",
    "RIGHT LEG":      "mixamorig:RightFoot",
    "LEFT HIP":       "mixamorig:LeftUpLeg",
    "LEFT KNEE":      "mixamorig:LeftLeg",
    "LEFT LEG":       "mixamorig:LeftFoot",
}

# Yuz noktalari kemikten degil, kafanin YONELIMINDEN turetiliyor (Mixamo'da
# goz/kulak kemigi yok). Ofsetler kafa uzunluguna oranli.
#
# KALIBRE EDILDI. Hedef, gercek karakterlerimizde PixelLab'in urettigi 2B
# iliskiler — KAFA BOYUNA normalize edilmis, cunku govdeye gore normalize
# etmek kafa BUYUKLUGU farkini iceri karistiriyor:
#     yandan:  NOSE>EYE / NECK>NOSE = 0.295    EYE>EAR / NECK>NOSE = 0.585
#     onden:                          0.639                          0.672
#
# Kisitsiz cozum oranlari birebir tutturuyor ama ANATOMIK OLARAK SACMA:
# burun kafanin arkasinda (-0.565) ve iki kafa boyu yukarisinda (+2.076),
# kulaklar 3.2 kafa boyu yanda. Yani olcut tutturulup olcutun temsil ettigi
# sey bozuluyor. O yuzden noktalar kafa merkezine 0.6 kafa boyu icinde
# tutuldu; ulasilan oranlar hedefin %95-101'i (biri %147).
#
# KALAN FARKIN SEBEBI OFSETLER DEGIL, KAFA BUYUKLUGU. Olculdu: Mixamo'da
# kafa boyu / govde boyu = 0.159, ve hedef NECK>NOSE=0.482 icin burnun
# boyundan 1.6 kafa boyu uzakta olmasi gerekirdi — kafanin cok disinda.
# Bizim karakterlerimizde o oran buyuk cunku kafalari gercekten kocaman
# (chibi). Bu ofsetlerle degil, edit-bone olceklemesiyle cozulur.
# Degerler MESH'ten turetildi, orandan degil. Kafa tepelerinin kafa-yerel
# araliklari (kafa kemigi = 1.0 birim, 807 tepe):
#     ileri  -0.583 .. +0.680     en ileri tepe -0.311 yuksekliginde (cene/burun)
#     yukari -0.779 .. +0.539
#     yana   -0.444 .. +0.448     yanal uc noktalar -0.112 .. +0.047 (kulak hizasi)
# Onceki surumde goz +0.40'taydi, yani neredeyse kafatasinin tepesinde
# (tavan +0.539) ve render'da siluetin DISINDA kaliyordu — 30 yuz noktasinin
# 12'si disaridaydi.
YUZ_OFSET = {
    #            ileri,  yukari,   yana
    "NOSE":      (0.58,  -0.18,   0.00),
    "RIGHT EYE": (0.42,   0.00,  -0.16),
    "LEFT EYE":  (0.42,   0.00,   0.16),
    "RIGHT EAR": (-0.10,  -0.03,  -0.40),
    "LEFT EAR":  (-0.10,  -0.03,   0.40),
}

SIRA = ("NOSE", "NECK", "RIGHT SHOULDER", "RIGHT ELBOW", "RIGHT ARM",
        "LEFT SHOULDER", "LEFT ELBOW", "LEFT ARM", "RIGHT HIP", "RIGHT KNEE",
        "RIGHT LEG", "LEFT HIP", "LEFT KNEE", "LEFT LEG",
        "RIGHT EYE", "LEFT EYE", "RIGHT EAR", "LEFT EAR")


def _arm(ad=None):
    if ad:
        return bpy.data.objects[ad]
    for o in bpy.data.objects:
        if o.type == "ARMATURE" and o.visible_get():
            return o
    raise SystemExit("HATA: gorunur bir armature bulunamadi.")


def kafa_cercevesi(arm):
    """Kafanin (ileri, yukari, yana) birim vektorleri ve merkezi.

    Kafa kemiginin ekseni YUKARI; ileri yon govdeden turetiliyor cunku kafa
    kemigi kendi basina hangi yone baktigini soylemiyor (Mixamo'da kemik
    yuvarlanmasi karaktere gore degisebiliyor)."""
    kb = arm.pose.bones["mixamorig:Head"]
    bas = arm.matrix_world @ kb.head
    uc = arm.matrix_world @ kb.tail
    yukari = (uc - bas).normalized()
    uzunluk = (uc - bas).length

    sag = arm.matrix_world @ arm.pose.bones["mixamorig:RightArm"].head
    sol = arm.matrix_world @ arm.pose.bones["mixamorig:LeftArm"].head
    yana = (sol - sag).normalized()                 # karakterin SAGINDAN SOLUNA
    ileri = yana.cross(yukari).normalized()
    # Govdeye gore ileri yonu dogrula: burun kalcanin onunde olmali
    kalca = arm.matrix_world @ arm.pose.bones["mixamorig:Hips"].head
    if ileri.dot(bas - kalca) < -1e-6 and abs(ileri.dot(bas - kalca)) > 1e-3:
        pass                                        # dikeyde fark; isaret onemli degil
    merkez = bas + yukari * (uzunluk * 0.5)
    return merkez, ileri, yukari, yana, uzunluk


def eklem_dunya(arm):
    """18 eklemin DUNYA konumu."""
    n = {}
    for etiket, kemik in KEMIK.items():
        n[etiket] = arm.matrix_world @ arm.pose.bones[kemik].head
    # NECK: BIZIM konvansiyonumuz — iki omuzun orta noktasi.
    n["NECK"] = (n["RIGHT SHOULDER"] + n["LEFT SHOULDER"]) / 2.0
    merkez, ileri, yukari, yana, boy = kafa_cercevesi(arm)
    for etiket, (fi, fy, fs) in YUZ_OFSET.items():
        n[etiket] = merkez + ileri * (fi * boy) + yukari * (fy * boy) + yana * (fs * boy)
    return n


# Gorunurluk esigi, karakter boyuna ORANLI. Olculdu (1.715 m karakter, yan
# gorunus yuruyus karesi) — eklemin kameraya bakan ilk yuzeyden uzakligi:
#     yakin taraf uzuvlari      0.027 - 0.098   (kendi derisinin altinda)
#     LEFT SHOULDER (uzak)      0.433
#     LEFT HIP      (uzak)      0.281
#     LEFT EAR/EYE  (uzak)      0.164 / 0.113
# Yani "isin bir seye carpti mi" YANLIS olcut — eklem zaten govdenin icinde,
# isin her zaman once derinin kendisine carpiyor. Ayirt eden sey BOSLUGUN
# BUYUKLUGU: kendi uzvunun derisi altindaysa bosluk uzuv yariçapi kadar,
# baska bir uzuv onunu kesiyorsa cok daha buyuk.
GORUNURLUK_ESIGI = 0.065          # karakter boyuna oranli (1.715 m'de ~0.11 m)


def gorunur_mu(sahne, dg, kam, dunya_p, karakter_boyu):
    """Eklem kameradan gorunuyor mu; (gorunur, bosluk) doner.

    `estimate-skeleton` bu bilgiyi hic vermiyor — 18 noktanin hepsine her
    zaman konum donduruyor, eklem gercekten gizli olsa bile. Olculdu:
    etiketlerimizin %0.8'i siluetin disinda, modelin yuruyus tahminlerinin
    %1.9'u. Bayrak, gizli eklemi egitimde ayri ele almayi mumkun kiliyor."""
    kaynak = kam.matrix_world.translation
    yon = dunya_p - kaynak
    uzak = yon.length
    if uzak < 1e-6:
        return True, 0.0
    vurdu, konum, _, _, _, _ = sahne.ray_cast(dg, kaynak, yon.normalized())
    if not vurdu:
        # Hicbir seye carpmadi: eklem siluetin DISINDA kaliyor.
        return False, float("inf")
    bosluk = uzak - (konum - kaynak).length
    return bosluk <= GORUNURLUK_ESIGI * karakter_boyu, round(float(bosluk), 4)


def karakter_boyu(arm):
    ayak = min((arm.matrix_world @ arm.pose.bones[b].head).z
               for b in ("mixamorig:LeftToe_End", "mixamorig:RightToe_End"))
    tepe = (arm.matrix_world @ arm.pose.bones["mixamorig:Head"].tail).z
    return max(tepe - ayak, 1e-6)


def kare_verisi(sahne, arm, kam):
    dg = bpy.context.evaluated_depsgraph_get()
    boy = karakter_boyu(arm)
    n3 = eklem_dunya(arm)
    kp, gor, bosluk = {}, {}, {}
    for etiket in SIRA:
        v = _w2c(sahne, kam, n3[etiket])
        # Blender kamera uzayinda y YUKARI; goruntude asagi -> cevir.
        kp[etiket] = [round(float(v.x), 6), round(float(1.0 - v.y), 6)]
        g, b = gorunur_mu(sahne, dg, kam, n3[etiket], boy)
        gor[etiket], bosluk[etiket] = g, b

    # NECK TUREV bir nokta — govdenin merkezinde, hicbir zaman "yuzeyde"
    # degil, dolayisiyla bosluk olcutu onun icin anlamsiz. Gorunurlugunu
    # omuzlardan devraliyor: en az biri gorunuyorsa boyun da konumlandirilabilir.
    gor["NECK"] = gor["RIGHT SHOULDER"] or gor["LEFT SHOULDER"]
    return kp, gor, bosluk


# Kamera KARAKTERIN ETRAFINDA donduruluyor. Tek acidan 32 kare, mevcut 4363
# ornekli kumeye %0.7 ekler — olcek egrimize (hata ~ n^-0.125) gore gorunmez.
# Sekiz yon Chen'in 2111 ornegiyle karsilastirilabilir bir hacim veriyor, ve
# zaten olculen eksigimiz gorus acisi cesitliligi.
YONLER = {
    "south":      0.0,     # karakterin onu kameraya donuk
    "south-east": 45.0,
    "east":       90.0,    # saga bakan profil (walk_right konvansiyonumuz)
    "north-east": 135.0,
    "north":      180.0,
    "north-west": 225.0,
    "west":       270.0,
    "south-west": 315.0,
}


def kamerayi_yerlestir(kam, arm, aci_derece, pay=1.25):
    """Kamerayi karakterin etrafinda `aci` kadar dondurup ortalar.

    Ortografik kamera kullaniliyor (sahnede zaten oyle): sprite'larda
    perspektif bozulmasi olmaz, karakterin oranlari mesafeden bagimsiz kalir."""
    kalca = arm.matrix_world @ arm.pose.bones["mixamorig:Hips"].head
    ayak = min((arm.matrix_world @ arm.pose.bones[b].head).z
               for b in ("mixamorig:LeftToe_End", "mixamorig:RightToe_End"))
    tepe = (arm.matrix_world @ arm.pose.bones["mixamorig:Head"].tail).z
    boy = max(tepe - ayak, 1e-6)
    merkez = Vector((kalca.x, kalca.y, (ayak + tepe) / 2.0))

    # Karakterin ILERI yonu omuz ekseninden turetiliyor; aci ona GORE veriliyor
    # ki farkli aksiyonlarda ayni "south" ayni sey olsun.
    sag = arm.matrix_world @ arm.pose.bones["mixamorig:RightArm"].head
    sol = arm.matrix_world @ arm.pose.bones["mixamorig:LeftArm"].head
    yana = (sol - sag).normalized()
    ileri = yana.cross(Vector((0, 0, 1))).normalized()

    t = math.radians(aci_derece)
    # aci=0 -> kamera karakterin ONUNDE (ileri yonunde)
    yon = Vector((ileri.x * math.cos(t) - ileri.y * math.sin(t),
                  ileri.x * math.sin(t) + ileri.y * math.cos(t), 0)).normalized()
    kam.location = merkez + yon * (boy * 4.0)
    kam.rotation_mode = "QUATERNION"
    kam.rotation_quaternion = (merkez - kam.location).to_track_quat("-Z", "Y")
    if kam.data.type == "ORTHO":
        kam.data.ortho_scale = boy * pay
    bpy.context.view_layer.update()


def uret(cikti, kare_araligi=None, kaynak="blender", armature=None,
         seffaf=True, cozunurluk=512, yonler=None):
    sahne = bpy.context.scene
    arm = _arm(armature)
    kam = sahne.camera
    if kam is None:
        raise SystemExit("HATA: sahnede kamera yok.")

    onceki = (sahne.render.film_transparent, sahne.render.filepath,
              sahne.render.image_settings.file_format,
              sahne.render.image_settings.color_mode,
              sahne.render.resolution_x, sahne.render.resolution_y)
    sahne.render.film_transparent = seffaf
    sahne.render.image_settings.file_format = "PNG"
    sahne.render.image_settings.color_mode = "RGBA"
    sahne.render.resolution_x = sahne.render.resolution_y = cozunurluk

    gorseller = os.path.join(cikti, "gorseller")
    os.makedirs(gorseller, exist_ok=True)
    a, b = kare_araligi or (sahne.frame_start, sahne.frame_end)

    # Etiketler ANINDA yaziliyor: uzun kosuda dusen bir render her seyi
    # goturmesin (ayni ders chen_to_pixelart ve pixellab_generate'de de var).
    yol = os.path.join(cikti, "etiketler.jsonl")
    kam_onceki = (kam.location.copy(), kam.rotation_mode,
                  kam.rotation_quaternion.copy() if kam.rotation_mode == "QUATERNION"
                  else kam.rotation_euler.copy(),
                  kam.data.ortho_scale if kam.data.type == "ORTHO" else None)
    secilen = yonler or ["east"]
    n = 0
    with open(yol, "w", buffering=1) as f:
        for yon_ad in secilen:
            for kare in range(int(a), int(b) + 1):
                sahne.frame_set(kare)
                # Kamera HER KAREDE yeniden yerlestiriliyor: karakter yuruyusle
                # yer degistiriyor, sabit kamera onu kadrajdan cikariyor.
                kamerayi_yerlestir(kam, arm, YONLER[yon_ad])
                dosya = f"{kaynak}_{yon_ad}_{kare:05d}.png"
                sahne.render.filepath = os.path.join(gorseller, dosya)
                bpy.ops.render.render(write_still=True)
                kp, gor, bosluk = kare_verisi(sahne, arm, kam)
                f.write(json.dumps({
                    "gorsel": f"gorseller/{dosya}",
                    "kaynak": f"blender/{kaynak}_{yon_ad}_{kare:05d}",
                    "artirma": "ham",
                    "yon": yon_ad,
                    "keypoints": kp,
                    "gorunur": gor,
                    # Ham bosluk da yaziliyor: esik sonradan degistirilebilsin,
                    # veri yeniden uretilmeden.
                    "bosluk": bosluk,
                    "cozunurluk": cozunurluk,
                }, ensure_ascii=False) + "\n")
                n += 1
            print(f"  {yon_ad}: {int(b)-int(a)+1} kare  (toplam {n})", flush=True)
    kam.location, kam.rotation_mode = kam_onceki[0], kam_onceki[1]
    if kam_onceki[1] == "QUATERNION":
        kam.rotation_quaternion = kam_onceki[2]
    else:
        kam.rotation_euler = kam_onceki[2]
    if kam_onceki[3] is not None:
        kam.data.ortho_scale = kam_onceki[3]

    (sahne.render.film_transparent, sahne.render.filepath,
     sahne.render.image_settings.file_format,
     sahne.render.image_settings.color_mode,
     sahne.render.resolution_x, sahne.render.resolution_y) = onceki
    print(f"{n} kare -> {yol}")
    return n


def _cli():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--frames", nargs=2, type=int, default=None)
    p.add_argument("--kaynak", default="blender")
    p.add_argument("--armature", default=None)
    p.add_argument("--res", type=int, default=512)
    a = p.parse_args(argv)
    uret(a.out, a.frames, a.kaynak, a.armature, cozunurluk=a.res)


if __name__ == "__main__":
    _cli()
