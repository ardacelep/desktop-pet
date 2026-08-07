#!/usr/bin/env python3
"""
pixellab_karakter.py — tek bir pixel art gorselinden calisir bir pet karakteri uretir.

    python3 tools/pixellab_karakter.py                    # sorarak ilerler
    python3 tools/pixellab_karakter.py kedi.png --ad kedi
    python3 tools/pixellab_karakter.py kedi.png --ad kedi --dry-run   # sadece maliyet

Girdi: onden bakan, seffaf zeminli, NATIVE cozunurlukte tek bir PNG.
Cikti: characters/<ad>/ altinda idle + walk_right sheet'leri ve meta.json —
       yani `npm start` ile dogrudan secilebilen bir karakter.

NEDEN BU UC NOKTALAR
    PixelLab'in animasyon uclari uc farkli sey yapiyor ve secim onemli:

    - `/animate-with-text`: referans gorsel + eylem metni. En dogrudan yol ama
      YALNIZCA 64x64 destekliyor. Bizim karakterlerimiz 87-90px; 64'e indirip
      geri buyutmek pixel art'ta geri donusu olmayan bir kayip.
    - `/animate-with-skeleton`: 256'ya kadar cikiyor ama TAM 3 kare iskelet
      istiyor. Yurume dongusunu 3'er karelik pencerelere bolmek ve pencereler
      arasi sureklilik saglamak ayri bir is.
    - `/create-character-v3` + `/characters/animations` (template modu):
      once gorsel 8 yone dondurulup kalici bir "karakter" haline geliyor,
      sonra hazir iskelet sablonlariyla animasyon uretiliyor. Boyut kisiti
      yok, sablon 1 generation/yon ve kareler zaten ayni tuvalde hizali
      geliyor. Secilen yol bu.

NEDEN idle=south, walk=east
    Depodaki karakterlerde olculdu: idle karesi onden bakiyor (ael, omerhan,
    mag), yurume karesi ise yandan, saga bakiyor. `walk_left` ayri bir sheet
    degil, `flip: true` ile ureiliyor — o yuzden bati yonunu hic istemiyoruz.

MALIYET
    v3 karakter: ceil(w*h*8/65536) generation (128x128 -> 2, 87x87 -> 1)
    her animasyon: 1 generation/yon -> idle 1 + walk 1
    Toplam bir karakter icin 3-4 generation. `GET /balance` ucretsiz.

YARIDA KESILME
    Her odenmis adim `_data/pixellab/<ad>/durum.json`'a yaziliyor. Arac tekrar
    calistirildiginda tamamlanmis adimlari ATLIYOR — aksi halde poll sirasinda
    Ctrl-C basmak odenmis bir karakteri cope atardi.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

from PIL import Image

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARAC = os.path.join(KOK, "tools")
sys.path.insert(0, ARAC)

TABAN = "https://api.pixellab.ai/v2"

# Sablon kimlikleri canli API'ye gecersiz bir kimlik gonderilerek dogrulandi
# (dogrulama hatasi ucretsiz): `idle`, `breathing-idle`, `walk`, `walking`
# hepsi mevcut. `breathing-idle` duran karakterde nefes alip verme veriyor —
# masaustu pet'i icin `idle`den daha canli.
IDLE_SABLON = "breathing-idle"
WALK_SABLON = "walk"

# Depodaki dort karakterin ortak degerleri. Bunlar "uzun ve ugrastirici" girdi
# sinifinda: sorulmuyor, varsayilan geciyor, isteyen meta.json'dan degistiriyor.
IDLE_SURE = 500
WALK_SURE = 120
YURUME_HIZI = 42
VARSAYILAN_REPLIKLER = [
    "Selam!",
    "Bugün nasılsın?",
    "Bir mola versene.",
    "Su içmeyi unutma.",
    "Buradayım, merak etme.",
    "Beni sürükleyebilirsin!",
]
# v3 rotasyonun tutarli olmasi icin bir tarif istiyor. Gorseli zaten verdigimiz
# icin metnin isi sadece modeli dogru sinifa oturtmak.
VARSAYILAN_TARIF = "full body pixel art character, front view, standing"

# Iskeletin oturtulacagi 3B govde. Yanlis sablon animasyonu bozar: dort ayakli
# bir karakteri `mannequin` ile iki ayak uzerinde yurutmeye calisir.
GOVDELER = ("mannequin", "bear", "cat", "dog", "horse", "lion")

EN_KUCUK, EN_BUYUK = 32, 256      # v3'un kabul ettigi kare kenari
POLL_ARALIK = 5                   # sn — dokumantasyon 2-5 sn oneriyor
POLL_AZAMI = 900                  # sn; tipik uretim 30-180 sn


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def anahtar_oku() -> str:
    """.env icindeki PIXELLAB_API_KEY. Dosya .gitignore'da, repoya girmiyor."""
    yol = os.path.join(KOK, ".env")
    if os.path.exists(yol):
        m = re.search(r"^\s*PIXELLAB_API_KEY\s*=\s*(\S+)", open(yol).read(), re.M)
        if m:
            return m.group(1).strip("'\"")
    if os.environ.get("PIXELLAB_API_KEY"):
        return os.environ["PIXELLAB_API_KEY"]
    raise SystemExit(
        "HATA: PIXELLAB_API_KEY bulunamadi.\n"
        f"  {yol} icine  PIXELLAB_API_KEY=...  satirini ekleyin\n"
        "  (anahtar https://www.pixellab.ai hesap sayfasindan alinir)")


