#!/usr/bin/env python3
"""
chen_to_pixelart.py — Chen'in illustrasyon poz veri setini pixel art'a cevirir.

    ~/ComfyUI/venv/bin/python tools/chen_to_pixelart.py --limit 60 --sheet

NEDEN KAPILI

    Donusum ZINCIRI kirilgan: arka plan ayikla -> pixel art'a cevir -> tuvale
    otur -> eklemleri tasi. Her adim sessizce bozulabiliyor ve 4000 ornegi
    gozle denetlemek mumkun degil. O yuzden her ornek OLCULUP eleniyor;
    guvenmek yerine kaniti aranmiyor, sarti saglamayan atiliyor.

    Kapilar ve ne yakaladiklari:
      zemin   — ayiklamadan sonra kenar seridi hala doluysa arka plan
                temizlenememis demektir (veri setinde kenar beyazlik orani
                ort 0.72, min 0.00 — yani ayiklama her goruntude tutmaz).
      iou     — pixel art'a cevrilen siluet, orijinal siluete oturuyor mu.
                Dusukse donusum karakteri yemis ya da sismis.
      eklem   — eklemler donusumden sonra hala karakterin uzerinde mi.
                Koordinat donusumundeki bir hata burada yakalanir.
      doluluk — karakter tuvalin makul bir bolumunu kapliyor mu.
      renk    — cikti gercekten pixel art mi (sinirli palet), yoksa
                gradyan bulamaci mi.

ETIKET DONUSUMU
    Chen 25 nokta veriyor; bize 17 COCO'su lazim ve 18.'yi (NECK) OpenPose
    tanimiyla uretiyoruz: iki omuzun ORTA NOKTASI. Bu tahmin degil —
    PixelLab'in ciktisinda alti ayri sorguda 0.00000 farkla dogrulandi.

    Anotasyon koordinatlari [y, x] ve `size` [yukseklik, genislik]. Gozle
    dogrulandi; ters varsayilsaydi tum veri seti bozuk olurdu.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import multiprocessing as mp
import os
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skeleton as sk  # noqa: E402

# Chen adi -> bizim etiket. NECK listede yok, omuzlardan turetiliyor.
ESLEME = {
    "nose": "NOSE",
    "shoulder_right": "RIGHT SHOULDER", "elbow_right": "RIGHT ELBOW",
    "wrist_right": "RIGHT ARM",
    "shoulder_left": "LEFT SHOULDER", "elbow_left": "LEFT ELBOW",
    "wrist_left": "LEFT ARM",
    "hip_right": "RIGHT HIP", "knee_right": "RIGHT KNEE",
    "ankle_right": "RIGHT LEG",
    "hip_left": "LEFT HIP", "knee_left": "LEFT KNEE", "ankle_left": "LEFT LEG",
    "eye_right": "RIGHT EYE", "eye_left": "LEFT EYE",
    "ear_right": "RIGHT EAR", "ear_left": "LEFT EAR",
}


def zemini_ayikla(rgb: np.ndarray, tol: int = 18) -> np.ndarray:
    """Kenarlardan tasma-doldurma ile arka plan maskesi (True = KARAKTER).

    Kose renginden baslayip benzer komsulara yayiliyor. Basit ama yeterli:
    tutmadigi ornekler `zemin` kapisinda zaten eleniyor."""
    h, w = rgb.shape[:2]
    a = rgb.astype(np.int16)
    koseler = [a[0, 0], a[0, w - 1], a[h - 1, 0], a[h - 1, w - 1]]
    zemin_rengi = np.median(np.stack(koseler), axis=0)
    benzer = (np.abs(a - zemin_rengi).max(axis=2) <= tol)

    # kenarlardan tasma-doldurma
    from collections import deque
    zemin = np.zeros((h, w), bool)
    kuyruk = deque()
    for y, x in ([(0, i) for i in range(w)] + [(h - 1, i) for i in range(w)] +
                 [(i, 0) for i in range(h)] + [(i, w - 1) for i in range(h)]):
        if benzer[y, x] and not zemin[y, x]:
            zemin[y, x] = True
            kuyruk.append((y, x))
    while kuyruk:
        y, x = kuyruk.popleft()
        for ny, nx in ((y-1, x), (y+1, x), (y, x-1), (y, x+1)):
            if 0 <= ny < h and 0 <= nx < w and benzer[ny, nx] and not zemin[ny, nx]:
                zemin[ny, nx] = True
                kuyruk.append((ny, nx))
    return ~zemin


def pixelize(rgba: np.ndarray, hucre: int, renk: int) -> np.ndarray:
    """PixelOE ile native cozunurluklu pixel art. Alfa ayri tasiniyor —
    PixelOE RGB calisiyor ve alfayi kendi basina goturmuyor."""
    import torch
    from pixeloe.torch.pixelize import pixelize as _px

    rgb = rgba[:, :, :3].astype(np.float32) / 255.0
    t = torch.from_numpy(rgb).permute(2, 0, 1)[None]
    out = _px(t, pixel_size=hucre, thickness=2, do_quant=True,
              num_colors=renk, no_post_upscale=True)
    px = (out[0].permute(1, 2, 0).clamp(0, 1).numpy() * 255).astype(np.uint8)

    yh, yw = px.shape[:2]
    alfa = np.array(Image.fromarray(rgba[:, :, 3]).resize((yw, yh), Image.NEAREST))
    return np.dstack([px, (alfa > 127).astype(np.uint8) * 255])


def tuvale_otur(rgba: np.ndarray, kp: dict, tuval: int = 128):
    """Karakteri tuvale ortalar, eklemleri ayni donusumle tasir."""
    ys, xs = np.where(rgba[:, :, 3] > 0)
    if ys.size == 0:
        return None
    y0, y1, x0, x1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
    kirp = rgba[y0:y1 + 1, x0:x1 + 1]
    h, w = kirp.shape[:2]
    olcek = min(1.0, (tuval - 6) / max(h, w))
    if olcek < 1.0:
        yh, yw = max(1, int(round(h * olcek))), max(1, int(round(w * olcek)))
        kirp = np.array(Image.fromarray(kirp).resize((yw, yh), Image.NEAREST))
        h, w = kirp.shape[:2]
    t = np.zeros((tuval, tuval, 4), np.uint8)
    dy, dx = (tuval - h) // 2, (tuval - w) // 2
    t[dy:dy + h, dx:dx + w] = kirp
    yeni = {l: [((x - x0) * olcek + dx) / tuval, ((y - y0) * olcek + dy) / tuval]
            for l, (x, y) in kp.items()}
    return t, yeni


def kapilar(tuval: np.ndarray, kp: dict, orijinal_maske: np.ndarray,
            esik_iou=0.55, esik_eklem=0.55, esik_doluluk=(0.10, 0.75),
            esik_renk=(4, 200)) -> tuple[bool, dict]:
    """Ornek kabul edilebilir mi? (kabul, olcumler)"""
    opak = tuval[:, :, 3] > 0
    b = tuval.shape[0]

    # siluet oturmasi: orijinal maskeyi ayni kutuya getirip IoU
    ys, xs = np.where(orijinal_maske)
    ref = np.array(Image.fromarray(
        orijinal_maske[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8) * 255
    ).resize((b, b), Image.NEAREST)) > 127
    cur = np.array(Image.fromarray(opak.astype(np.uint8) * 255)).astype(bool)
    ys2, xs2 = np.where(cur)
    if ys2.size == 0:
        return False, {"sebep": "bos"}
    cur = np.array(Image.fromarray(
        cur[ys2.min():ys2.max() + 1, xs2.min():xs2.max() + 1].astype(np.uint8) * 255
    ).resize((b, b), Image.NEAREST)) > 127
    iou = float((ref & cur).sum() / max((ref | cur).sum(), 1))

    # eklemler karakterin uzerinde mi (1 piksel genisletilmis siluet)
    gen = opak.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            gen |= np.roll(np.roll(opak, dy, 0), dx, 1)
    icinde = 0
    for l, (x, y) in kp.items():
        px, py = int(round(x * b)), int(round(y * b))
        if 0 <= px < b and 0 <= py < b and gen[py, px]:
            icinde += 1
    eklem_orani = icinde / max(len(kp), 1)

    doluluk = float(opak.mean())
    renk = len(np.unique(tuval[:, :, :3][opak].reshape(-1, 3), axis=0)) if opak.any() else 0

    olcum = {"iou": round(iou, 3), "eklem": round(eklem_orani, 3),
             "doluluk": round(doluluk, 3), "renk": renk}
    kabul = (iou >= esik_iou and eklem_orani >= esik_eklem
             and esik_doluluk[0] <= doluluk <= esik_doluluk[1]
             and esik_renk[0] <= renk <= esik_renk[1])
    if not kabul:
        olcum["sebep"] = ("iou" if iou < esik_iou else
                          "eklem" if eklem_orani < esik_eklem else
                          "doluluk" if not (esik_doluluk[0] <= doluluk <= esik_doluluk[1])
                          else "renk")
    return kabul, olcum


def cevir(kayit: dict, kok: str, hucre: int, renk: int, tuval: int):
    """Tek ornegi cevirir; (tuval, keypoints, olcum) ya da (None, None, olcum)."""
    yol = os.path.join(kok, "raw", "images", f"{kayit['bn']}.png")
    im = Image.open(yol).convert("RGBA")
    rgb = np.array(im)[:, :, :3]

    maske = zemini_ayikla(rgb)
    if maske.sum() < 200:
        return None, None, {"sebep": "zemin"}
    # kenar seridi hala doluysa ayiklama tutmamis
    kenar = np.concatenate([maske[0], maske[-1], maske[:, 0], maske[:, -1]])
    if kenar.mean() > 0.25:
        return None, None, {"sebep": "zemin", "kenar": round(float(kenar.mean()), 3)}

    rgba = np.dstack([rgb, maske.astype(np.uint8) * 255])
    px = pixelize(rgba, hucre, renk)

    # Chen koordinatlari [y, x]; pixelize olcegi degistiriyor
    oy, ox = im.size[1], im.size[0]
    sy, sx = px.shape[0] / oy, px.shape[1] / ox
    kp = {}
    for chen_ad, bizim in ESLEME.items():
        if chen_ad not in kayit["keypoints"]:
            return None, None, {"sebep": "eksik_eklem"}
        y, x = kayit["keypoints"][chen_ad]
        kp[bizim] = (x * sx, y * sy)
    kp["NECK"] = ((kp["RIGHT SHOULDER"][0] + kp["LEFT SHOULDER"][0]) / 2,
                  (kp["RIGHT SHOULDER"][1] + kp["LEFT SHOULDER"][1]) / 2)

    sonuc = tuvale_otur(px, kp, tuval)
    if sonuc is None:
        return None, None, {"sebep": "bos"}
    t, k = sonuc
    kabul, olcum = kapilar(t, k, maske)
    return (t, k, olcum) if kabul else (None, None, olcum)


# --------------------------------------------------------------------------
# Paralel kosum
#
# Isin %97'si PixelOE'de geciyor (olculdu: ornek basina 12.3s; yukleme 0.02s,
# zemin ayiklama 0.35s). Torch'un kendi ic paralelligi bu boyuttaki evrisimlerde
# olceklenmiyor, o yuzden her isci TEK is parcacigina sabitlenip is SURECLERE
# bolunuyor. 4000 ornek tek surecte ~14 saat; 8 iscide ~2 saat.
# --------------------------------------------------------------------------
_AYAR: dict = {}


def _isci_kur(ayar: dict) -> None:
    global _AYAR
    _AYAR = ayar
    import torch
    torch.set_num_threads(1)   # yoksa 8 isci 10 cekirdegi paylasmak icin bogusur


def _isci(kayit: dict):
    try:
        t, kp, olcum = cevir(kayit, _AYAR["data"], _AYAR["cell"],
                             _AYAR["colors"], _AYAR["canvas"])
    except Exception as err:                                      # noqa: BLE001
        return kayit["bn"], None, None, {"sebep": f"hata:{type(err).__name__}"}
    return kayit["bn"], t, kp, olcum


@contextlib.contextmanager
def _akis(kayitlar: list[dict], ayar: dict, isci: int):
    """Sonuclari SIRAYLA veren akis. `--jobs 1` tek surecte kalir (hata
    ayiklamasi kolay olsun); digerlerinde spawn'li havuz kullanilir —
    fork'lanmis surecte torch kilitlenebiliyor."""
    if isci <= 1:
        _isci_kur(ayar)
        yield (_isci(k) for k in kayitlar)
        return
    ctx = mp.get_context("spawn")
    havuz = ctx.Pool(isci, initializer=_isci_kur, initargs=(ayar,))
    try:
        # imap SIRAYI korur; devam etme indekse dayandigi icin bu sart.
        yield havuz.imap(_isci, kayitlar, chunksize=2)
    finally:
        havuz.terminate()
        havuz.join()


