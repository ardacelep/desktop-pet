#!/usr/bin/env python3
"""
palette_reduce.py — AI uretimi sprite'larin sisirilmis renk paletini gercek
pixel art paletine indirir.

SORUN
    Gemini'den gelen sprite'lar native cozunurluge indirildikten sonra bile
    binlerce renk tasiyor: olculdugunde g1/idle 9981 piksel icin 2809 renk,
    fakus/walk 16715 piksel icin 7560 renk kullaniyordu. Bu renklerin buyuk
    kismi ayni tonun 1-2 birimlik kaymasi. Elle cizilmis pixel art'ta ise
    30-130 renk oluyor.

    Kritik ayrim OLCULDU. Her rengin CIELAB'da en yakin komsusuna uzakligi:

        temiz klipler (ardus, ael, mag/walk)   medyan dE 4.5 - 6.6
        kirli klipler (g1, fakus, mag/idle)    medyan dE 0.45 - 0.68

    Arada on kat fark var ve hic ortusmuyor. Yani shading icin kullanilan
    gercek tonlar gurultuden bir buyukluk mertebesi uzakta duruyor; dogru
    esikle biri silinirken digeri korunabiliyor.

BU SCRIPT NE YAPAR
    1. Bir karakterin TUM kliplerini birlikte okur. Klipler ayri ayri
       kuantize edilirse ayni ten tonu idle'da ve walk'ta 1-2 birim kayar,
       animasyon gecisinde renk titrer. Palet ortak ogreniliyor.
    2. Uzamsal aykiri pikselleri tespit edip palet ogrenirken ELER. Sebebi
       olculdu: g1'in konturunda (49,0,49) gibi magenta pikseller var ve
       k-means bunlara 32 renkten BIRINI ayirip gurultuyu pekistiriyordu.
       Aykiri pikselin komsulari siyah kontur; palete katilmayinca atama
       asamasinda en yakin palet rengine, yani kontur siyahina gidiyor.
    3. Birbirine dE < --merge-de yakin renkleri en cok kullanilanda toplar.
       Bu on temizlik k-means'i hem hizlandirir hem de cekirdek seciminin
       gurultu bulutuna takilmasini engeller.
    4. CIELAB uzayinda piksel-agirlikli k-means calistirir. RGB'de kumelemek
       yanlis olur: RGB mesafesi algisal degil, koyu tonlarda gereginden
       fazla, acik tonlarda az birlestirir.
    5. k'yi otomatik secer: piksel-agirlikli ORTALAMA dE hedefin altina
       inene kadar k'yi artirir. Once "piksellerin %95'i JND icinde" olcutu
       denendi ama tutmuyor: gurultulu bir sprite'ta her zaman uzakta kalan
       bir kuyruk oluyor ve olcut k'yi ust sinira dayiyor. Ortalama, gozle
       kayipsiz bulunan k degerleriyle ortusuyor.

TASARIM PRENSIBI
    Zaten temiz olan sprite'a DOKUNULMAZ. Ham renk sayisi --clean-under
    altindaysa ve komsu dE profili saglikliysa dosya oldugu gibi kopyalanir.
    Elle duzeltilmis ya da dogru uretilmis bir asseti "iyilestirmeye"
    calismak kazanctan cok risk.

BAGIMLILIK
    pip install numpy pillow

KULLANIM
    python3 tools/palette_reduce.py characters/g1 --out /tmp/g1
    python3 tools/palette_reduce.py characters/g1 --dry-run
    python3 tools/palette_reduce.py characters/g1 --out /tmp/g1 --preview /tmp/g1.png
    python3 tools/palette_reduce.py characters/g1 --colors 32 --in-place
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

import numpy as np
from PIL import Image

VERBOSE = False

#: Gozun iki rengi ayirt edebildigi esik (Just Noticeable Difference).
JND = 2.3


def log(*args):
    if VERBOSE:
        print(*args, file=sys.stderr)


# ---------------------------------------------------------------------------
# Renk uzayi
# ---------------------------------------------------------------------------

def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """(N,3) uint8 sRGB -> (N,3) float CIELAB (D65).

    Tum mesafe hesaplari burada yapiliyor. CIE76 (duz Oklid) kullaniyoruz;
    CIEDE2000 daha dogru ama bu isteki karar noktalari (0.5'e karsi 5.0)
    o hassasiyete ihtiyac duymayacak kadar uzak.
    """
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    M = np.array([[0.4124, 0.3576, 0.1805],
                  [0.2126, 0.7152, 0.0722],
                  [0.0193, 0.1192, 0.9505]])
    xyz = c @ M.T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[:, 1] - 16,
                     500 * (f[:, 0] - f[:, 1]),
                     200 * (f[:, 1] - f[:, 2])], axis=1)


def perceptual(lab: np.ndarray, l0: float) -> np.ndarray:
    """Koyu renklerde kroma bilesenini sonumler.

    NEDEN: g1'in konturunda olculen (42,5,39) rengi L=6.7 ama kroma=27.3 —
    neredeyse siyah bir pikselin asiri doygun olmasi. Duz CIELAB bunu siyahtan
    27 birim uzakta gorup ona ayri bir palet rengi ayiriyordu. Oysa o
    parlaklikta goz o kromayi zaten ayirt edemez; CIELAB'in bilinen zayifligi
    dusuk aydinlikta kroma farkini abartmasidir.

    Piksel sayisi olcutu bu isi yapamiyor: magenta kume 62 piksel, mesru bir
    ten tonu 61 piksel. Ayrim kroma tarafinda.

    l0 = 0 verilirse sonumleme kapanir ve duz CIELAB kullanilir.
    """
    if l0 <= 0:
        return lab
    w = np.clip(lab[:, 0:1] / l0, 0.0, 1.0)
    return np.concatenate([lab[:, 0:1], lab[:, 1:] * w], axis=1)


def rgb_to_metric(rgb: np.ndarray, l0: float) -> np.ndarray:
    """Tum mesafe hesaplarinin yapildigi uzay."""
    return perceptual(srgb_to_lab(rgb), l0)


# ---------------------------------------------------------------------------
# Uzamsal aykirilar
# ---------------------------------------------------------------------------

def spatial_outliers(lab_img: np.ndarray, alpha: np.ndarray,
                     esik: float) -> np.ndarray:
    """8-komsusunun HICBIRINE dE < esik yakin olmayan pikseller.

    Bunlar tanim geregi cizimin bir parcasi olamaz: pixel art'ta her renk ya
    bir yuzeyi kaplar ya da bir rampanin adimidir, ikisinde de en az bir
    komsusuyla akrabadir. Tek basina duran renk ya AI gurultusu ya da bilincli
    bir 1px detaydir (goz parlamasi). Ikisini de palete SOKMUYORUZ, ama
    silmiyoruz da: atama asamasinda en yakin palet rengine gidiyorlar, yani
    parlama beyaza, kontur gurultusu siyaha donuyor.
    """
    h, w = alpha.shape
    en_yakin = np.full((h, w), np.inf)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            k = np.roll(np.roll(lab_img, dy, axis=0), dx, axis=1)
            ka = np.roll(np.roll(alpha, dy, axis=0), dx, axis=1)
            d = np.linalg.norm(lab_img - k, axis=2)
            # Kenardan sarma ve seffaf komsu gecerli komsu sayilmaz
            d[ka == 0] = np.inf
            en_yakin = np.minimum(en_yakin, d)
    if h > 1:
        en_yakin[0, :] = np.minimum(en_yakin[0, :], np.inf)
    return (en_yakin >= esik) & (alpha > 0)


def despeckle(rgb: np.ndarray, lab_img: np.ndarray, alpha: np.ndarray,
              max_boyut: int, min_kroma_fark: float, max_l: float = 25.0,
              baglanti_de: float = 3.0) -> tuple[np.ndarray, int]:
    """Kucuk ve cevresine gore ASIRI DOYGUN piksel gruplarini cevre rengine cevirir.

    NEDEN AYRI BIR ADIM: g1'in konturundaki magenta pikseller ikili-uclu bitisik
    gruplar halinde, yani "komsusu yok" testine takilmiyorlar. Renk uzayinda da
    cozulmuyor: (49,0,49) siyahtan L olarak 8 birim acik, kroma sonumu uygulansa
    bile ayri bir ton olarak duruyor. O pikselin siyah OLMASI GEREKTIGI bilgisi
    renginde degil, KONUMUNDA — konturun ortasinda duruyor.

    KASITLI DETAYI NEDEN SILMIYOR: olcut sadece "kucuk" degil, "kucuk VE
    cevresinden daha doygun". Kontur gurultusu kroma yonunde sapar (siyah cevre,
    kroma 27 leke). Goz parlamasi ya da metal isigi gibi kasitli 1px detaylar
    ise PARLAKLIK yonunde sapar, kromalari cevrelerinden yuksek degildir, o
    yuzden bu filtreye takilmazlar.
    """
    h, w = alpha.shape
    kroma = np.linalg.norm(lab_img[:, :, 1:], axis=2)
    gorulmus = np.zeros((h, w), bool)
    cikti = rgb.copy()
    temizlenen = 0

    for y0 in range(h):
        for x0 in range(w):
            if gorulmus[y0, x0] or alpha[y0, x0] == 0:
                continue
            # Benzer renkli bitisik pikselleri topla (4-baglanti)
            yigin = [(y0, x0)]
            gorulmus[y0, x0] = True
            bilesen = []
            tasti = False
            while yigin:
                y, x = yigin.pop()
                bilesen.append((y, x))
                if len(bilesen) > max_boyut:
                    tasti = True
                    break
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    b, c = y + dy, x + dx
                    if not (0 <= b < h and 0 <= c < w) or gorulmus[b, c]:
                        continue
                    if alpha[b, c] == 0:
                        continue
                    if np.linalg.norm(lab_img[b, c] - lab_img[y, x]) < baglanti_de:
                        gorulmus[b, c] = True
                        yigin.append((b, c))
            if tasti:
                # Buyuk bolge: kalanini da gezip isaretle, ama dokunma
                while yigin:
                    y, x = yigin.pop()
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        b, c = y + dy, x + dx
                        if (0 <= b < h and 0 <= c < w and not gorulmus[b, c]
                                and alpha[b, c] > 0
                                and np.linalg.norm(lab_img[b, c] - lab_img[y, x])
                                < baglanti_de):
                            gorulmus[b, c] = True
                            yigin.append((b, c))
                continue

            ic = set(bilesen)
            sinir = []
            for (y, x) in bilesen:
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    b, c = y + dy, x + dx
                    if (0 <= b < h and 0 <= c < w and (b, c) not in ic
                            and alpha[b, c] > 0):
                        sinir.append((b, c))
            if not sinir:
                continue
            ic_kroma = float(np.mean([kroma[y, x] for y, x in bilesen]))
            sinir_kroma = float(np.mean([kroma[y, x] for y, x in sinir]))
            if ic_kroma - sinir_kroma < min_kroma_fark:
                continue
            # Sadece KOYU lekeler: ten ile kontur arasindaki gecis pikselleri de
            # cevrelerinden doygun cikiyor (L 40-70) ve olcut onlari da yutuyordu
            # — sonucta karakterin konturu kalinlasiyordu. Gercek kontur
            # gurultusu olculdugunde L 6-18 arasindaydi.
            ic_l = float(np.mean([lab_img[y, x, 0] for y, x in bilesen]))
            if ic_l > max_l:
                continue
            # Cevrenin en sik rengi
            renkler, sayilar = np.unique(
                np.array([rgb[y, x] for y, x in sinir]), axis=0,
                return_counts=True)
            hedef = renkler[sayilar.argmax()]
            for (y, x) in bilesen:
                cikti[y, x] = hedef
            temizlenen += len(bilesen)
    return cikti, temizlenen


# ---------------------------------------------------------------------------
# Kumeleme
# ---------------------------------------------------------------------------

def merge_near(lab: np.ndarray, agirlik: np.ndarray,
               tol: float) -> np.ndarray:
    """En cok kullanilan renkten baslayarak dE < tol olanlari ona katar.

    Donen dizi: her renk icin cekirdek indeksi (0..m-1).
    """
    atama = np.full(len(lab), -1)
    sira = np.argsort(-agirlik, kind="stable")
    m = 0
    for i in sira:
        if atama[i] != -1:
            continue
        d = np.linalg.norm(lab - lab[i], axis=1)
        atama[(atama == -1) & (d < tol)] = m
        m += 1
    return atama


def weighted_kmeans(lab: np.ndarray, agirlik: np.ndarray, k: int,
                    tur: int = 60, seed: int = 0):
    """Piksel-agirlikli k-means++ (Lab). Donen: (atama, merkezler)."""
    n = len(lab)
    if k >= n:
        return np.arange(n), lab.copy()
    rng = np.random.default_rng(seed)

    # k-means++ tohumlama, agirlikla: az kullanilan gurultu tonunun cekirdek
    # secilme olasiligi piksel payiyla oranti oluyor.
    p = agirlik / agirlik.sum()
    idx = [int(rng.choice(n, p=p))]
    d2 = ((lab - lab[idx[0]]) ** 2).sum(1)
    for _ in range(k - 1):
        q = d2 * agirlik
        q = q / q.sum() if q.sum() > 0 else p
        i = int(rng.choice(n, p=q))
        idx.append(i)
        d2 = np.minimum(d2, ((lab - lab[i]) ** 2).sum(1))

    C = lab[idx].copy()
    for _ in range(tur):
        d = np.linalg.norm(lab[:, None, :] - C[None, :, :], axis=2)
        a = d.argmin(1)
        yeni = C.copy()
        for j in range(k):
            m = a == j
            if m.any():
                yeni[j] = (lab[m] * agirlik[m, None]).sum(0) / agirlik[m].sum()
        if np.allclose(yeni, C, atol=1e-4):
            C = yeni
            break
        C = yeni
    d = np.linalg.norm(lab[:, None, :] - C[None, :, :], axis=2)
    return d.argmin(1), C


# ---------------------------------------------------------------------------
# Ana boru hatti
# ---------------------------------------------------------------------------

class Sheet:
    def __init__(self, yol: str, l0: float = 30.0):
        self.yol = yol
        self.l0 = l0
        self.ad = os.path.basename(yol)
        im = Image.open(yol).convert("RGBA")
        self.arr = np.array(im)
        self.rgb = self.arr[:, :, :3]
        self.alpha = self.arr[:, :, 3]
        h, w = self.alpha.shape
        self.temizlenen = 0
        duz = srgb_to_lab(self.rgb.reshape(-1, 3))
        #: Teshis ve aykiri tespiti duz CIELAB'da — gercek algisal farki olcuyoruz.
        self.lab_img = duz.reshape(h, w, 3)
        #: Kumeleme ve atama sonumlu uzayda.
        self.metric_img = perceptual(duz, l0).reshape(h, w, 3)

    def temizle(self, max_boyut: int, min_kroma_fark: float,
                max_l: float = 25.0):
        """despeckle'i uygulayip renk uzaylarini yeniden kurar."""
        if max_boyut <= 0:
            return
        yeni, n = despeckle(self.rgb, self.lab_img, self.alpha,
                            max_boyut, min_kroma_fark, max_l)
        self.temizlenen = n
        if not n:
            return
        self.rgb = yeni
        self.arr = np.dstack([yeni, self.alpha])
        h, w = self.alpha.shape
        duz = srgb_to_lab(yeni.reshape(-1, 3))
        self.lab_img = duz.reshape(h, w, 3)
        self.metric_img = perceptual(duz, self.l0).reshape(h, w, 3)

    @property
    def renk_sayisi(self) -> int:
        d = self.rgb[self.alpha > 0]
        return len(np.unique(d, axis=0)) if len(d) else 0

    def komsu_de_medyani(self) -> float:
        """Renkler arasi en yakin komsu dE'sinin medyani — kirlilik gostergesi."""
        d = self.rgb[self.alpha > 0]
        if len(d) < 2:
            return float("inf")
        renk = np.unique(d, axis=0)
        if len(renk) > 3000:                   # pairwise patlamasin
            renk = renk[np.random.default_rng(0).choice(len(renk), 3000,
                                                        replace=False)]
        lab = srgb_to_lab(renk)
        m = np.linalg.norm(lab[:, None, :] - lab[None, :, :], axis=2)
        np.fill_diagonal(m, np.inf)
        return float(np.median(m.min(axis=1)))


