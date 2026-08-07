#!/usr/bin/env python3
"""
pixellab_generate.py — poz modeli icin PixelLab'e CESITLI karakterler urettirir.

    ~/ComfyUI/venv/bin/python tools/pixellab_generate.py --count 20 -o _data/uretim

NEDEN BU KAYNAK VAR
    Chen'in veri seti bedava ve poz cesitliligi yuksek, ama IN-DOMAIN degil:
    anime illustrasyonun pixelize edilmis hali, gercek pixel art'in kendisi
    degil. Bu arac hedef alanin ta kendisini uretiyor — gercek pixel art,
    seffaf zeminli, tek karakter, sabit tuval.

MALIYET (olculdu)
    Uretim 1.0 generation/gorsel, etiketleme 0.1 -> etiketli ornek basina
    1.1. Chen'de bu 0. Yani burasi HACIM kaynagi degil KALITE kaynagi;
    karisimin in-domain ayagini olusturur.

CESITLILIK NASIL SAGLANIYOR
    Poz modelinin genellemesi gereken sey CIZIM TARZI, o yuzden cesitlilik
    rastgele metinle degil eksen eksen kuruluyor: govde orani, kiyafet, sac,
    ve PixelLab'in kendi stil kollari (outline / shading / detail). Ozellikle
    govde orani onemli — hazir OpenPose'un bizde en cok zorlandigi sey chibi
    orandi (mag'de 8/18 eklem, 11.4px), yani modelin genis bir oran araligi
    gormesi gerekiyor.

    Poz SABIT: onden bakan, kollar yanda temel duruş. Poz cesitliligini
    Chen'in verisi sagliyor; buradan istedigimiz sey tarz cesitliligi.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import time

import numpy as np
import requests
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pose_dataset as pdset  # noqa: E402

UC = "https://api.pixellab.ai/v2/create-image-pixflux"
URETIM_BASI = 1.0        # olculdu: bakiye 33.7 -> 32.7

GOVDE = ["slim adult", "stocky adult", "tall lanky adult", "short chibi child",
         "muscular adult", "petite young adult", "heavyset adult",
         "very short chibi character with large head"]
KIYAFET = ["green jacket and boots", "red hoodie and jeans", "blue dress",
           "brown leather armor", "white lab coat", "black suit and tie",
           "orange overalls", "purple robe", "yellow raincoat",
           "grey sweater and shorts", "striped shirt and sandals",
           "teal tracksuit"]
SAC = ["short brown hair", "long blonde hair", "black ponytail", "red curly hair",
       "bald", "white long hair", "blue short bob", "green messy hair",
       "grey beard and short hair", "pink twin tails"]
KONTUR = ["single color black outline", "selective outline", "lineless"]
GOLGE = ["flat shading", "basic shading", "medium shading", "detailed shading"]
AYRINTI = ["low detail", "medium detail", "highly detailed"]


# HEDEFLI havuz. Olculdu: hata ortalamasi tek bir karakterin omzunda —
# faküs 6.47px, digerleri 2.92-3.87. faküs'un tarzi egitim dagiliminda
# temsil edilmiyor ve onu ayirt eden ozellikler tam da tespiti zorlastiran
# seyler:
#   - uzun/ince govde (en az chibi olan)
#   - omuzlara inen uzun sac  -> boyun cukurunu yok ediyor
#   - bol paca / akiskan kiyafet -> bacaklar siluette birlesiyor
#   - koyu goz -> sclera sinyali yok
# Genel karakter almak yerine bu bolgeyi doldurmak daha verimli olmali.
#
# ILK SURUM YANLISTI ve olculdu: ORTME ozelliklerini istemek ("hooded head",
# "cloak covering the shoulders", "robe reaching the floor") yuzu tamamen
# kapali figurler uretti — hedefli partide gozu tespit edilebilen oran %38,
# genel partide %82, gercek karakterlerimizde 5'te 4. Cikarimda hep yuzu
# gorunen karakter kullanacagiz, yani o dagilim hic karsilasmayacagimiz bir
# sey; ustelik yuzu olmayan figurde etiketleyicinin goz/burun/kulak icin
# dayanacagi sinyal de yok.
#
# Istenmesi gereken sey faküs GIBI KARAKTERLER: yuzu gorunen, uzun sacli,
# ince govdeli, bol pacali. Ortme kelimeleri cikarildi, yuzun gorunur olmasi
# acikca istendi ve ayrica KAPIYLA zorlaniyor (bkz. kabul_edilebilir).
ZOR_GOVDE = ["tall slim adult", "very tall lanky adult", "tall thin teenager",
             "slender tall adult with long limbs"]
ZOR_KIYAFET = ["wide-leg baggy trousers and tank top",
               "long dress down to the ankles",
               "long open coat and wide trousers",
               "wide palazzo pants and t-shirt",
               "flowing long skirt and blouse",
               "loose jumpsuit with wide legs"]
ZOR_SAC = ["long straight hair past the shoulders",
           "long wavy hair down to the waist",
           "long ponytail and visible face",
           "shoulder-length hair with visible face"]


def istem(rng: np.random.Generator, odak: str = "genel") -> tuple[str, dict]:
    """Bir karakter tarifi ve stil kollari uretir.

    `odak='zor'` dagilimin eksik kalan bolgesini hedefler (bkz. ZOR_* )."""
    if odak == "zor":
        govde, kiyafet, sac = ZOR_GOVDE, ZOR_KIYAFET, ZOR_SAC
    else:
        govde, kiyafet, sac = GOVDE, KIYAFET, SAC
    tarif = (f"full body pixel art character, {rng.choice(govde)}, "
             f"{rng.choice(kiyafet)}, {rng.choice(sac)}, "
             "standing straight, arms down at sides, facing the viewer, "
             "face clearly visible, front view, "
             "full body visible from head to feet")
    return tarif, {"outline": str(rng.choice(KONTUR)),
                   "shading": str(rng.choice(GOLGE)),
                   "detail": str(rng.choice(AYRINTI))}


def uret(gizli: str, tarif: str, stil: dict, boyut: int, tohum: int,
         deneme: int = 3) -> np.ndarray | None:
    govde = {"description": tarif,
             "image_size": {"width": boyut, "height": boyut},
             "view": "side", "direction": "south", "no_background": True,
             "seed": int(tohum), **stil}
    for i in range(deneme):
        try:
            r = requests.post(UC, headers={"Authorization": f"Bearer {gizli}"},
                              json=govde, timeout=300)
            r.raise_for_status()
            b = r.json()["image"]["base64"]
            return np.array(Image.open(io.BytesIO(base64.b64decode(b))).convert("RGBA"))
        except requests.RequestException as err:
            if i == deneme - 1:
                print(f"    uretim basarisiz: {str(err)[:90]}", file=sys.stderr)
            time.sleep(3 * (i + 1))
    return None


KAFA_AYRINTI_ESIGI = 20


def kafa_ayrintisi(rgba: np.ndarray, tol: int = 24, en_az: int = 3) -> int:
    """Kafa bolgesindeki ayri renk adaciklarinin sayisi.

    YUZUN GORUNUR OLUP OLMADIGINI olcuyor. Gerekli, cunku uretim bazen sirti
    donuk ya da kapusonla ortulmus figur veriyor; cikarimda hep one bakan
    karakter kullanacagiz ve yuzu olmayan figurde etiketleyicinin
    goz/burun/kulak icin dayanacagi sinyal de yok — o etiketler tahmin olur.

    Neden BU olcut: "sclera var mi" diye bakmak yanlis olurdu, cunku faküs'un
    de sclera'si yok ve o tam da tutmak istedigimiz karakter. `yuz_bolgesi`
    de yetmiyor — kapusonlu figurde "ust yaridaki en buyuk bolge" kapusonun
    kendisi cikiyor. Gorunur bir yuz ise IC AYRINTI demek: goz, agiz, burun
    ayri renk adaciklari uretiyor; kapusonlu ya da arkadan gorunen kafa duz
    bir kutle.

    Olculdu: gercek bes karakterimiz 50-87 adacik; uretimin genel havuzu
    medyan 58 (%10 dilim 19); ortme kelimeleriyle uretilen hedefli parti
    medyan 36 ve %10 dilim 9, en dusugu 1. Esik ikisinin arasina, 20'ye
    konuldu — gercek karakterlerin hepsinin comfortably altinda."""
    from pixelart_extract import label_components, merge_near_colors, pack_rgb

    opak = rgba[:, :, 3] > 0
    ys, _ = np.where(opak)
    if ys.size == 0:
        return 0
    y0, y1 = int(ys.min()), int(ys.max())
    kafa = opak.copy()
    kafa[y0 + int(0.45 * (y1 - y0)):, :] = False
    if kafa.sum() < 40:
        return 0
    temiz = rgba.copy()
    temiz[~kafa] = 0
    anah = pack_rgb(merge_near_colors(temiz, tol)[:, :, :3])
    n = 0
    for v in np.unique(anah[kafa]):
        etiket, k = label_components((anah == v) & kafa)
        for i in range(1, k + 1):
            if int((etiket == i).sum()) >= en_az:
                n += 1
    return n


def kabul_edilebilir(rgba: np.ndarray, yuz_kapisi: bool = False) -> tuple[bool, str]:
    """Uretilen gorsel egitim verisi olmaya uygun mu?

    Uretim her zaman istedigimizi vermiyor: bazen karakter tuvale sigmiyor,
    bazen zemin ayrilmamis, bazen figur cok kucuk kaliyor. Etiketlemeden
    ONCE eleniyor — cunku etiketleme ayrica ucretli."""
    opak = rgba[:, :, 3] > 0
    oran = float(opak.mean())
    if oran < 0.05:
        return False, "cok kucuk"
    if oran > 0.60:
        return False, "zemin ayrilmamis"
    ys, xs = np.where(opak)
    h, w = rgba.shape[:2]
    # Karakter kenara dayanmissa govde kirpilmis demektir
    if ys.min() <= 0 and ys.max() >= h - 1:
        return False, "dikeyde kirpilmis"
    boy = (ys.max() - ys.min() + 1) / h
    if boy < 0.45:
        return False, "figur kisa kalmis"

    # YUZ KAPISI VARSAYILAN OLARAK KAPALI. Sirti donuk figurleri gercekten
    # yakaliyor, ama olculdu (2026-08-07, dort holdout, son epok): kapiyi
    # acinca 60->53 karakterde hata 4.35 -> 4.50px, 94->76'da 4.33 -> 4.37px.
    # Yani iyilestirmiyor. Sebebi muhtemelen su: eledigi veri, gurultusunden
    # daha degerli — veri miktarinin kazandirdigi olculmus bir sey
    # (0/26/60 karakter -> 5.62/4.66/4.10px). Ustelik kapi uretimden SONRA
    # calisiyor, yani ucret zaten odenmis oluyor.
    if yuz_kapisi and kafa_ayrintisi(rgba) < KAFA_AYRINTI_ESIGI:
        return False, "yuz gorunmuyor"
    return True, ""


def main(argv=None):
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = argparse.ArgumentParser(
        description="PixelLab ile cesitli egitim karakterleri uretir ve etiketler.")
    p.add_argument("-o", "--output", default=os.path.join(kok, "_data", "uretim"))
    p.add_argument("--count", type=int, default=10, help="Kac karakter uretilsin")
    p.add_argument("--canvas", type=int, default=128, choices=(64, 128))
    p.add_argument("--augment", type=int, default=6)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--focus", choices=("genel", "zor"), default="genel",
                   help="zor = dagilimin eksik bolgesi (uzun/ince govde, uzun "
                        "sac, bol paca) — faküs benzeri tarzlar")
    p.add_argument("--yuz-kapisi", action="store_true",
                   help="Yuzu gorunmeyen (sirti donuk/kapusonlu) figurleri de "
                        "ele. Olculdu: egitimi IYILESTIRMIYOR, o yuzden kapali.")
    p.add_argument("--dry-run", action="store_true", help="Maliyeti soyle, uretme")
    args = p.parse_args(argv)

    gizli = pdset.anahtar_oku(kok)
    kalan, toplam = pdset.bakiye(gizli)
    tahmin = args.count * (URETIM_BASI + pdset.CAGRI_BASI)
    print(f"{args.count} karakter -> tahmini {tahmin:.1f} generation "
          f"(bakiye {kalan:.1f}/{toplam:.0f})")
    if tahmin > kalan:
        print("HATA: bakiye yetmiyor. --count azaltin.", file=sys.stderr)
        return 1
    if args.dry_run:
        return 0

    gorseller = os.path.join(args.output, "gorseller")
    onbellek = os.path.join(args.output, "onbellek")
    os.makedirs(gorseller, exist_ok=True)
    os.makedirs(onbellek, exist_ok=True)

    rng = np.random.default_rng(args.seed)
    satirlar, elenen = [], {}
    for i in range(args.count):
        tarif, stil = istem(rng, args.focus)
        ham = uret(gizli, tarif, stil, args.canvas, int(rng.integers(1, 2**31)))
        if ham is None:
            elenen["uretim"] = elenen.get("uretim", 0) + 1
            continue
        tamam, sebep = kabul_edilebilir(ham, args.yuz_kapisi)
        if not tamam:
            elenen[sebep] = elenen.get(sebep, 0) + 1
            print(f"  [{i+1}/{args.count}] elendi: {sebep}")
            continue

        tuval, _, _, _ = pdset.kanvasa_yerlestir(ham, args.canvas)
        kp = pdset.etiketle(tuval, gizli, onbellek)

        ornekler = [("ham", tuval, kp)]
        a_t, a_k = pdset.aynala(tuval, kp)
        ornekler.append(("ayna", a_t, a_k))
        for j in range(args.augment):
            ad, t, k = ornekler[j % 2]
            t2 = pdset.ton_kaydir(t, float(rng.uniform(0, 1)), rng)
            s = pdset.olcekle(t2, k, float(rng.uniform(0.7, 1.0)),
                              int(rng.integers(-8, 9)), int(rng.integers(-8, 9)))
            if s:
                ornekler.append((f"{ad}+art{j}", s[0], s[1]))

        for ad, t, k in ornekler:
            dosya = f"{pdset._hash(t)}.png"
            Image.fromarray(t).save(os.path.join(gorseller, dosya))
            # `kaynak` KOSUYA OZGU olmali: karakter bazinda bolme buna
            # dayaniyor. Yalnizca sirayla numaralandirmak yetmiyordu — ikinci
            # parti de 0000'dan basladigi icin farkli karakterler ayni kimlige
            # dusuyor ve bolmede ayni "karakter" hem egitime hem teste
            # girebiliyordu.
            satirlar.append({"gorsel": f"gorseller/{dosya}",
                             "kaynak": f"uretim/{args.focus[0]}{args.seed}_{i:04d}",
                             "artirma": ad,
                             "keypoints": k, "tarif": tarif, "stil": stil})
        print(f"  [{i+1}/{args.count}] ok  ({len(ornekler)} ornek)  {tarif[:58]}…")

    yol = os.path.join(args.output, "etiketler.jsonl")
    kip = "a" if os.path.exists(yol) else "w"
    with open(yol, kip) as f:
        for s in satirlar:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    kalan2, _ = pdset.bakiye(gizli)
    karakter = len({s["kaynak"] for s in satirlar})
    print(f"\n{len(satirlar)} ornek yazildi ({karakter} karakterden)")
    if elenen:
        print("Elenen:", ", ".join(f"{k}={v}" for k, v in elenen.items()))
    print(f"Bakiye {kalan:.1f} -> {kalan2:.1f}   cikti: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