def _cagir(yol: str, govde: dict | None = None, ham: bool = False):
    istek = urllib.request.Request(
        TABAN + yol,
        headers={"Authorization": f"Bearer {_ANAHTAR}",
                 "Content-Type": "application/json"},
        data=json.dumps(govde).encode() if govde is not None else None)
    try:
        with urllib.request.urlopen(istek, timeout=300) as y:
            return y.read() if ham else json.load(y)
    except urllib.error.HTTPError as e:
        govde_metni = e.read().decode(errors="replace")[:600]
        if e.code == 402:
            raise SystemExit("HATA: bakiye bitti. https://www.pixellab.ai/pricing")
        raise SystemExit(f"HATA: {yol} -> HTTP {e.code}\n{govde_metni}")
    except urllib.error.URLError as e:
        raise SystemExit(f"HATA: {yol} -> baglanti kurulamadi ({e.reason})")


def bakiye() -> float:
    b = _cagir("/balance")
    a = b.get("subscription") or {}
    if a.get("generations") is not None:
        return float(a["generations"])
    return float((b.get("credits") or {}).get("usd", 0))


def is_bekle(job_id: str, etiket: str) -> dict:
    """Arka plan isini tamamlanana kadar bekler.

    Uretim asenkron: cagri hemen donuyor, kareler dakikalar sonra hazir oluyor.
    Poll'u burada topluyoruz ki cagiran taraf her yerde ayni sabri gostersin."""
    basla = time.time()
    while True:
        d = _cagir(f"/background-jobs/{job_id}")
        durum = d.get("status")
        if durum == "completed":
            print(f"    {etiket}: tamam ({time.time() - basla:.0f} sn)")
            return d.get("last_response") or {}
        if durum == "failed":
            raise SystemExit(f"HATA: {etiket} basarisiz — {json.dumps(d)[:400]}")
        if time.time() - basla > POLL_AZAMI:
            raise SystemExit(
                f"HATA: {etiket} {POLL_AZAMI} sn'de bitmedi. Is kimligi {job_id}; "
                "araci tekrar calistirinca kaldigi yerden devam eder.")
        print(f"    {etiket}: {durum}… ({time.time() - basla:.0f} sn)",
              end="\r", flush=True)
        time.sleep(POLL_ARALIK)


# ---------------------------------------------------------------------------
# Girdi hazirligi
# ---------------------------------------------------------------------------

