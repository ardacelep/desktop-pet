#!/usr/bin/env python3
"""Tek bir karakter karesinden kukla (cutout rig) kurup yeni pozlar uretir.

Neden bu arac var: Gemini'ye metinle poz tarif etmek uc turda da basarisiz
oldu -- metin uzamsal bilgi tasimiyor, model celiskiyi gorunce referansa
sadakati seciyor ve pozu degistirmiyor. Olculdu: iki ayri sheet arasinda
alfa IoU %100, yani ayni goruntu.

Buradaki cikis yolu, pozu uretmeyi modelden almak. Karakter parcalara
bolunuyor, parcalar eklemlerden donduruluyor, ortaya kaba ama pozu DOGRU
bir kukla cikiyor.

Kritik nokta: kukla nihai sanat DEGIL. Cikti dogrudan ControlNet'e giden
bir cizgi goruntusune donusuyor, oradan da Gemini rotusuna. Bu yuzden:

  - Dondurme serbest. Normalde pixel art'ta bir uzvu 20 derece dondurmek
    yasaktir, piksel izgarasi bozulur. Burada bozulmasinin onemi yok,
    silueti tasiyan bir kontrol goruntusu uretiyoruz.
  - Parca kesimlerinin kaba olmasi sorun degil. Kolun dikdortgeni govdeden
    birkac piksel kapiyorsa siluet yine dogru cikar.

Olculen dayanak (ControlNet lineart ile, SD 1.5): kaynak oran 0.305,
uretilen 0.309 -- %1.3 sapma. Yani siluet duzeyinde poz vermek karakterin
oranlarini koruyor. OpenPose iskeleti ayni sonucu VERMEZ: iskelet sadece
eklem noktalarini tasir, aradaki eti model doldurur ve chibi oranini
insan oranina cekerek karakteri uzatir -- tam olarak Gemini'nin yaptigi
hatanin ayni.

Kullanim:
    python3 tools/rig_pose.py karakter.png --rig rig.json --poz poz.json -o kareler/
"""
from __future__ import annotations

import argparse
import json
import math
import sys

import numpy as np
from PIL import Image


# ---------------------------------------------------------------------------
# Parcalara bolme
# ---------------------------------------------------------------------------

def parcalara_bol(rgba: np.ndarray, parcalar: list[dict]) -> dict[str, np.ndarray]:
    """Her opak pikseli TEK bir parcaya atar.

    Dikdortgenler ust uste biniyor (kolun kutusu govdeyi de kapiyor), bu
    yuzden "icinde kalan her kutuya kopyala" yaklasimi pikselleri
    cogaltirdi: dondurunce ayni kol hem kolda hem govdede gorunurdu.
    Bunun yerine listedeki SIRA oncelik oluyor, her piksel kendisini ilk
    talep eden parcaya gidiyor. Uzuvlar listede once yazilir.
    """
    h, w = rgba.shape[:2]
    sahipli = np.zeros((h, w), dtype=bool)
    opak = rgba[:, :, 3] > 0
    katmanlar: dict[str, np.ndarray] = {}

    for p in parcalar:
        x0, y0, x1, y1 = p["rect"]
        kutu = np.zeros((h, w), dtype=bool)
        kutu[max(0, y0):y1, max(0, x0):x1] = True
        benim = kutu & opak & ~sahipli
        sahipli |= benim

        katman = np.zeros_like(rgba)
        katman[benim] = rgba[benim]
        katmanlar[p["ad"]] = katman

    kalan = int((opak & ~sahipli).sum())
    if kalan:
        print(f"  uyari: {kalan} opak piksel hicbir parcaya girmedi", file=sys.stderr)
    return katmanlar