def palet_ogren(sheets: list[Sheet], k: int | None, merge_de: float,
                outlier_de: float, hedef_de: float, max_colors: int,
                seed: int, l0: float = 30.0):
    """Tum kliplerden ORTAK palet ogrenir. Donen: (palet_rgb, rapor)."""
    renkler = []
    agirliklar = []
    elenen = 0
    for s in sheets:
        ayk = spatial_outliers(s.lab_img, s.alpha, outlier_de)
        gecerli = (s.alpha > 0) & ~ayk
        elenen += int(ayk.sum())
        d = s.rgb[gecerli]
        if len(d):
            r, c = np.unique(d, axis=0, return_counts=True)
            renkler.append(r)
            agirliklar.append(c)
    if not renkler:
        raise SystemExit("Opak piksel bulunamadi.")

    ham = np.concatenate(renkler)
    ham_w = np.concatenate(agirliklar)
    # Ayni renk birden fazla klipte gecebilir; agirliklari topla
    renk, ters = np.unique(ham, axis=0, return_inverse=True)
    agirlik = np.zeros(len(renk))
    np.add.at(agirlik, ters, ham_w)
    lab = rgb_to_metric(renk, l0)      # kumeleme uzayi
    lab_duz = srgb_to_lab(renk)        # hata olcumu: sonumden bagimsiz kalsin

    # 1) On temizlik
    grup = merge_near(lab, agirlik, merge_de)
    m = grup.max() + 1
    ara_rgb = np.zeros((m, 3))
    ara_w = np.zeros(m)
    for j in range(m):
        sel = grup == j
        ara_w[j] = agirlik[sel].sum()
        ara_rgb[j] = (renk[sel].astype(float) * agirlik[sel, None]).sum(0) / ara_w[j]
    ara_lab = rgb_to_metric(np.rint(ara_rgb).astype(np.uint8), l0)
    log(f"  on temizlik: {len(renk)} -> {m} renk (dE < {merge_de})")

    # 2) k secimi
    def calistir(kk):
        at, _ = weighted_kmeans(ara_lab, ara_w, kk, seed=seed)
        pal = np.zeros((at.max() + 1, 3))
        for j in range(at.max() + 1):
            sel = at == j
            if sel.any():
                pal[j] = ((ara_rgb[sel] * ara_w[sel, None]).sum(0)
                          / ara_w[sel].sum())
        pal = np.rint(pal).astype(np.uint8)
        # Her ORIJINAL rengin son rengine dE'si, piksel agirlikli
        tam = at[grup]
        dE = np.linalg.norm(lab_duz - srgb_to_lab(pal)[tam], axis=1)
        sirali = np.argsort(dE)
        birikim = np.cumsum(agirlik[sirali])
        p95 = float(dE[sirali][np.searchsorted(birikim, birikim[-1] * 0.95)])
        ort = float((dE * agirlik).sum() / agirlik.sum())
        return pal, tam, ort, p95

    if k is not None:
        pal, tam, ort, p95 = calistir(k)
        secilen = k
    else:
        adaylar = [n for n in (8, 12, 16, 20, 24, 32, 40, 48, 56, 64, 80, 96)
                   if n <= max_colors]
        if not adaylar or adaylar[-1] < max_colors:
            adaylar.append(max_colors)
        pal = tam = None
        for kk in adaylar:
            pal, tam, ort, p95 = calistir(kk)
            secilen = kk
            log(f"  k={kk:3d} -> ort dE {ort:.2f}, p95 dE {p95:.2f}")
            if ort <= hedef_de:
                break

    rapor = {"ham_renk": len(renk), "on_temizlik": m, "k": secilen,
             "palet": len(np.unique(tam)), "ort_de": ort, "p95_de": p95,
             "elenen_aykiri": elenen}
    # Kullanilmayan palet girdilerini at
    kullanilan = np.unique(tam)
    yeniden = np.full(len(pal), -1)
    yeniden[kullanilan] = np.arange(len(kullanilan))
    return pal[kullanilan], rapor


