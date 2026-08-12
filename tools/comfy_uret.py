#!/usr/bin/env python3
"""
comfy_uret.py — kuklayi ComfyUI'da temize cekip pixel art'a indirger.

    python3 tools/comfy_uret.py --kukla K.png --kontrol C.png \
        --referans characters/ael/walk_right_spritesheet.png -o _cikti/kare0

HATTIN BU PARCASI NE YAPIYOR

    Kukla dogru pozda ama kaba: pikseller keyfi acilarla dondurulmus, izgara
    bozulmus, uzuv diplerinde dikis var. Difuzyon bunu TEMIZE cekiyor.

    "Sifirdan ciz" degil "bunu duzelt" demek onemli. Kukla UC rolde birden
    giriyor:

        ControlNet  siluet/lineart olarak — pozu ve ORANI dayatiyor
        init_image  img2img baslangici olarak — kimlik ve palet cipasi
        (referans)  ayrica IP-Adapter'e kaynak sprite gidiyor — stil

    Ucuncusu olmadan model karakteri kendi bildigi gibi cizer; ikincisi
    olmadan her kare bagimsiz bir orneklem olur ve kareler arasi titrer
    (olculdu: yalnizca tohum degistirince cikti 5.65px kayiyor).

NEDEN ISKELET DEGIL SILUET KONTROLU
    Olculdu: iskelet verince difuzyon eklemler arasindaki eti kendi
    dolduruyor ve chibi oranini insan oranina cekiyor. Siluet verince oran
    korunuyor — kaynak 0.305, uretilen 0.309.

512'DE URETIP KUCULTMEK
    SD 1.5 512'de egitildi; 111 piksellik bir tuvalde calistirmak alan
    disidir. Uretim 512'de yapilip cikti PixelOE ile geri indiriliyor —
    Chen hattinin aynisi, o hat olculdu (4.02 -> 3.64).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.request
import uuid

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chen_to_pixelart as chen  # noqa: E402

SUNUCU = "http://127.0.0.1:8188"
COMFY = os.path.expanduser("~/ComfyUI")

OLUMSUZ = ("blurry, photorealistic, 3d render, smooth gradient, anti-aliased, "
           "extra limbs, deformed, text, watermark, jpeg artifacts")


def _tuvale_512(rgba: np.ndarray, zemin=(255, 255, 255)) -> Image.Image:
    """Kareyi 512x512 beyaz tuvale TAM SAYI katiyla ortalar.

    Tam sayi kati: NEAREST ile buyutmek her pikseli esit bloga cevirir.
    Kesirli olcek bazi pikselleri 4, bazilarini 5 piksel yapar ve difuzyon
    o duzensizligi dokusal bir sinyal sanar.

    Zemin beyaz cunku saydamlik VAE'ye siyah olarak giriyor ve model
    karakterin cevresini karanlik bir alan sanip oraya golge/nesne
    uyduruyor."""
    h, w = rgba.shape[:2]
    kat = max(1, min(512 // max(h, w), 8))
    im = Image.fromarray(rgba).resize((w * kat, h * kat), Image.NEAREST)
    tuval = Image.new("RGB", (512, 512), zemin)
    zemin_im = Image.new("RGB", im.size, zemin)
    zemin_im.paste(im.convert("RGB"), (0, 0), im.split()[3] if im.mode == "RGBA" else None)
    tuval.paste(zemin_im, ((512 - im.width) // 2, (512 - im.height) // 2))
    return tuval


def is_akisi(kukla: str, kontrol: str, referans: str, istem: str, *,
             denoise: float, cn_agirlik: float, ip_agirlik: float,
             cn_model: str, adim: int, cfg: float, tohum: int) -> dict:
    """ComfyUI API bicimi is akisi (node grafigi)."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"}},
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": istem, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": OLUMSUZ, "clip": ["1", 1]}},
        "4": {"class_type": "LoadImage", "inputs": {"image": kontrol}},
        "5": {"class_type": "LoadImage", "inputs": {"image": kukla}},
        "6": {"class_type": "LoadImage", "inputs": {"image": referans}},
        "7": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": cn_model}},
        "8": {"class_type": "ControlNetApplyAdvanced",
              "inputs": {"positive": ["2", 0], "negative": ["3", 0],
                         "control_net": ["7", 0], "image": ["4", 0],
                         "strength": cn_agirlik, "start_percent": 0.0,
                         "end_percent": 1.0}},
        "9": {"class_type": "IPAdapterModelLoader",
              "inputs": {"ipadapter_file": "ip-adapter_sd15.safetensors"}},
        "10": {"class_type": "CLIPVisionLoader",
               "inputs": {"clip_name": "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"}},
        "11": {"class_type": "IPAdapterAdvanced",
               "inputs": {"model": ["1", 0], "ipadapter": ["9", 0], "image": ["6", 0],
                          "clip_vision": ["10", 0],
                          "weight": ip_agirlik, "weight_type": "linear",
                          "combine_embeds": "concat", "start_at": 0.0, "end_at": 1.0,
                          "embeds_scaling": "V only"}},
        "12": {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0], "vae": ["1", 2]}},
        "13": {"class_type": "KSampler",
               "inputs": {"model": ["11", 0], "seed": tohum, "steps": adim, "cfg": cfg,
                          "sampler_name": "dpmpp_2m", "scheduler": "karras",
                          "positive": ["8", 0], "negative": ["8", 1],
                          "latent_image": ["12", 0], "denoise": denoise}},
        "14": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["1", 2]}},
        "15": {"class_type": "SaveImage",
               "inputs": {"images": ["14", 0], "filename_prefix": "pet_uret"}},
    }