def katmani_kapat(katman: np.ndarray) -> np.ndarray:
    """Parcanin ic boskluklarini komsu pikselle doldurur.

    Neden gerekli: yandan gorunuste kol govdenin ONUNDE duruyor, yani
    govdenin kolun arkasinda kalan kismi elimizdeki duz goruntude hic yok.
    Parcalari birbirini dislayacak sekilde bolunce govde katmaninda kol
    boyu bir yarik kaliyor; kol donunce o yarik siluete acik bir kesik
    olarak giriyor ve ControlNet onu gercek bir cizgi sanip render ediyor.

    Gercek bir cutout rig'de her parca kendi TAM cizimini tasir. Bizde
    tasimadigi icin yaklastiriyoruz: satir satir, en soldaki ve en sagdaki
    opak piksel arasinda kalan bosluklari en yakin opak komsunun rengiyle
    kapatiyoruz. Dis hat degismiyor, sadece ici doluyor.
    """
    kapali = katman.copy()
    alfa = katman[:, :, 3] > 0
    for y in range(katman.shape[0]):
        xs = np.flatnonzero(alfa[y])
        if xs.size < 2:
            continue
        sol, sag = xs[0], xs[-1]
        bosluk = np.flatnonzero(~alfa[y, sol:sag + 1]) + sol
        for x in bosluk:
            # ayni satirda en yakin opak piksel
            yakin = xs[np.argmin(np.abs(xs - x))]
            kapali[y, x] = katman[y, yakin]
    return kapali


# ---------------------------------------------------------------------------
# Donusum
# ---------------------------------------------------------------------------

def donus_matrisi(aci: float, capa: tuple[float, float],
                  kaydir: tuple[float, float]) -> np.ndarray:
    """Capa etrafinda dondurup sonra oteleyen 3x3 afin matris."""
    cx, cy = capa
    dx, dy = kaydir
    a = math.radians(aci)
    c, s = math.cos(a), math.sin(a)
    # once capayi orijine tasi, dondur, geri tasi, sonra otele
    return np.array([
        [c, -s, cx - c * cx + s * cy + dx],
        [s,  c, cy - s * cx - c * cy + dy],
        [0,  0, 1.0],
    ])


def _renk_ailesi(c: tuple[int, int, int]) -> str:
    """Rengi kaba bir kroma ailesine sokar (ten / mavi / notr)."""
    s = sum(c) or 1
    r, _, b = (v / s for v in c)
    if b > r + 0.06:
        return "mavi"
    if r > b + 0.06:
        return "kirmizi"
    return "notr"