def palet_uygula(s: Sheet, palet: np.ndarray) -> Image.Image:
    """Her opak pikseli en yakin palet rengine atar. Alfa'ya dokunmaz."""
    pal_lab = rgb_to_metric(palet, s.l0)
    h, w = s.alpha.shape
    duz = s.metric_img.reshape(-1, 3)
    opak = (s.alpha > 0).reshape(-1)
    cikti = s.arr.reshape(-1, 4).copy()
    if opak.any():
        d = np.linalg.norm(duz[opak][:, None, :] - pal_lab[None, :, :], axis=2)
        cikti[opak, :3] = palet[d.argmin(1)]
    return Image.fromarray(cikti.reshape(h, w, 4))


def onizleme_yaz(ciftler, yol, olcek=4):
    """Once/sonra karsilastirmasi — sayilarin yakalayamadigi bozulmalar icin."""
    from PIL import ImageDraw, ImageFont
    try:
        f = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 15)
    except OSError:
        f = ImageFont.load_default()
    kare = max(im.height for _, im, _ in ciftler)
    W = len(ciftler) * 2 * (kare * olcek + 10) + 20
    H = kare * olcek + 60
    out = Image.new("RGBA", (W, H), (36, 38, 46, 255))
    d = ImageDraw.Draw(out)
    x = 20
    for ad, once, sonra in ciftler:
        for etiket, im in (("once", once), ("sonra", sonra)):
            k = im.crop((0, 0, min(im.height, im.width), im.height))
            out.alpha_composite(k.resize((kare * olcek, kare * olcek),
                                         Image.NEAREST), (x, 32))
            d.text((x, 36 + kare * olcek), f"{ad} — {etiket}", font=f,
                   fill=(255, 235, 160, 255))
            x += kare * olcek + 10
    out.convert("RGB").save(yol)


