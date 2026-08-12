#!/usr/bin/env python3
"""
pixellab_animasyon.py — karaktere yeni animasyon klibi uretir ve meta.json'a ekler.

    python3 tools/pixellab_animasyon.py ael --eylem "waving hello" --ad tepki
    python3 tools/pixellab_animasyon.py ael --eylem "sitting down" --ad otur --kare 6

NEDEN BU ARAC

    Uygulamanin durum makinesi hazir: IDLE, WALKING, DRAGGING, REACTING.
    Ama DRAGGING ve REACTING'de oynatacak kare yok, ikisi de `idle`'a
    dusuyor — her karakterde yalnizca iki klip var. Yani uygulama ozellik
    degil KARE acligi cekiyor.

    Acik kaynak ureteci beklemeye gerek yok: `animate-with-text-v3` ilk
    kareyi ve eylem metnini alip 4-16 kare uretiyor, iskelet muhendisligi
    istemiyor.

NEDEN animate-with-skeleton DEGIL
    O tam 3 kare aliyor ve hedef poz dizisini DISARIDAN bekliyor. "Suruklenirken
    sallanma" gibi bir klip icin o poz dizisini once kurmak gerekirdi. Metinle
    olan uc adimi birden atliyor. Poz uzerinde tam denetim gerekince
    animate-with-skeleton'a donulur.

CIKTI
    Yatay serit sprite sheet + meta.json'a klip girdisi. Uygulama klipleri
    meta.json'dan kesfediyor, baska bir yere dokunmak gerekmiyor.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

TABAN = "https://api.pixellab.ai/v2"


def _anahtar(kok: str) -> str:
    for satir in open(os.path.join(kok, ".env")):
        if satir.startswith("PIXELLAB_API_KEY="):
            return satir.split("=", 1)[1].strip()
    raise SystemExit("HATA: .env icinde PIXELLAB_API_KEY yok.")


def _cagir(anahtar: str, yol: str, govde: dict | None = None) -> dict:
    r = urllib.request.Request(
        f"{TABAN}{yol}",
        data=json.dumps(govde).encode() if govde is not None else None,
        headers={"Authorization": f"Bearer {anahtar}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=180) as y:
            return json.load(y)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HATA {e.code} ({yol}): {e.read().decode()[:500]}")


def _b64_mu(x) -> bool:
    v = x.get("base64") if isinstance(x, dict) else x
    return isinstance(v, str) and len(v) > 200


def _kare_listesi_bul(d, derinlik: int = 0):
    """Yanitin herhangi bir yerindeki base64 goruntu listesini bulur."""
    if derinlik > 6:
        return None
    if isinstance(d, list) and d and all(_b64_mu(x) for x in d):
        return d
    if isinstance(d, dict):
        for v in d.values():
            b = _kare_listesi_bul(v, derinlik + 1)
            if b:
                return b
    elif isinstance(d, list):
        for v in d:
            b = _kare_listesi_bul(v, derinlik + 1)
            if b:
                return b
    return None


def _iskelet(d, derinlik: int = 0):
    """Yaniti kisaltarak yapisini gosterir (hata mesaji icin)."""
    if derinlik > 4:
        return "..."
    if isinstance(d, dict):
        return {k: _iskelet(v, derinlik + 1) for k, v in d.items()}
    if isinstance(d, list):
        return [f"<{len(d)} oge>"] + ([_iskelet(d[0], derinlik + 1)] if d else [])
    if isinstance(d, str):
        return f"<str {len(d)}>" if len(d) > 60 else d
    return d


def uret(anahtar: str, ilk_kare_png: bytes, eylem: str, kare: int,
         tohum: int, zaman_asimi: int = 600) -> tuple[list[bytes], dict]:
    """Isi kuyruga verir, bitmesini bekler, (kare listesi, usage) doner."""
    istek = {
        "first_frame": {"type": "base64",
                        "base64": base64.b64encode(ilk_kare_png).decode()},
        "action": eylem,
        "frame_count": kare,
        "seed": tohum,
        "no_background": True,
    }
    d = _cagir(anahtar, "/animate-with-text-v3", istek)
    kullanim = dict(d.get("usage") or {})
    if d.get("enhanced_prompt"):
        print(f"  genisletilmis istem: {d['enhanced_prompt'][:110]}")
    is_id = d.get("background_job_id")
    if not is_id:
        raise SystemExit(f"Beklenmeyen yanit: {json.dumps(d)[:400]}")

    basla = time.time()
    while time.time() - basla < zaman_asimi:
        time.sleep(4)
        j = _cagir(anahtar, f"/background-jobs/{is_id}")
        durum = j.get("status")
        if durum == "failed":
            raise SystemExit(f"Uretim basarisiz: {json.dumps(j)[:400]}")
        if durum == "completed":
            for k, v in (j.get("usage") or {}).items():
                if isinstance(v, (int, float)):
                    kullanim[k] = kullanim.get(k, 0.0) + float(v)
            # Kareler ic ice bir yapida geliyor (`last_response` altinda) ve
            # anahtar adi surumden surume degisebiliyor. Sabit bir yol yerine
            # OZYINELEMELI arama: base64 goruntu listesi neredeyse oradan
            # aliniyor. Boylece yapi degisirse arac sessizce bozulmuyor.
            ham = _kare_listesi_bul(j)
            if ham is None:
                raise SystemExit("Kare bulunamadi. Yanit yapisi:\n"
                                 + json.dumps(_iskelet(j), indent=1)[:900])
            return [base64.b64decode(x["base64"] if isinstance(x, dict) else x)
                    for x in ham], kullanim
        print(f"    {durum}… {int(time.time()-basla)}s", flush=True)
    raise SystemExit(f"{zaman_asimi}s icinde bitmedi.")


def serit_yap(kareler: list[bytes], boy: int):
    """Kareleri yatay serite dizer; uygulamanin bekledigi bicim."""
    from PIL import Image
    ims = [Image.open(io.BytesIO(b)).convert("RGBA") for b in kareler]
    serit = Image.new("RGBA", (boy * len(ims), boy), (0, 0, 0, 0))
    for i, im in enumerate(ims):
        if im.size != (boy, boy):
            # Tam sayi kati degilse NEAREST: ara ton uretmesin.
            im = im.resize((boy, boy), Image.NEAREST)
        serit.paste(im, (i * boy, 0))
    return serit


def main(argv=None):
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = argparse.ArgumentParser(description="Karaktere yeni animasyon klibi uretir.")
    p.add_argument("karakter")
    p.add_argument("--eylem", required=True, help="Ingilizce eylem tarifi")
    p.add_argument("--ad", required=True, help="Klip adi (meta.json anahtari)")
    p.add_argument("--kaynak-klip", default="idle", help="Ilk kare hangi klipten")
    p.add_argument("--kaynak-kare", type=int, default=0,
                   help="Kaynak klibin kacinci karesi. -1 = SON kare. "
                        "Zincirlenen klipler icin sart: 'uyu'yu idle'in ilk "
                        "karesinden baslatinca karakter AYAKTA uyuyor ve "
                        "'otur'dan gecis isinlanma gibi gorunuyor.")
    p.add_argument("--kare", type=int, default=6, help="Kare sayisi (4-16, cift)")
    p.add_argument("--sure", type=int, default=140, help="Kare suresi (ms)")
    p.add_argument("--tohum", type=int, default=0)
    p.add_argument("--kuru", action="store_true", help="Sadece plani yaz, cagri yapma")
    args = p.parse_args(argv)

    kdir = os.path.join(kok, "characters", args.karakter)
    myol = os.path.join(kdir, "meta.json")
    if not os.path.exists(myol):
        raise SystemExit(f"HATA: {myol} yok.")
    with open(myol) as f:
        meta = json.load(f)
    kaynak = meta.get(args.kaynak_klip)
    if not kaynak:
        raise SystemExit(f"HATA: '{args.kaynak_klip}' klibi meta.json'da yok.")

    from PIL import Image
    boy = int(kaynak["frameSize"])
    sheet = Image.open(os.path.join(kdir, kaynak["file"])).convert("RGBA")
    kare_say = int(kaynak.get("frameCount", 1))
    ki = args.kaynak_kare % kare_say
    ilk = sheet.crop((ki * boy, 0, (ki + 1) * boy, boy))
    # API 256'ya kadar kabul ediyor; tam sayi katiyla buyutmek karakteri
    # modelin gordugu bantta tutuyor ve ara ton uretmiyor.
    kat = max(1, min(256 // boy, 4))
    if kat > 1:
        ilk = ilk.resize((boy * kat, boy * kat), Image.NEAREST)
    tam = io.BytesIO()
    ilk.save(tam, format="PNG")

    print(f"{args.karakter}: '{args.ad}' <- \"{args.eylem}\"  {args.kare} kare, "
          f"baslangic: {args.kaynak_klip}[{ki}] {boy}x{boy} (x{kat})")
    if args.kuru:
        return 0

    kareler, kullanim = uret(_anahtar(kok), tam.getvalue(), args.eylem,
                             args.kare, args.tohum)
    dosya = f"{args.ad}_spritesheet.png"
    serit_yap(kareler, boy).save(os.path.join(kdir, dosya))

    meta[args.ad] = {"file": dosya, "frameSize": boy,
                     "frameCount": len(kareler), "frameDuration": args.sure}
    with open(myol, "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"  {len(kareler)} kare -> characters/{args.karakter}/{dosya}")
    print(f"  meta.json'a '{args.ad}' klibi eklendi")
    if kullanim:
        print("  maliyet: " + ", ".join(f"{k}={v:.4g}" for k, v in sorted(kullanim.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
