#!/usr/bin/env python3
"""pixellab_karakter.py'nin AG'A CIKMAYAN parcalarinin testleri.

    python3 tools/test_pixellab_karakter.py

Uretim adimlari gercek para harciyor, o yuzden burada test edilen sey hazirlik
ve paketleme mantigi: gorsel kapisi, maliyet hesabi, ZIP icindeki klibi secme
ve durum dosyasinin yarida kesilmeyi kurtarmasi. Bunlar yanlis oldugunda hata
UCRET ODENDIKTEN sonra ortaya cikardi.
"""
import json
import os
import sys
import tempfile

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pixellab_karakter as pk  # noqa: E402

gecen = basarisiz = 0


def kontrol(kosul, mesaj):
    global gecen, basarisiz
    if kosul:
        gecen += 1
        print(f"  ok   {mesaj}")
    else:
        basarisiz += 1
        print(f"  HATA {mesaj}")


def hata_bekle(fn, parca, mesaj):
    try:
        fn()
    except SystemExit as e:
        kontrol(parca.lower() in str(e).lower(),
                f"{mesaj} (mesajda '{parca}' gecti mi)")
        return
    kontrol(False, f"{mesaj} — hata bekleniyordu, gelmedi")


def gorsel(w, h, opaklik=0.3):
    """Ust kismi seffaf, altta figur olan sahte bir sprite."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dolu = max(1, int(h * opaklik))
    for y in range(h - dolu, h):
        for x in range(w // 4, 3 * w // 4):
            im.putpixel((x, y), (200, 100, 50, 255))
    return im


def gecici_png(im):
    yol = tempfile.mktemp(suffix=".png")
    im.save(yol)
    return yol


print("gorsel_hazirla")
im, uyari = pk.gorsel_hazirla(gecici_png(gorsel(64, 64)))
kontrol(im.size == (64, 64) and not uyari, "kare ve seffaf gorsel oldugu gibi gecer")

im, uyari = pk.gorsel_hazirla(gecici_png(gorsel(48, 64)))
kontrol(im.size == (64, 64), "kare olmayan gorsel kare kutuya alinir")
kontrol(any("kare kutuya" in u for u in uyari), "kare kutu uyarisi verilir")
# Ayaklar alt kenarda kalmali: en alt satirda opak piksel olmali
kontrol(im.getchannel("A").crop((0, 63, 64, 64)).getextrema()[1] > 0,
        "dikeyde alta yaslanir (ayaklar alt kenarda)")

opak = Image.new("RGBA", (64, 64), (10, 20, 30, 255))
_, uyari = pk.gorsel_hazirla(gecici_png(opak))
kontrol(any("seffaf" in u for u in uyari), "opak zemin uyari uretir")

hata_bekle(lambda: pk.gorsel_hazirla(gecici_png(gorsel(512, 512))),
           "pixelart_extract", "256'dan buyuk gorsel reddedilir")
hata_bekle(lambda: pk.gorsel_hazirla(gecici_png(gorsel(16, 16))),
           "en az", "32'den kucuk gorsel reddedilir")

print("\nmaliyet")
kontrol(pk.maliyet(gorsel(87, 87)) == (1, 2), "87x87 -> 1 + 2 generation")
kontrol(pk.maliyet(gorsel(128, 128)) == (2, 2), "128x128 -> 2 + 2 generation")
kontrol(pk.maliyet(gorsel(256, 256)) == (8, 2), "256x256 -> 8 + 2 generation")

print("\n_sec (ZIP icindeki klibi bulma)")
k = {"breathing-idle/south": ["a.png"], "walk/east": ["b.png"]}
kontrol(pk._sec(k, "breathing-idle", "south") == ["a.png"], "tam eslesme bulunur")
kontrol(pk._sec(k, "walk", "east") == ["b.png"], "ikinci klip bulunur")
# API animation_name'i degistirebiliyor; yonde tek aday varsa ona duselim
kontrol(pk._sec({"nefes/south": ["c.png"]}, "breathing-idle", "south") == ["c.png"],
        "ad tutmasa da yonde tek aday varsa o secilir")
hata_bekle(lambda: pk._sec({"walk/east": ["b.png"]}, "breathing-idle", "south"),
           "bulunamadi", "olmayan klip acik hata verir")

print("\nDurum (yarida kesilme)")
with tempfile.TemporaryDirectory() as d:
    yol = os.path.join(d, "alt", "durum.json")
    s = pk.Durum(yol)
    kontrol(s["character_id"] is None, "bos durum None doner")
    s.yaz(character_id="abc", rotasyon_tamam=True)
    kontrol(pk.Durum(yol)["character_id"] == "abc", "yazilan durum geri okunur")
    pk.Durum(yol).yaz(idle_tamam=True)
    d2 = pk.Durum(yol)
    kontrol(d2["character_id"] == "abc" and d2["idle_tamam"],
            "ikinci yazim oncekini korur")

print("\nmeta_yaz")
with tempfile.TemporaryDirectory() as d:
    pk.meta_yaz(d, "Kedi", {"kutu": 88, "idle": 4, "walk": 8}, ["Selam!"], 1.5)
    m = json.load(open(os.path.join(d, "meta.json")))
    kontrol(m["nativeFrameSize"] == 88 and m["displayScale"] == 1.5,
            "kare kutusu ve olcek yazilir")
    kontrol(m["idle"]["frameCount"] == 4 and m["walk_right"]["frameCount"] == 8,
            "kare sayilari yazilir")
    kontrol(m["walk_left"]["flip"] is True
            and m["walk_left"]["file"] == m["walk_right"]["file"],
            "sola yuruyus sag sheet'in aynasi")
    kontrol(all(k["frameSize"] == m["nativeFrameSize"]
                for k in (m["idle"], m["walk_right"], m["walk_left"])),
            "butun klipler ayni kare kutusunda")

print(f"\n{gecen} gecti, {basarisiz} basarisiz")
sys.exit(1 if basarisiz else 0)