def gorsel_hazirla(yol: str) -> tuple[Image.Image, list[str]]:
    """Girdiyi v3'un kabul edecegi hale getirir; duzeltemedigini uyari olarak doner.

    Kare kutuya PAD ediyoruz, olceklemiyoruz: depodaki sprite'lar kare kutu
    formatinda ve olcekleme pixel art'ta gerideki izgarayi bozar."""
    im = Image.open(yol).convert("RGBA")
    uyari: list[str] = []

    # histogram[0] = tamamen seffaf piksel sayisi
    seffaf = im.getchannel("A").histogram()[0]
    if 1 - seffaf / (im.width * im.height) > 0.97:
        uyari.append(
            "gorselin zemini seffaf degil — PixelLab arka plani karakterin "
            "parcasi sanip dondurur. Once tools/pixelart_extract.py'den gecirin.")
    if max(im.size) > EN_BUYUK:
        raise SystemExit(
            f"HATA: gorsel {im.width}x{im.height}, v3 en fazla {EN_BUYUK} kabul "
            "ediyor. Bu boyut genelde gorselin NATIVE cozunurlukte olmadigini "
            "gosterir; tools/pixelart_extract.py ile gercek cozunurluge indirin.")
    if max(im.size) < EN_KUCUK:
        raise SystemExit(f"HATA: gorsel {im.width}x{im.height}, en az "
                         f"{EN_KUCUK}x{EN_KUCUK} olmali.")

    if im.width != im.height:
        k = max(im.size)
        kare = Image.new("RGBA", (k, k), (0, 0, 0, 0))
        # Yatayda ortala, DIKEYDE ALTA yasla: karakterin ayaklari alt kenarda
        # duruyor olmali, yoksa ekranda havada durur.
        kare.paste(im, ((k - im.width) // 2, k - im.height))
        uyari.append(f"{im.width}x{im.height} -> {k}x{k} kare kutuya alindi")
        im = kare
    if im.width < EN_KUCUK:
        raise SystemExit(f"HATA: kare kutu {im.width}px, en az {EN_KUCUK} olmali.")
    return im, uyari


def b64(im: Image.Image) -> dict:
    tampon = io.BytesIO()
    im.save(tampon, format="PNG")
    return {"type": "base64", "base64": base64.b64encode(tampon.getvalue()).decode(),
            "format": "png"}


def maliyet(im: Image.Image) -> tuple[int, int]:
    """(karakter, animasyon) generation. v3 reference modu: ceil(w*h*8/65536)."""
    karakter = -(-(im.width * im.height * 8) // 65536)
    return karakter, 2          # idle south + walk east, 1 gen/yon


# ---------------------------------------------------------------------------
# Durum (yarida kesilme korumasi)
# ---------------------------------------------------------------------------

class Durum:
    def __init__(self, yol: str):
        self.yol = yol
        self.d = json.load(open(yol)) if os.path.exists(yol) else {}

    def __getitem__(self, k):
        return self.d.get(k)

    def yaz(self, **kv):
        self.d.update(kv)
        os.makedirs(os.path.dirname(self.yol), exist_ok=True)
        json.dump(self.d, open(self.yol, "w"), ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Boru hatti adimlari
# ---------------------------------------------------------------------------

def karakter_yarat(im: Image.Image, tarif: str, ad: str, govde: str, durum: Durum,
                   tohum: int | None) -> str:
    if durum["character_id"] and durum["rotasyon_tamam"]:
        print(f"  1/4 karakter zaten uretilmis ({durum['character_id'][:8]}…), atlaniyor")
        return durum["character_id"]

    if not durum["character_id"]:
        print("  1/4 karakter uretiliyor (8 yone dondurme)…")
        # `name` acikca veriliyor: verilmedigi zaman PixelLab karakteri ilk
        # animasyonun adiyla yeniden adlandiriyor ("Idle") ve ZIP'teki state
        # klasoru de o adi aliyor.
        istek = {"description": tarif, "name": ad, "template_id": govde,
                 "reference_image": b64(im), "no_background": True}
        if tohum is not None:
            istek["seed"] = int(tohum)
        y = _cagir("/create-character-v3", istek)
        durum.yaz(character_id=y["character_id"], rotasyon_isi=y["background_job_id"])
    else:
        print(f"  1/4 karakter uretimi devam ediyor ({durum['character_id'][:8]}…)")

    is_bekle(durum["rotasyon_isi"], "rotasyonlar")
    durum.yaz(rotasyon_tamam=True)
    return durum["character_id"]


def animasyon_uret(karakter_id: str, sablon: str, yon: str, ad: str,
                   durum: Durum) -> None:
    anahtar = f"{ad}_isler"
    if durum[f"{ad}_tamam"]:
        print(f"  {'2' if ad == 'idle' else '3'}/4 {ad} zaten uretilmis, atlaniyor")
        return

    if not durum[anahtar]:
        print(f"  {'2' if ad == 'idle' else '3'}/4 {ad} uretiliyor "
              f"(sablon '{sablon}', yon {yon})…")
        y = _cagir("/characters/animations", {
            "character_id": karakter_id,
            "template_animation_id": sablon,
            "animation_name": ad,
            "directions": [yon],
        })
        durum.yaz(**{anahtar: y["background_job_ids"]})

    for i, jid in enumerate(durum[anahtar]):
        is_bekle(jid, f"{ad} [{i + 1}/{len(durum[anahtar])}]")
    durum.yaz(**{f"{ad}_tamam": True})


def kareleri_indir(karakter_id: str, hedef: str) -> dict[str, list[str]]:
    """Karakteri ZIP olarak indirir; {"<klip>/<yon>": [kare yollari]} doner.

    ZIP'i tercih ediyoruz cunku tek istekte butun animasyonlarin karelerini
    sirali ve ayni tuvalde veriyor — is yanitindaki URL'leri tek tek cekmek
    hem daha kirilgan hem sira garantisi yok.

    Kareler ZIP icindeki metadata.json'dan okunuyor, klasorlerde gezinerek
    DEGIL: klasor duzeni state adiyla one-kli (`Idle/animations/...`) ve klip
    adlari gonderdigimiz `animation_name` degil API'nin kendi slug'i
    (`breathing-idle` -> `animating`). metadata.json ikisini de dogru veriyor."""
    ham = _cagir(f"/characters/{karakter_id}/zip", ham=True)
    os.makedirs(hedef, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(ham)) as z:
        z.extractall(hedef)

    dizin = os.path.join(hedef, "metadata.json")
    if not os.path.exists(dizin):
        raise SystemExit(f"HATA: ZIP icinde metadata.json yok — {os.listdir(hedef)}")
    meta = json.load(open(dizin))

    klipler: dict[str, list[str]] = {}
    for durum in meta.get("states", []):
        for klip, yonler in (durum.get("frames", {}).get("animations") or {}).items():
            for yon, yollar in yonler.items():
                tam = [os.path.join(hedef, y) for y in yollar]
                if all(os.path.exists(t) for t in tam):
                    klipler[f"{klip}/{yon}"] = tam
    return klipler


def _pack(kareler: list[str], cikti: str, kutu: int | None, klip: str,
          sure: int, gif: str | None) -> int:
    """pack_sheet.py'yi cagirir; uretilen sheet'in kare kenarini doner.

    Elle dizmek yerine pack_sheet: kareler ayni tuvalde gelse bile kirpma ve
    ayak cizgisine hizalama onun isi ve depodaki butun sheet'ler oyle uretildi."""
    komut = [sys.executable, os.path.join(ARAC, "pack_sheet.py"), *kareler,
             "-o", cikti, "--clip", klip, "--duration", str(sure)]
    if kutu:
        komut += ["--box", str(kutu)]
    if gif:
        komut += ["--gif", gif]
    s = subprocess.run(komut, cwd=KOK, capture_output=True, text=True)
    if s.returncode != 0:
        raise SystemExit(f"HATA: pack_sheet basarisiz\n{s.stdout}\n{s.stderr}")
    with Image.open(cikti) as im:
        return im.height


def paketle(klipler: dict[str, list[str]], hedef: str, gif: bool) -> dict:
    """Iki klibi AYNI kare kutusuyla paketler.

    pack_sheet kutuyu her klip icin ayri hesapliyor ve idle 86 / walk 87 gibi
    farkli cikabiliyor; meta.json'da tek bir nativeFrameSize tutuldugu icin
    once ikisi olculuyor, sonra ikisi de max degeriyle yeniden paketleniyor."""
    idle = _sec(klipler, IDLE_SABLON, "south")
    walk = _sec(klipler, WALK_SABLON, "east")
    os.makedirs(hedef, exist_ok=True)

    with tempfile.TemporaryDirectory() as gecici:
        h1 = _pack(idle, os.path.join(gecici, "i.png"), None, "idle", IDLE_SURE, None)
        h2 = _pack(walk, os.path.join(gecici, "w.png"), None, "walk_right",
                   WALK_SURE, None)
    kutu = max(h1, h2)
    if h1 != h2:
        print(f"    klipler farkli kutu verdi ({h1}, {h2}) -> ikisi de {kutu}")

    _pack(idle, os.path.join(hedef, "idle_spritesheet.png"), kutu, "idle",
          IDLE_SURE, os.path.join(hedef, "onizleme_idle.gif") if gif else None)
    _pack(walk, os.path.join(hedef, "walk_right_spritesheet.png"), kutu,
          "walk_right", WALK_SURE,
          os.path.join(hedef, "onizleme_walk.gif") if gif else None)
    return {"kutu": kutu, "idle": len(idle), "walk": len(walk)}


def _sec(klipler: dict[str, list[str]], sablon: str, yon: str) -> list[str]:
    """ZIP'teki klip adlari sablon adiyla birebir ayni olmayabiliyor (animation_name
    kullaniliyor), o yuzden once tam eslesme sonra icerme araniyor."""
    for anahtar in (f"{sablon}/{yon}",):
        if anahtar in klipler:
            return klipler[anahtar]
    aday = [k for k in klipler if k.endswith(f"/{yon}")]
    if len(aday) == 1:
        return klipler[aday[0]]
    for k in aday:
        if sablon.split("-")[-1] in k.lower():
            return klipler[k]
    raise SystemExit(f"HATA: '{sablon}/{yon}' klibi ZIP'te bulunamadi. "
                     f"Bulunanlar: {', '.join(sorted(klipler)) or '(yok)'}")


def meta_yaz(hedef: str, gosterilen: str, olcu: dict, replikler: list[str],
             olcek: float) -> None:
    meta = {
        "displayName": gosterilen,
        "nativeFrameSize": olcu["kutu"],
        "displayScale": olcek,
        "idle": {"file": "idle_spritesheet.png", "frameSize": olcu["kutu"],
                 "frameCount": olcu["idle"], "frameDuration": IDLE_SURE},
        "walk_right": {"file": "walk_right_spritesheet.png",
                       "frameSize": olcu["kutu"], "frameCount": olcu["walk"],
                       "frameDuration": WALK_SURE},
        # Sola yuruyus ayri bir sheet degil: sag sheet'in aynasi. Depodaki
        # butun karakterler boyle ve bir klip daha uretmek 1 generation daha
        # demek olurdu.
        "walk_left": {"file": "walk_right_spritesheet.png",
                      "frameSize": olcu["kutu"], "frameCount": olcu["walk"],
                      "frameDuration": WALK_SURE, "flip": True},
        "walkSpeed": YURUME_HIZI,
        "lines": replikler,
    }
    with open(os.path.join(hedef, "meta.json"), "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# Etkilesimli sorular
# ---------------------------------------------------------------------------

def sorarak(args) -> None:
    """Argumanla verilmeyen alanlari sorar. UZUN girdilerde varsayilan geciyor:
    animasyon sablonlari, replikler ve kare sureleri sorulmuyor."""
    from menu import dosya_sor, evet_mi, sor          # noqa: E402

    if not args.gorsel:
        print("\n— PixelLab ile karakter uret —")
        print("  Onden bakan, seffaf zeminli, native cozunurlukte tek bir PNG verin.")
        args.gorsel = dosya_sor("Karakter gorseli")
    if not args.ad:
        tahmin = re.sub(r"[^a-z0-9]", "",
                        os.path.splitext(os.path.basename(args.gorsel))[0].lower())
        args.ad = sor("Klasor adi (kucuk harf, ASCII)", tahmin or "karakter")
    if not args.display_name:
        args.display_name = sor("Ekranda gorunecek ad", args.ad.capitalize())
    if args.tarif is None:
        args.tarif = sor("Karakter tarifi (rotasyon icin, Ingilizce)",
                         VARSAYILAN_TARIF)
    # Dort ayaklilar icin sablon degismek zorunda; iki ayakli her seyde
    # varsayilan dogru, o yuzden tek Enter'la geciliyor.
    if not evet_mi("Karakter iki ayakli mi (insan/insansi)?", True):
        while args.govde == "mannequin":
            args.govde = sor("Govde tipi (" + "/".join(GOVDELER[1:]) + ")", "cat")
            if args.govde not in GOVDELER:
                print(f"  gecersiz — sunlardan biri: {', '.join(GOVDELER)}")
                args.govde = "mannequin"
    if not args.gif:
        args.gif = evet_mi("Onizleme GIF'leri de uretilsin mi?", True)


def main(argv=None) -> int:
    global _ANAHTAR
    p = argparse.ArgumentParser(
        description="Tek bir pixel art gorselinden PixelLab ile pet karakteri uretir.")
    p.add_argument("gorsel", nargs="?", help="Onden bakan native PNG")
    p.add_argument("--ad", help="characters/ altindaki klasor adi (kucuk harf, ASCII)")
    p.add_argument("--display-name", help="Ekranda gorunecek ad")
    p.add_argument("--tarif", help=f"Rotasyon icin karakter tarifi "
                                   f"(varsayilan: {VARSAYILAN_TARIF!r})")
    p.add_argument("--govde", choices=GOVDELER, default="mannequin",
                   help="Iskeletin oturtulacagi govde tipi. Iki ayakli her sey "
                        "icin mannequin; dort ayaklilar icin turune en yakini.")
    p.add_argument("--olcek", type=float, default=1.0,
                   help="meta.json displayScale (varsayilan 1)")
    p.add_argument("--seed", type=int, help="Tekrarlanabilir uretim icin tohum")
    p.add_argument("--gif", action="store_true", help="Onizleme GIF'leri de uret")
    p.add_argument("--dry-run", action="store_true",
                   help="Maliyeti soyle, uretme")
    p.add_argument("--yeniden", action="store_true",
                   help="Kayitli durumu yok say, bastan uret (yeniden ucretlenir)")
    args = p.parse_args(argv)

    if not args.gorsel or not args.ad:
        try:
            sorarak(args)
        except (KeyboardInterrupt, EOFError):
            print("\n  iptal edildi")
            return 130
    args.tarif = args.tarif or VARSAYILAN_TARIF

    if not re.fullmatch(r"[a-z0-9_-]+", args.ad):
        print(f"HATA: klasor adi '{args.ad}' — kucuk harf + ASCII kullanin. "
              "macOS buyuk/kucuk harfe duyarsiz ama Linux/CI duyarli.",
              file=sys.stderr)
        return 1

    hedef = os.path.join(KOK, "characters", args.ad)
    if os.path.exists(os.path.join(hedef, "meta.json")) and not args.yeniden:
        print(f"HATA: characters/{args.ad}/ zaten var. Baska bir ad verin ya da "
              "--yeniden ile uzerine yazin.", file=sys.stderr)
        return 1

    im, uyarilar = gorsel_hazirla(args.gorsel)
    for u in uyarilar:
        print(f"  uyari: {u}")

    _ANAHTAR = anahtar_oku()
    kar, anim = maliyet(im)
    kalan = bakiye()
    print(f"\n  gorsel   {im.width}x{im.height}")
    print(f"  maliyet  {kar} (karakter) + {anim} (animasyon) = {kar + anim} "
          f"generation   bakiye {kalan:.1f}")
    if args.dry_run:
        return 0
    if kar + anim > kalan:
        print("HATA: bakiye yetmiyor.", file=sys.stderr)
        return 1

    calisma = os.path.join(KOK, "_data", "pixellab", args.ad)
    durum_yolu = os.path.join(calisma, "durum.json")
    if args.yeniden and os.path.exists(durum_yolu):
        os.remove(durum_yolu)
    durum = Durum(durum_yolu)

    print()
    kid = karakter_yarat(im, args.tarif, args.display_name or args.ad,
                         args.govde, durum, args.seed)
    animasyon_uret(kid, IDLE_SABLON, "south", "idle", durum)
    animasyon_uret(kid, WALK_SABLON, "east", "walk", durum)

    print("  4/4 kareler indiriliyor ve paketleniyor…")
    klipler = kareleri_indir(kid, os.path.join(calisma, "zip"))
    olcu = paketle(klipler, hedef, args.gif)
    meta_yaz(hedef, args.display_name or args.ad.capitalize(), olcu,
             VARSAYILAN_REPLIKLER, args.olcek)

    print(f"\n  characters/{args.ad}/ yazildi — kare {olcu['kutu']}px, "
          f"idle {olcu['idle']} kare, walk {olcu['walk']} kare")
    print(f"  bakiye {kalan:.1f} -> {bakiye():.1f}")

    npm = shutil.which("npm")
    if npm:
        print("\n  npm run check:")
        # Cikti bir boruya/dosyaya yonlendirildiginde print blok tamponlu olur
        # ama subprocess dogrudan yazar; flush olmadan check'in ciktisi kendi
        # satirlarimizin ONUNE gecip sirayi bozuyor.
        sys.stdout.flush()
        subprocess.run([npm, "run", "--silent", "check"], cwd=KOK)
    print(f"\n  Denemek icin:  npm start   ->  sag tik -> Karakter Değiştir -> "
          f"{args.display_name or args.ad.capitalize()}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  iptal edildi — odenmis adimlar _data/pixellab/ altinda kayitli, "
              "araci tekrar calistirinca kaldigi yerden devam eder.")
        sys.exit(130)