def kuyruga_ver(akis: dict, zaman_asimi: int = 900) -> list[str]:
    """Is akisini gonderir, bitmesini bekler, uretilen dosya adlarini doner."""
    kimlik = str(uuid.uuid4())
    veri = json.dumps({"prompt": akis, "client_id": kimlik}).encode()
    istek = urllib.request.Request(f"{SUNUCU}/prompt", data=veri,
                                   headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(istek, timeout=30) as y:
            pid = json.load(y)["prompt_id"]
    except urllib.error.HTTPError as e:
        raise SystemExit(f"ComfyUI reddetti: {e.read().decode()[:800]}")

    basla = time.time()
    while time.time() - basla < zaman_asimi:
        time.sleep(2)
        with urllib.request.urlopen(f"{SUNUCU}/history/{pid}", timeout=30) as y:
            g = json.load(y)
        if pid not in g:
            continue
        durum = g[pid].get("status", {})
        if durum.get("status_str") == "error":
            raise SystemExit(f"ComfyUI hata: {json.dumps(durum)[:800]}")
        cikti = g[pid].get("outputs", {})
        if cikti:
            return [im["filename"] for d in cikti.values() for im in d.get("images", [])]
    raise SystemExit(f"{zaman_asimi}s icinde bitmedi.")


def main(argv=None):
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = argparse.ArgumentParser(description="Kuklayi ComfyUI'da temize ceker.")
    p.add_argument("--kukla", required=True)
    p.add_argument("--kontrol", required=True)
    p.add_argument("--referans", required=True, help="Kaynak sprite (IP-Adapter stili)")
    p.add_argument("--frame", type=int, default=0)
    p.add_argument("--istem", default="pixel art sprite of a character, side view, "
                                      "walking, clean flat colors, sharp pixels, "
                                      "transparent background, game asset")
    p.add_argument("--denoise", type=float, default=0.55)
    p.add_argument("--cn", type=float, default=0.9, help="ControlNet agirligi")
    p.add_argument("--ip", type=float, default=0.8, help="IP-Adapter agirligi")
    p.add_argument("--cn-model", default="control_v11p_sd15_lineart_fp16.safetensors")
    p.add_argument("--adim", type=int, default=24)
    p.add_argument("--cfg", type=float, default=7.0)
    p.add_argument("--tohum", type=int, default=0)
    p.add_argument("--hedef", type=int, default=0,
                   help="Indirgeme hedefi (piksel). 0 = kuklanin boyu")
    p.add_argument("-o", "--out", required=True)
    args = p.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    girdi_dizin = os.path.join(COMFY, "input")
    os.makedirs(girdi_dizin, exist_ok=True)

    import skeleton as sk
    kukla = np.array(Image.open(args.kukla).convert("RGBA"))
    ref = sk.kareyi_al(args.referans, args.frame, None)
    hedef = args.hedef or int((kukla[:, :, 3] > 0).any(axis=1).sum())

    # ComfyUI yalnizca kendi `input/` klasorunden okuyor.
    adlar = {}
    for etiket, im in (("kukla", _tuvale_512(kukla)),
                       ("kontrol", Image.open(args.kontrol).convert("RGB")
                        .resize((512, 512), Image.NEAREST)),
                       ("referans", _tuvale_512(ref))):
        ad = f"pet_{etiket}_{os.getpid()}.png"
        im.save(os.path.join(girdi_dizin, ad))
        adlar[etiket] = ad
        im.save(os.path.join(args.out, f"girdi_{etiket}.png"))

    akis = is_akisi(adlar["kukla"], adlar["kontrol"], adlar["referans"], args.istem,
                    denoise=args.denoise, cn_agirlik=args.cn, ip_agirlik=args.ip,
                    cn_model=args.cn_model, adim=args.adim, cfg=args.cfg,
                    tohum=args.tohum)
    print(f"uretiliyor: denoise={args.denoise} cn={args.cn} ip={args.ip} "
          f"adim={args.adim} tohum={args.tohum}")
    t0 = time.time()
    dosyalar = kuyruga_ver(akis)
    print(f"  {time.time()-t0:.0f}s, {len(dosyalar)} kare")

    for i, dosya in enumerate(dosyalar):
        kaynak = os.path.join(COMFY, "output", dosya)
        ham = os.path.join(args.out, f"ham_{i}.png")
        shutil.copy(kaynak, ham)
        # PixelOE ile indirgeme — hucre boyu hedefe gore secilir.
        buyuk = np.array(Image.open(ham).convert("RGBA"))
        hucre = max(2, round(512 / max(hedef, 1)))
        px = chen.pixelize(buyuk, hucre, 48)
        Image.fromarray(px).save(os.path.join(args.out, f"px_{i}.png"))
        print(f"  ham 512 -> px {px.shape[1]}x{px.shape[0]} (hucre {hucre})")
    print(f"cikti: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