def main(argv=None):
    global VERBOSE
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("hedef", help="Karakter klasoru (characters/g1) veya tek PNG")
    p.add_argument("--out", help="Cikti klasoru (yoksa olusturulur)")
    p.add_argument("--in-place", action="store_true",
                   help="Dosyalarin uzerine yaz (yaninda .bak birakir)")
    p.add_argument("--dry-run", action="store_true",
                   help="Hicbir sey yazma, sadece olcup raporla")
    p.add_argument("--colors", type=int, default=None, metavar="N",
                   help="Palet boyutunu elle sabitle (varsayilan: otomatik)")
    p.add_argument("--max-colors", type=int, default=64,
                   help="Otomatik secimde ust sinir (varsayilan 64)")
    p.add_argument("--target-de", type=float, default=2.0, metavar="DE",
                   help="Agirlikli ortalama dE bunun altina insin (varsayilan 2.0)")
    p.add_argument("--merge-de", type=float, default=2.0, metavar="DE",
                   help="On temizlikte birlestirme esigi (varsayilan 2.0)")
    p.add_argument("--outlier-de", type=float, default=10.0, metavar="DE",
                   help="Uzamsal aykiri esigi (varsayilan 10.0)")
    p.add_argument("--no-outliers", action="store_true",
                   help="Uzamsal aykiri elemesini kapat")
    p.add_argument("--speck", type=int, default=4, metavar="N",
                   help="Bu boyuta kadar olan asiri doygun leke gruplari cevre "
                        "rengine cevrilir; 0 = kapali (varsayilan 4)")
    p.add_argument("--speck-chroma", type=float, default=10.0, metavar="C",
                   help="Leke sayilmak icin cevreye gore gereken kroma farki "
                        "(varsayilan 10)")
    p.add_argument("--speck-max-l", type=float, default=25.0, metavar="L",
                   help="Leke temizligi sadece bu L degerinin altindaki koyu "
                        "gruplara uygulanir (varsayilan 25)")
    p.add_argument("--dark-chroma", type=float, default=30.0, metavar="L",
                   help="Bu L degerinin altinda kroma sonumlenir; 0 = kapali "
                        "(varsayilan 30)")
    p.add_argument("--clean-under", type=int, default=160, metavar="N",
                   help="Bu kadar az renkli klipler zaten temiz sayilir (varsayilan 160)")
    p.add_argument("--force", action="store_true",
                   help="Zaten temiz olsa bile isle")
    p.add_argument("--preview", metavar="PNG", help="Once/sonra karsilastirmasi")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args(argv)
    VERBOSE = a.verbose

    if os.path.isdir(a.hedef):
        yollar = sorted(os.path.join(a.hedef, f) for f in os.listdir(a.hedef)
                        if f.endswith("_spritesheet.png"))
    else:
        yollar = [a.hedef]
    if not yollar:
        raise SystemExit(f"{a.hedef} altinda *_spritesheet.png bulunamadi.")

    sheets = [Sheet(y, a.dark_chroma) for y in yollar]
    print(f"{a.hedef}: {len(sheets)} klip")
    kirli = False
    for s in sheets:
        n = s.renk_sayisi
        med = s.komsu_de_medyani()
        temiz = n <= a.clean_under and med >= 3.0
        kirli = kirli or not temiz
        print(f"  {s.ad:34s} {n:5d} renk, komsu dE medyani {med:5.2f}"
              f"  {'temiz' if temiz else 'KIRLI'}")

    if not kirli and not a.force:
        print("\nButun klipler zaten temiz — dokunulmadi. (--force ile zorlayabilirsin)")
        return 0

    # Leke temizligi teshisTEN SONRA: zaten temiz bir karaktere dokunmuyoruz.
    for s in sheets:
        s.temizle(a.speck, a.speck_chroma, a.speck_max_l)
    lekeler = sum(s.temizlenen for s in sheets)
    if lekeler:
        print(f"\nleke temizligi: {lekeler} piksel cevre rengine cevrildi")

    palet, r = palet_ogren(sheets, a.colors, a.merge_de,
                           float("inf") if a.no_outliers else a.outlier_de,
                           a.target_de, a.max_colors, a.seed, a.dark_chroma)
    print(f"\nortak palet: {r['ham_renk']} renk -> on temizlik {r['on_temizlik']}"
          f" -> k={r['k']} -> {len(palet)} renk")
    print(f"  agirlikli ort dE {r['ort_de']:.2f}, p95 dE {r['p95_de']:.2f}, "
          f"uzamsal aykiri elenen {r['elenen_aykiri']} piksel")

    ciftler = [(s.ad.replace("_spritesheet.png", ""),
                Image.fromarray(s.arr), palet_uygula(s, palet)) for s in sheets]

    if a.preview:
        onizleme_yaz(ciftler, a.preview)
        print(f"  onizleme: {a.preview}")

    if a.dry_run:
        print("\n--dry-run: dosya yazilmadi.")
        return 0
    if not a.out and not a.in_place:
        print("\n--out ya da --in-place vermedin, dosya yazilmadi.")
        return 0

    for s, (_, _, sonra) in zip(sheets, ciftler):
        if a.in_place:
            shutil.copy2(s.yol, s.yol + ".bak")
            hedef = s.yol
        else:
            os.makedirs(a.out, exist_ok=True)
            hedef = os.path.join(a.out, s.ad)
        sonra.save(hedef)
        print(f"  yazildi: {hedef}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