def _jsonl_oku(yol: str) -> list[dict]:
    """Yarim kalmis SON satiri atar — kosu ortasinda kesilmis dosya normaldir."""
    if not os.path.exists(yol):
        return []
    cikti = []
    with open(yol) as f:
        for ham in f:
            try:
                cikti.append(json.loads(ham))
            except json.JSONDecodeError:
                break
    return cikti


def main(argv=None):
    kok_proje = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = argparse.ArgumentParser(description="Chen veri setini pixel art'a cevirir.")
    p.add_argument("--data", default=os.path.join(kok_proje, "_data", "chen",
                                                  "bizarre_pose_dataset"))
    p.add_argument("-o", "--output", default=os.path.join(kok_proje, "_data", "chen_px"))
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--cell", type=int, default=4, help="PixelOE hucre boyutu")
    p.add_argument("--colors", type=int, default=48)
    p.add_argument("--canvas", type=int, default=128)
    p.add_argument("--sheet", action="store_true", help="Gozle inceleme sayfasi uret")
    p.add_argument("--resume", action="store_true",
                   help="Yarim kalmis kosuya kaldigi yerden devam et")
    # Cekirdeklerin ucte biri. Hepsini doldurmak makineyi kullanilamaz hale
    # getiriyor: is CPU'ya doymus halde kaliyor ve arayuze pay kalmiyor.
    # Ucte birle kosu birkac kat hizli ama makine akici kaliyor.
    p.add_argument("-j", "--jobs", type=int, default=max(1, (os.cpu_count() or 3) // 3),
                   help="Paralel isci sayisi (1 = tek surec). Varsayilan "
                        "cekirdegin ucte biri; makineyi bogmamak icin.")
    args = p.parse_args(argv)

    with open(os.path.join(args.data, "raw", "annotations.json")) as f:
        ann = json.load(f)
    anahtarlar = list(ann)[:args.limit] if args.limit else list(ann)

    gorseller = os.path.join(args.output, "gorseller")
    os.makedirs(gorseller, exist_ok=True)
    satirlar, sebepler, ornekler = [], {}, []

    # Etiketler ANINDA yaziliyor, sonda toplu degil. 4000 ornek saatler suruyor;
    # toplu yazimda 3900'de dusen bir kosu her seyi goturur, ustelik kosarken
    # `tools/veri_onizle.py` ile ara sonuca bakmak da mumkun olmaz.
    etiket_yolu = os.path.join(args.output, "etiketler.jsonl")
    ilerleme_yolu = os.path.join(args.output, "ilerleme.json")

    # Kaldigi yerden devam. ISLENEN sayisi tutuluyor, kabul edilen degil:
    # elenenlerin kaydi yok, sadece etiketlere bakip atlasaydik reddedilen
    # %55 her devamda bastan islenirdi.
    basla = 0
    if args.resume and os.path.exists(ilerleme_yolu):
        with open(ilerleme_yolu) as f:
            durum = json.load(f)
        basla = int(durum.get("islenen", 0))
        satirlar = _jsonl_oku(etiket_yolu)[:]
        sebepler = dict(durum.get("sebepler", {}))
        print(f"Devam: ilk {basla} ornek islenmisti, {len(satirlar)} kabul.",
              flush=True)

    kalan = [ann[k] for k in anahtarlar[basla:]]
    ayar = {"data": args.data, "cell": args.cell, "colors": args.colors,
            "canvas": args.canvas}
    baslangic = time.time()

    with open(etiket_yolu, "a" if basla else "w", buffering=1) as ef, \
            _akis(kalan, ayar, args.jobs) as akis:
        for j, (bn, t, kp, olcum) in enumerate(akis):
            i = basla + j
            if t is None:
                sebepler[olcum.get("sebep", "?")] = sebepler.get(olcum.get("sebep", "?"), 0) + 1
            else:
                dosya = f"{bn}.png"
                Image.fromarray(t).save(os.path.join(gorseller, dosya))
                s = {"gorsel": f"gorseller/{dosya}", "kaynak": f"chen/{bn}",
                     "artirma": "ham", "keypoints": kp, "olcum": olcum}
                satirlar.append(s)
                ef.write(json.dumps(s, ensure_ascii=False) + "\n")
                if len(ornekler) < 24:
                    ornekler.append((t, kp))

            # ELENEN ornekten sonra da calismali: eskiden bu blok `continue`nin
            # arkasindaydi, yani ilerleme ancak 50'ye bolunen ornek KABUL
            # edildiginde basiliyordu — yaklasik iki seferde bir.
            if (i + 1) % 50 == 0:
                gecen = time.time() - baslangic
                kalan_sn = gecen / (j + 1) * (len(kalan) - j - 1)
                # flush sart: cikti dosyaya yonlendirilince print blok tamponlu
                # olur ve ilerleme ancak kosu bitince gorunur.
                print(f"  {i+1}/{len(anahtarlar)} islendi, {len(satirlar)} kabul "
                      f"(%{100*len(satirlar)/(i+1):.0f})  "
                      f"{gecen/(j+1):.2f}s/ornek  kalan ~{kalan_sn/60:.0f}dk",
                      flush=True)
                with open(ilerleme_yolu, "w") as pf:
                    json.dump({"islenen": i + 1, "sebepler": sebepler}, pf)

    n = len(anahtarlar)
    print(f"\n{len(satirlar)}/{n} kabul edildi (%{100*len(satirlar)/max(n,1):.0f})")
    if sebepler:
        print("Elenme sebepleri:", ", ".join(f"{k}={v}" for k, v in
                                             sorted(sebepler.items(), key=lambda t: -t[1])))
    if satirlar:
        for ad in ("iou", "eklem", "doluluk", "renk"):
            v = [s["olcum"][ad] for s in satirlar if ad in s["olcum"]]
            if v:
                print(f"  {ad:8s} medyan {np.median(v):.3f}  en dusuk {min(v):.3f}")

    if args.sheet and ornekler:
        from PIL import ImageDraw
        s, sut = 128, 6
        satir = (len(ornekler) + sut - 1) // sut
        sf = Image.new("RGB", (s * sut, s * satir), (20, 22, 26))
        for j, (t, kp) in enumerate(ornekler):
            im = Image.fromarray(t).convert("RGBA")
            d = ImageDraw.Draw(im)
            for a, b in sk.KEMIKLER:
                d.line([(kp[a][0]*s, kp[a][1]*s), (kp[b][0]*s, kp[b][1]*s)],
                       fill=(0, 200, 255, 200), width=1)
            for l, (x, y) in kp.items():
                d.ellipse([x*s-1.5, y*s-1.5, x*s+1.5, y*s+1.5], fill=(255, 70, 70, 255))
            sf.paste(im.convert("RGB"), ((j % sut) * s, (j // sut) * s))
        yol = os.path.join(args.output, "inceleme.png")
        sf.save(yol)
        print(f"Gozle inceleme: {yol}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