def ton_eslesmesi(yakin: np.ndarray, uzak: np.ndarray) -> dict:
    """Yakin uzuv paleti ile uzak uzuv paleti arasinda iki yonlu eslesme kurar.

    Faz takasinin dayanagi: yandan gorunuste yuruyusun iki temas karesi AYNI
    geometriye sahiptir. A karesinde bacaklar {+t onde, -t arkada}, B
    karesinde de {+t, -t}. Degisen tek sey hangisinin YAKIN (acik ton, ustte
    cizilen) hangisinin UZAK (koyu ton, altta) oldugudur. Yani B karesi,
    A karesinin yeniden tonlanmis halidir -- hicbir piksel yer degistirmez.

    Bu yuzden burasi dondurmeye gore kat kat guvenli: eklem yerinde kama
    seklinde bosluk acilmiyor, uzuv kesilip tasinmadigi icin ayak yonu ters
    donmuyor, ve sonuc deterministik.

    Eslestirme parlaklik siralamasiyla DEGIL renk ailesiyle yapiliyor.
    Olculdu: ten (255,156,137)->(174,83,78), ten golgesi (216,108,96)->
    (112,48,46), ayakkabi mavisi (69,76,122)->(45,46,77). Oranlar sirasiyla
    0.68/0.53/0.57 -- sabit bir carpan yok, o yuzden "koyulastir" turu bir
    donusum yanlis sonuc verir.

    Siralama VARLIGA degil BASKINLIGA gore: "iki tarafta da bulunan renge
    dokunma" kurali denendi ve yanlis cikti. Olculdu -- iki ayakkabi da her
    iki maviyi kullaniyor, yakin olanda acik mavi baskin (21 piksele karsi 6),
    uzak olanda koyu baskin (21'e karsi 14). Varlik olcutu ikisini de "ortak"
    sayip ayakkabilari takas disi birakiyordu. Her uzvun kendi icindeki paya
    gore siralayinca dogru esleniyorlar. Ayni kural siyah konturu ve beyaz
    tabani da dogru birakiyor: onlar iki tarafta da AYNI sirada, dolayisiyla
    kendilerine esleniyorlar.
    """
    def palet(katman: np.ndarray) -> list[tuple[tuple[int, int, int], int]]:
        m = katman[:, :, 3] > 0
        if not m.any():
            return []
        v, c = np.unique(katman[m][:, :3].reshape(-1, 3), axis=0, return_counts=True)
        return [(tuple(int(t) for t in v[i]), int(c[i]))
                for i in np.argsort(-c) if c[i] >= 2]

    N, F = palet(yakin), palet(uzak)
    esles: dict = {}
    # NOTR aile bilerek disarida. Bu cizimde derinlik farki yalnizca TENDE ve
    # AYAKKABIDA ifade ediliyor -- olculdu, yakin bacak teni 188, uzak 112.
    # Sort, ceket ve siyah kontur iki uzuvda da ayni; onlar giysi rengi, mesafe
    # tonu degil. Notr aileyi de eslestirmeye sokunca sort grisi siyaha gidiyor
    # ve govdenin altinda koyu bir dikdortgen leke olusuyordu: iki tarafta
    # notr renk SAYILARI farkli oldugu icin sira eslemesi kayiyor.
    for ad in ("kirmizi", "mavi"):
        n = [c for c, _ in N if _renk_ailesi(c) == ad]   # payi buyukten kucuge
        f = [c for c, _ in F if _renk_ailesi(c) == ad]
        if not n or not f:
            continue
        for i, c in enumerate(n):
            esles[c] = f[min(i * len(f) // len(n), len(f) - 1)]
        for i, c in enumerate(f):
            esles[c] = n[min(i * len(n) // len(f), len(n) - 1)]
    return esles


def tonu_uygula(katman: np.ndarray, esles: dict) -> np.ndarray:
    """Katmandaki renkleri eslesmeye gore degistirir; eslesmeyen renk aynen kalir."""
    if not esles:
        return katman
    out = katman.copy()
    m = katman[:, :, 3] > 0
    if not m.any():
        return out
    px = out[m]
    for i, p in enumerate(px):
        yeni = esles.get(tuple(int(v) for v in p[:3]))
        if yeni is not None:
            px[i, :3] = yeni
    out[m] = px
    return out


def dinlenme_acisi(katman: np.ndarray, capa: tuple[float, float]) -> float:
    """Uzvun taban pozdaki dogal acisi: dikeyden kac derece sapmis.

    Neden olculuyor: rig taban pozunun "notr" oldugunu varsaymak yanlis
    cikti. Olculen bir ornekte Gemini'nin verdigi durusta bacaklar kalcadan
    A harfi gibi aciliyordu -- uzak bacak zaten 22 derece ONDE, yakin bacak
    13 derece GERIDE. Pozlara dikeyden sayilmis gibi +-22 derece yazinca
    hicbir kare faz takasina yetmedi: gereken degerler 44 ve 35 idi.

    Bu olcumle pozlar MUTLAK aci yazabiliyor (0 = dikey, pozitif = one
    dogru), tool farki kendi buluyor. Yeni bir karaktere gecerken aci
    tablosunu elle yeniden hesaplamak gerekmiyor.
    """
    ys, xs = np.where(katman[:, :, 3] > 0)
    if ys.size == 0:
        return 0.0
    alt = ys > capa[1]          # capanin altinda kalan kisim uzvun govdesi
    if alt.sum() < 3:
        return 0.0
    dx = float(xs[alt].mean()) - capa[0]
    dy = float(ys[alt].mean()) - capa[1]
    return math.degrees(math.atan2(dx, dy))


def zincir_matrisi(ad: str, parca_indeks: dict[str, dict],
                   poz: dict[str, dict]) -> np.ndarray:
    """Parcanin kendi donusumunu ATA zincirini takip ederek birlestirir.

    Diz, ust bacagi izlemeli: uyluk donunce baldir da onunla gitmeli, ustune
    bir de kendi acisini eklemeli. Ata olmadan her uzvu tek parca dondurmek
    zorunda kalirdik ve yuruyus tahta bacakli gorunurdu.
    """
    m = np.eye(3)
    zincir = []
    imlec = ad
    while imlec is not None:
        zincir.append(imlec)
        if imlec in [z for z in zincir[:-1]]:
            raise ValueError(f"rig'de dongu var: {ad}")
        imlec = parca_indeks[imlec].get("ata")
    for p_ad in reversed(zincir):  # kokten yaprağa
        p = parca_indeks[p_ad]
        d = poz.get(p_ad, {})
        # "temel" her pozda uygulanan sabit kayma. Neden gerekli: gercek bir
        # YANDAN gorunuste iki bacak ayni x'te durur, yakin olan uzaki gizler.
        # Ama o durusta bacaklari birbirinden KESMEK imkansiz -- ayrik piksel
        # yok. Bu yuzden rig taban pozunu bacaklar yatayda ACIK olarak
        # urettiriyoruz. Temel kayma o yapay acikligi geri kapatip iki kalcayi
        # cakistiriyor: parcalar ayri ayri kesilebiliyor AMA animasyonda
        # dogru yerden donuyorlar. Bu olmadan bacaklar taban acikligini asla
        # kapatamiyor ve faz takasi (yakin bacagin one gecmesi) hic olmuyor --
        # olculdu, dort karede de koyu bacak onde kaliyordu.
        t = p.get("temel", [0, 0])
        # Poz MUTLAK aci veriyorsa (pozitif = one dogru), uygulanacak donus
        # dinlenme acisindan farki kadar. Donus isareti saat yonu pozitif,
        # yani ayagi GERIYE goturur -- bu yuzden fark ters isaretle giriyor.
        if "mutlak" in d:
            aci = p.get("_dinlenme", 0.0) - float(d["mutlak"])
        else:
            aci = float(d.get("aci", 0.0))
        m = m @ donus_matrisi(aci,
                              tuple(p["capa"]),
                              (float(d.get("dx", 0.0)) + float(t[0]),
                               float(d.get("dy", 0.0)) + float(t[1])))
    return m


def katman_uygula(katman: np.ndarray, m: np.ndarray, boyut: tuple[int, int]) -> Image.Image:
    """Afin donusumu NEAREST ile uygular (ara renk uretmemek icin)."""
    im = Image.fromarray(katman)
    ters = np.linalg.inv(m)  # PIL hedeften kaynaga esleme istiyor
    kats = (ters[0, 0], ters[0, 1], ters[0, 2],
            ters[1, 0], ters[1, 1], ters[1, 2])
    return im.transform(boyut, Image.AFFINE, kats, resample=Image.NEAREST)


def poz_uret(rgba: np.ndarray, rig: dict, poz: dict, pay: int = 12) -> Image.Image:
    """Bir pozu cizip RGBA gorsel dondurur."""
    parcalar = rig["parcalar"]
    indeks = {p["ad"]: p for p in parcalar}
    katmanlar = parcalara_bol(rgba, parcalar)

    # Dinlenme acilari, temel kayma UYGULANMADAN olculuyor: temel sadece
    # uzvun yerini kaydiriyor, egimini degistirmiyor.
    for p in parcalar:
        p["_dinlenme"] = dinlenme_acisi(katmanlar[p["ad"]], tuple(p["capa"]))

    # Faz takasi: yakin/uzak uzuv ciftlerini yeniden tonla ve z-sirasini degistir.
    # Geometriye HIC dokunulmuyor (bkz. ton_eslesmesi).
    #
    # Kapsam onemli: takas SILUET icin dogru ama ASIMETRIK AKSESUAR icin
    # degil. Olculen ornekte karakterin yesil saati tek bir bileginde; kollari
    # takas edince saat karsi kola gecmis gorunuyor ve animasyonda kollar
    # arasinda zipliyor. Bacaklarda boyle bir sorun yok, iki ayakkabi ayni --
    # sadece tonlari farkli. Bu yuzden faz_takasi bir liste de olabiliyor:
    # ["bacak"] yazinca yalnizca *_bacak ciftleri takas ediliyor.
    istek = poz.get("faz_takasi")
    kapsam = istek if isinstance(istek, list) else None
    z_takas: dict[str, int] = {}
    if istek:
        yeni: dict[str, np.ndarray] = {}
        for ad in list(katmanlar):
            if not ad.startswith("yakin_"):
                continue
            son = ad[len("yakin_"):]
            if kapsam is not None and son not in kapsam:
                continue
            es = "uzak_" + son
            if es not in katmanlar:
                continue
            harita = ton_eslesmesi(katmanlar[ad], katmanlar[es])
            yeni[ad] = tonu_uygula(katmanlar[ad], harita)
            yeni[es] = tonu_uygula(katmanlar[es], harita)
            # Uzak olan artik yakin: ustte cizilmeli
            z_takas[ad] = indeks[es].get("z", 0)
            z_takas[es] = indeks[ad].get("z", 0)
        katmanlar.update(yeni)

    h, w = rgba.shape[:2]
    # Uzuvlar donunce cerceve disina tasabiliyor, tuvali her yandan buyutuyoruz
    bh, bw = h + 2 * pay, w + 2 * pay
    genis = {}
    for ad, k in katmanlar.items():
        if indeks[ad].get("kapat", False):
            k = katmani_kapat(k)
        g = np.zeros((bh, bw, 4), dtype=np.uint8)
        g[pay:pay + h, pay:pay + w] = k
        genis[ad] = g

    sonuc = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    for p in sorted(parcalar, key=lambda p: z_takas.get(p["ad"], p.get("z", 0))):
        ad = p["ad"]
        p2 = dict(p)
        p2["capa"] = [p["capa"][0] + pay, p["capa"][1] + pay]
        indeks2 = {k: (dict(v, capa=[v["capa"][0] + pay, v["capa"][1] + pay])
                       if "capa" in v else v) for k, v in indeks.items()}
        m = zincir_matrisi(ad, indeks2, poz.get("parcalar", {}))
        sonuc.alpha_composite(katman_uygula(genis[ad], m, (bw, bh)))
    return sonuc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("karakter", help="Kaynak kare (native pixel art, RGBA)")
    ap.add_argument("--rig", required=True, help="Parca tanimlari (JSON)")
    ap.add_argument("--poz", required=True, help="Poz listesi (JSON)")
    ap.add_argument("-o", "--out", required=True, help="Cikti klasoru")
    ap.add_argument("--onizleme", help="Tum pozlari yan yana diz")
    ap.add_argument("--olcek", type=int, default=4, help="Onizleme buyutmesi")
    args = ap.parse_args()

    rgba = np.array(Image.open(args.karakter).convert("RGBA"))
    rig = json.load(open(args.rig))
    pozlar = json.load(open(args.poz))

    from pathlib import Path
    cikti = Path(args.out)
    cikti.mkdir(parents=True, exist_ok=True)

    uretilen = []
    for i, poz in enumerate(pozlar["pozlar"], 1):
        im = poz_uret(rgba, rig, poz)
        yol = cikti / f"poz_{i}.png"
        im.save(yol)
        uretilen.append(im)
        print(f"  {yol}  {im.width}x{im.height}  ({poz.get('ad', '')})")

    if args.onizleme and uretilen:
        k = args.olcek
        w, h = uretilen[0].size
        serit = Image.new("RGBA", (w * k * len(uretilen), h * k), (255, 255, 255, 255))
        for i, im in enumerate(uretilen):
            serit.alpha_composite(im.resize((w * k, h * k), Image.NEAREST), (i * w * k, 0))
        serit.convert("RGB").save(args.onizleme)
        print(f"Onizleme: {args.onizleme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
