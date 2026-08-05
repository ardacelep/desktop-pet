#!/usr/bin/env python3
"""
pixelart_extract.py — AI'nin urettigi "buyutulmus" pixel art'i NATIVE cozunurluge indirir.

SORUN
    Gemini'ye pixel art urettirdiginizde 1024x1024 (veya 2048x2048) bir PNG geliyor,
    ama gorseldeki gercek pixel art ornegin 100x100. Yani her "sanal piksel" ~10.24
    gercek piksellik bir blok olarak render edilmis. Ayrica seffaflik gercek degil:
    arka plana dama (checkerboard) deseni CIZILMIS durumda.

BU SCRIPT NE YAPAR
    1. Izgarayi (grid) tespit eder: periyot VE faz, ikisi de ondalikli olabilir.
       Aday periyotlar sinir konumlarindan cikarilir, ama SECIM hucre ici varyansla
       yapilir — sinir skoru kucuk periyotlara sistematik olarak yanli.
    2. Her hucrenin merkezinden baskin rengi ornekleyerek native cozunurluge iner.
    3. Dama desenini gercek alfa seffafligina cevirir. Dama tonlari sabit degil:
       her satir/sutun icin kenar seridinden AYRI ornekleniyor, cunku render'da
       ton goruntu boyunca kayabiliyor. Tolerans da olculerek seciliyor.
    4. Kalan kucuk artefaktlari temizler ve kenar bosluklarini kirpar.

ONCEKI SCRIPTLERDEN FARKI — KOK SEBEP DUZELTMESI
    Eski surumler blok boyutunu TAM SAYIYA yuvarliyordu (`block = 10`, `arr[i*block:...]`).
    Gercek periyot 1024/100 = 10.24 oldugunda, hucre basina 0.24 pikselllik hata
    100 hucre boyunca BIRIKIYOR: son hucrelerde ornekleme noktasi 24 piksel kayiyor
    ve komsu hucreden renk okunuyor. Karakterin alt/sag kenarindaki (ayakkabilar,
    omuz hizasi) aciklanamayan lekelerin sebebi buydu — leke temizleyicinin
    esigi degil, ORNEKLEME KOORDINATI yanlisti.
    Bu surum periyodu ondalikli tutar (10.24) ve ayrica IZGARA FAZINI da olcer,
    yani ilk hucre 0'dan baslamak zorunda degil. Kayma birikmez.

TASARIM PRENSIBI (degistirmeyin)
    Karakter ASLA zorla sabit bir boyuta (88x88 gibi) olceklenmez. Native cozunurluk
    ne cikarsa odur (100x100, 44x90, 128x128 hepsi normaldir). Sebebi: sabit boyuta
    sikistirmak, dusuk kontrastli kucuk detaylari (golgeli bir goz gibi) baskin renge
    yenilterek TAMAMEN yok ediyordu. Ekranda tutarli boyut gerekiyorsa bu, uygulama
    katmaninda (CSS/canvas scale, meta.json'daki displayHeight) yapilir.

BAGIMLILIK
    pip install numpy pillow          (scipy'ye gerek yok)

KULLANIM
    python3 pixelart_extract.py girdi.png cikti.png
    python3 pixelart_extract.py girdi.png cikti.png --verbose --debug-dir ./debug
    python3 pixelart_extract.py girdi.png cikti.png --preview onizleme.png --preview-scale 8
    python3 pixelart_extract.py girdi.png cikti.png --verify   # kayipsizligi olcup raporlar
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

import numpy as np
from PIL import Image

VERBOSE = False


def log(*args):
    if VERBOSE:
        print(*args)


# ---------------------------------------------------------------------------
# Kucuk goruntu yardimcilari (scipy bagimliligi olmasin diye elle yazildi)
# ---------------------------------------------------------------------------

def pack_rgb(rgb: np.ndarray) -> np.ndarray:
    """(...,3) uint8 diziyi tek bir int32'ye paketler — mode/unique islemleri
    tuple listelerine kiyasla ~50x hizlanir."""
    a = rgb.astype(np.int32)
    return (a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]


def unpack_rgb(packed: int) -> tuple[int, int, int]:
    return ((packed >> 16) & 255, (packed >> 8) & 255, packed & 255)


def label_components(mask: np.ndarray, connectivity: int = 4):
    """Bagli bilesenleri etiketler. mask: bool (H,W). Donen: (labels int32, adet).
    Etiketler 1'den baslar, 0 = maskenin disi."""
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    if connectivity == 4:
        offs = ((-1, 0), (1, 0), (0, -1), (0, 1))
    else:
        offs = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))

    current = 0
    stack: list[tuple[int, int]] = []
    for sy in range(h):
        for sx in range(w):
            if not mask[sy, sx] or labels[sy, sx]:
                continue
            current += 1
            labels[sy, sx] = current
            stack.append((sy, sx))
            while stack:
                y, x = stack.pop()
                for dy, dx in offs:
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not labels[ny, nx]:
                        labels[ny, nx] = current
                        stack.append((ny, nx))
    return labels, current


def flood_from_seeds(allowed: np.ndarray, seeds: np.ndarray, connectivity: int = 4) -> np.ndarray:
    """`allowed` icinde, `seeds` noktalarindan ulasilabilen tum pikselleri isaretler.
    Histerezis esikleme icin kullaniliyor: zayif maske icinde, guclu tohumlardan yayil."""
    h, w = allowed.shape
    out = np.zeros((h, w), dtype=bool)
    offs = ((-1, 0), (1, 0), (0, -1), (0, 1)) if connectivity == 4 else (
        (-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))

    ys, xs = np.where(seeds & allowed)
    stack = list(zip(ys.tolist(), xs.tolist()))
    for y, x in stack:
        out[y, x] = True
    while stack:
        y, x = stack.pop()
        for dy, dx in offs:
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and allowed[ny, nx] and not out[ny, nx]:
                out[ny, nx] = True
                stack.append((ny, nx))
    return out


# ---------------------------------------------------------------------------
# 1) Izgara tespiti — periyot ve faz (ikisi de ondalikli)
# ---------------------------------------------------------------------------

def lattice_edges(period: float, phase: float, size: int,
                  min_overlap: float = 0.5) -> np.ndarray:
    """Izgarayi SONSUZ bir kafes kabul edip [0, size] araligini kaplayan hucre
    sinirlarini dondurur.

    Faz kadar iceriden baslamak yerine kafesi geriye dogru da uzatmak sart: aksi
    halde faz buyudukce bastaki hucre dusuyor, hem goruntunun kenari kirpiliyor hem
    de faz arayan optimizasyon "daha az piksel kapsa, ortalama varyans dussun"
    yonunde YANLI hale geliyordu (olculen: 100 hucrelik bir izgara 98'e duyuyordu).
    Bu haliyle her faz ayni pikselleri kapsiyor, dolayisiyla varyanslar kiyaslanabilir.

    Tuvale yarisindan azi tasan uc hucreler atilir, kalanlar [0, size] araligina
    kirpilir."""
    k0 = int(np.floor((0.0 - phase) / period))
    k1 = int(np.ceil((size - phase) / period))
    lines = phase + np.arange(k0, k1 + 1) * period

    left = np.maximum(lines[:-1], 0.0)
    right = np.minimum(lines[1:], float(size))
    keep = np.where((right - left) >= min_overlap * period)[0]
    if len(keep) == 0:
        return np.array([0.0, float(size)])

    first, last = int(keep[0]), int(keep[-1])
    edges = lines[first:last + 2].copy()
    edges[0] = max(edges[0], 0.0)
    edges[-1] = min(edges[-1], float(size))
    return edges


@dataclass
class AxisGrid:
    period: float   # bir pixel-art hucresinin kac gercek piksel oldugu (ondalikli!)
    phase: float    # kafesin ofseti (0 olmak zorunda degil, negatif de olabilir)
    count: int      # eksende kac hucre var
    quality: float  # 0..1, izgaranin oturma kalitesi

    def edges(self, size: int) -> np.ndarray:
        """Hucre sinirlarini dondurur: count+1 adet ondalikli konum."""
        e = lattice_edges(self.period, self.phase, size)
        return e[:self.count + 1] if len(e) > self.count + 1 else e


def line_diff_shape(arr: np.ndarray) -> tuple[float, float]:
    """Her eksen icin komsu satir/sutun farklarinin MEDYAN/ORTALAMA oranini verir.

    Bu oran, farklarin dagiliminin bicimini olcer ve olcekten bagimsizdir:
      - Buyutulmus pixel art'ta dagilim IKI TEPELI olur. Komsu ciftlerin cogu ayni
        blogun icindedir (fark ~ gurultu), azinlik bir kismi blok siniridir (fark
        buyuk). Medyan gurultu seviyesinde kalir, ortalamayi sinirlar yukari ceker,
        oran kucuk cikar.
      - Native bir gorselde (ya da illustrasyonda) boyle bir ayrim yok; dagilim tek
        tepeli, medyan ile ortalama birbirine yakin, oran 1'e yaklasir."""
    a = arr.astype(np.float32)
    out = []
    for axis in (1, 0):
        keep = tuple(i for i in (0, 1, 2) if i != axis)
        d = np.abs(np.diff(a, axis=axis)).mean(axis=keep)
        out.append(float(np.median(d) / max(float(d.mean()), 1e-6)))
    return out[0], out[1]


def looks_already_native(arr: np.ndarray, max_shape_ratio: float = 0.7) -> bool:
    """Gorsel zaten native cozunurlukte mi? Bu on kontrol olmadan, zaten native bir
    dosya verildiginde izgara tespiti anlamsiz bir periyot uydurabiliyor.

    Onceki surum "komsu sutunlarin yuzde kaci birbirinden 1 birimden az farkli"
    diye soruyordu. Bu MUTLAK esik kirilgan cikti: sikistirma gurultusu olan bir
    Gemini ciktisinda blok ici farklar 1'in biraz uzerine ciktigi icin gorsel
    "zaten native" sanildi ve 1024x1024'luk bir sheet (gercek cozunurlugu 128x128)
    hic indirgenmeden, 40 bin renkle kaydedildi.

    Yerine olcekten bagimsiz bir bicim olcutu kullaniliyor. 25 gercek dosyada
    olculdu: buyutulmus olanlar 0.28-0.52 araliginda, native pixel art ve
    illustrasyonlar 0.85-1.01 araliginda. Esik ikisinin arasindaki bosluga
    konuldu."""
    return max(line_diff_shape(arr)) >= max_shape_ratio


def boundary_signal(arr: np.ndarray, axis: int) -> np.ndarray:
    """Eksen boyunca renk degisim enerjisi. axis=1 -> dikey sinirlar (x ekseni)."""
    diff = np.abs(np.diff(arr.astype(np.float64), axis=axis))
    reduce_axes = tuple(i for i in range(3) if i != axis)
    return diff.sum(axis=reduce_axes)


def cluster_boundaries(sig: np.ndarray, k_sigma: float = 0.5):
    """Esigi asan komsu indeksleri tek bir sinira indirger (anti-aliasing yuzunden
    bir sinir 1-2 piksele yayilabiliyor). Donen: (konumlar, agirliklar)."""
    thresh = sig.mean() + sig.std() * k_sigma
    idx = np.where(sig > thresh)[0]
    if len(idx) == 0:
        return np.array([]), np.array([])

    groups, cur = [], [idx[0]]
    for i in idx[1:]:
        if i - cur[-1] <= 2:
            cur.append(i)
        else:
            groups.append(cur)
            cur = [i]
    groups.append(cur)

    pos, wt = [], []
    for g in groups:
        g = np.array(g)
        w = sig[g]
        # agirlikli merkez; +0.5 cunku diff[i], i ile i+1 arasindaki siniri temsil eder
        pos.append(float((g * w).sum() / w.sum()) + 0.5)
        wt.append(float(w.sum()))
    return np.array(pos), np.array(wt)


def _lattice_quality(pos: np.ndarray, wt: np.ndarray, period: float) -> tuple[float, float]:
    """Dairesel istatistik: tum sinirlar `period` periyotlu bir kafese oturuyorsa
    R ~ 1 cikar. Donen: (R, faz)."""
    z = (wt * np.exp(2j * np.pi * pos / period)).sum() / wt.sum()
    phase = (np.angle(z) / (2 * np.pi)) * period
    return float(abs(z)), float(phase % period)


def _refine_lsq(pos: np.ndarray, wt: np.ndarray, period: float, phase: float,
                iters: int = 10) -> tuple[float, float, float]:
    """Aykiri sinirlari eleyerek agirlikli en kucuk karelerle periyot+fazi keskinlestirir.
    Dairesel tahmin kabadir (bu gorselde 10.28 veriyordu); LSQ onu 10.24'e oturtuyor."""
    for _ in range(iters):
        k = np.round((pos - phase) / period)
        residual = pos - (phase + k * period)
        keep = np.abs(residual) <= 0.30 * period
        if keep.sum() < 3:
            break
        P, K, W = pos[keep], k[keep], wt[keep]
        A = np.stack([np.ones_like(K), K], axis=1) * W[:, None]
        phase, period = np.linalg.lstsq(A, P * W, rcond=None)[0]

    k = np.round((pos - phase) / period)
    residual = pos - (phase + k * period)
    inliers = np.abs(residual) <= 0.30 * period
    return float(period), float(phase), float(inliers.mean())


class AxisVariance:
    """Bir eksen icin hucre ici varyansi hizli sorgulanabilir hale getirir.

    Kumulatif toplamlar BIR KEZ hesaplanir, sonra her (periyot, faz) sorgusu sadece
    hucre sayisi kadar islem. Boylece yuzlerce aday izgarayi denemek pratik oluyor."""

    def __init__(self, arr: np.ndarray, axis: int, row_step: int = 4):
        A = arr.astype(np.float64)
        if axis == 0:
            A = A.transpose(1, 0, 2)
        A = A[::row_step]                      # satir altornekleme: varyans tahmini bozulmaz
        self.size = A.shape[1]
        self.channels = A.shape[2]
        zeros = np.zeros((A.shape[0], 1, A.shape[2]))
        self.cumsum = np.concatenate([zeros, np.cumsum(A, axis=1)], axis=1)
        self.cumsum2 = np.concatenate([zeros, np.cumsum(A * A, axis=1)], axis=1)

    def variance(self, period: float, phase: float) -> float:
        """Hucre sinirlarindan 1px iceride kalan bolgelerin agirlikli varyansi.

        Hucreler `lattice_edges` ile sayildigi icin her faz ayni pikselleri kapsar —
        yoksa optimizasyon kapsamayi kucultmeyi "iyilesme" sanardi."""
        if period < 3:
            return float("inf")
        edges = lattice_edges(period, phase, self.size)
        if len(edges) < 5:
            return float("inf")
        a = np.ceil(edges[:-1] + 1).astype(int)
        b = np.floor(edges[1:] - 1).astype(int)
        keep = (b > a) & (a >= 0) & (b <= self.size)
        a, b = a[keep], b[keep]
        if len(a) < 4:
            return float("inf")
        count = (b - a)[None, :, None]
        s = self.cumsum[:, b, :] - self.cumsum[:, a, :]
        s2 = self.cumsum2[:, b, :] - self.cumsum2[:, a, :]
        var = s2 / count - (s / count) ** 2
        return float((var * count).sum() / (count.sum() * self.channels))

    def best_phase(self, period: float, steps: int = 24) -> tuple[float, float]:
        """Varyansi en aza indiren fazi bulur. Donen: (faz, varyans)."""
        phases = np.linspace(0.0, period, steps, endpoint=False)
        values = [self.variance(period, float(p)) for p in phases]
        i = int(np.argmin(values))
        return float(phases[i]), float(values[i])

    def alignment_score(self, period: float) -> tuple[float, float, float]:
        """Izgaranin bu periyoda ne kadar oturdugunu olcer.

        Yontem: en iyi fazdaki varyansi, YARIM PERIYOT kaydirilmis izgaraninkiyle
        kiyasla. Dogru periyotta hizali hucreler duz renkli, kaydirilmis hucreler ise
        her sinir gecisini kesiyor — oran yuksek cikar. Yanlis periyotta ikisi de
        sinir kesiyor, oran ~1'de kalir.

        Donen: (oran, faz, hizali varyans)."""
        phase, aligned = self.best_phase(period)
        shifted = self.variance(period, (phase + period / 2) % period)
        return shifted / max(aligned, 1e-6), phase, aligned


def _period_seeds(pos: np.ndarray, wt: np.ndarray, size: float,
                  min_period: float) -> list[float]:
    """Sinir konumlarindan aday periyotlar cikarir (kaba, elemeye tabi)."""
    periods = np.arange(min_period, max(min_period + 1.0, size / 8.0), 0.02)
    scores = np.array([_lattice_quality(pos, wt, p)[0] for p in periods])
    if scores.max() <= 0:
        return []
    floor = 0.5 * scores.max()
    return [float(periods[i]) for i in range(1, len(scores) - 1)
            if scores[i] > scores[i - 1] and scores[i] >= scores[i + 1] and scores[i] > floor]


def detect_axis_grid(arr: np.ndarray, axis: int, min_period: float = 3.0,
                     name: str = "", min_ratio: float = 3.0) -> AxisGrid:
    """Eksendeki izgara periyodunu ve fazini tespit eder.

    IKI ASAMALI, cunku tek basina hicbiri yetmiyor:

    1. Sinir konumlarindan aday periyotlar (hizli ama YANILTICI). Bu skor kucuk
       periyotlara sistematik olarak yanli: periyot ne kadar kucukse rastgele bir
       sinir kafese denk gelme sansi o kadar yuksek. Olculen bir ornekte gercek
       periyot 20.48 iken 1/8'i olan 2.56 daha yuksek skor aliyordu.
    2. Her adayi (ve KATLARINI) hucre ici varyansla ele: dogru izgarada hucreler
       duz renklidir. Bolen periyotlar da duz cikar, bu yuzden gecerliler arasindan
       EN BUYUGU secilir. Katlari da denememiz sart, cunku 1. asama bir boleni
       yakalamis olabilir ve gercek periyot aday listesinde hic bulunmayabilir.

    Faz her aday icin ayrica optimize edilir — bazi render'larda izgara tuvali tam
    bolmuyor (olculen bir ornekte periyot 11.06, faz 6.45) ve faz sifir varsayilirsa
    o goruntuler tamamen yanlis cozunuyor."""
    size = arr.shape[1] if axis == 1 else arr.shape[0]
    sig = boundary_signal(arr, axis)
    pos, wt = cluster_boundaries(sig)

    seeds = _period_seeds(pos, wt, size, min_period) if len(pos) >= 3 else []
    candidates: set[float] = set()
    for seed in seeds:
        for multiple in range(1, 17):
            value = seed * multiple
            if min_period <= value <= size / 8.0:
                candidates.add(round(value, 3))
    if not candidates:
        # Sinir sinyali yoksa: "sanat tuvali tam boluyor" varsayimiyla tara
        candidates = {round(size / n, 3) for n in range(8, 257)
                      if min_period <= size / n <= size / 8.0}
    log(f"  {name}: {len(seeds)} tohum -> {len(candidates)} aday periyot")

    av = AxisVariance(arr, axis)
    scored = [(p, *av.alignment_score(p)) for p in sorted(candidates)]
    viable = [s for s in scored if s[1] >= min_ratio]

    if not viable:
        best = max(scored, key=lambda s: s[1]) if scored else None
        detail = f" (en iyi oran {best[1]:.2f}, esik {min_ratio})" if best else ""
        raise ValueError(
            f"{name} ekseninde izgara bulunamadi{detail} — gorsel buyutulmus pixel art "
            "olmayabilir ya da render cok bozuk olabilir.")

    # Bolenler de gecerli cikar, dogru cevap EN BUYUK olan. Ama olcum gurultusu
    # yuzunden dogru periyodun 1-2 komsusu da listeye giriyor; en buyugun %5
    # civarindakiler arasindan en iyi oranliyi aliyoruz.
    largest = max(s[0] for s in viable)
    near = [s for s in viable if s[0] >= largest * 0.95]
    period, ratio, phase, _ = max(near, key=lambda s: s[1])
    log(f"  {name} aday secildi: periyot={period:.3f} faz={phase:.2f} oran={ratio:.1f}")

    period, phase = _refine_grid(av, period, phase)

    # Cogu render'da izgara tuvali TAM bolen (1024 = 100 x 10.24). Sonuc buna cok
    # yakinsa tam bolmeye yasla — son hucrede yuvarlama artigi kalmasin.
    n_exact = int(round(size / period))
    if n_exact > 0:
        exact = size / n_exact
        offset = phase - round(phase / exact) * exact
        if abs(exact - period) < 0.01 * period and abs(offset) < 0.10 * exact:
            log(f"  {name} tam bolmeye yaslandi: {size}/{n_exact} = {exact:.4f}")
            period, phase = exact, 0.0

    count = len(lattice_edges(period, phase, size)) - 1
    if count < 1:
        raise ValueError(f"{name}: gecerli bir izgara kurulamadi (periyot={period}).")

    return AxisGrid(period=period, phase=phase, count=count,
                    quality=float(min(1.0, ratio / 20.0)))


def detect_grid(arr: np.ndarray) -> tuple[AxisGrid, AxisGrid]:
    """Iki ekseni birlikte tespit eder ve birbirleriyle destekler.

    Pixel art hucreleri neredeyse her zaman KAREDIR, yani iki eksenin periyodu ayni
    cikmalidir. Bunu iki yerde kullaniyoruz:
      - Bir eksen tamamen basarisiz olursa digerinin periyodu denenir (sadece faz
        aranir). Aksi halde tek bir zayif eksen tum cikarimi cokertiyordu.
      - Iki eksen birbirine yakin ama esit degilse, daha iyi oturani ikisi icin de
        kullanilir; kucuk olcum farklarinin cozunurlugu kaydirmasi onlenir.
    Belirgin farkli cikarlarsa (kare olmayan hucre) oldugu gibi birakilir."""
    results: dict[int, AxisGrid | None] = {}
    errors: dict[int, str] = {}
    for axis, name in ((1, "X"), (0, "Y")):
        try:
            results[axis] = detect_axis_grid(arr, axis=axis, name=name)
        except ValueError as err:
            results[axis] = None
            errors[axis] = str(err)
            log(f"  {name} basarisiz: {err}")

    if results[1] is None and results[0] is None:
        raise ValueError(errors.get(1) or errors.get(0))

    # Basarisiz ekseni, calisan eksenin periyoduyla kurtar
    for axis, other in ((1, 0), (0, 1)):
        if results[axis] is None:
            src = results[other]
            size = arr.shape[1] if axis == 1 else arr.shape[0]
            av = AxisVariance(arr, axis)
            phase, _ = av.best_phase(src.period, steps=48)
            count = len(lattice_edges(src.period, phase, size)) - 1
            name = "X" if axis == 1 else "Y"
            log(f"  {name}: diger eksenin periyodu ({src.period:.4f}) kullanildi")
            results[axis] = AxisGrid(period=src.period, phase=phase,
                                     count=max(1, count), quality=src.quality * 0.5)

    gx, gy = results[1], results[0]

    # Yakinsa birlestir: daha iyi oturan eksenin periyodu ikisi icin de kullanilir
    spread = abs(gx.period - gy.period) / max(gx.period, gy.period)
    if 0 < spread <= 0.05:
        better, worse_axis = (gx, 0) if gx.quality >= gy.quality else (gy, 1)
        size = arr.shape[1] if worse_axis == 1 else arr.shape[0]
        av = AxisVariance(arr, worse_axis)
        phase, _ = av.best_phase(better.period, steps=48)
        count = len(lattice_edges(better.period, phase, size)) - 1
        unified = AxisGrid(period=better.period, phase=phase, count=max(1, count),
                           quality=better.quality)
        log(f"  eksenler birlestirildi: periyot {better.period:.4f} "
            f"(fark %{spread * 100:.1f})")
        if worse_axis == 1:
            gx = unified
        else:
            gy = unified

    return gx, gy


def _refine_grid(av: AxisVariance, period: float, phase: float,
                 span: float = 0.02, steps: int = 41) -> tuple[float, float]:
    """Periyot ve fazi, hucre ici varyansi en aza indirecek sekilde ince ayarlar.

    Sinir konumlarina en kucuk kareler uydurmak yerine dogrudan varyansi kucultuyoruz:
    olcut fiziksel olarak anlamli (hucreler duz renkli mi) ve zayif/gurultulu sinir
    sinyalinden etkilenmiyor."""
    best = (float("inf"), period, phase)
    for candidate in np.linspace(period * (1 - span), period * (1 + span), steps):
        ph, value = av.best_phase(float(candidate), steps=32)
        if value < best[0]:
            best = (value, float(candidate), ph)
    return best[1], best[2]


# ---------------------------------------------------------------------------
# 2) Native cozunurluge indirme
# ---------------------------------------------------------------------------

def downsample_by_mode(arr: np.ndarray, gx: AxisGrid, gy: AxisGrid,
                       center_ratio: float = 0.5) -> np.ndarray:
    """Her hucrenin MERKEZ bolgesinden baskin (mode) rengi alir.

    Merkezden ornekleme, hucre sinirlarindaki anti-aliasing ara tonlarini disarida
    birakir. Sinirlar ondalikli tutuldugu icin son hucrede de kayma olmaz."""
    xe = gx.edges(arr.shape[1])
    ye = gy.edges(arr.shape[0])
    H, W = arr.shape[:2]
    packed = pack_rgb(arr)

    out = np.zeros((gy.count, gx.count, 3), dtype=np.uint8)
    inset = (1.0 - center_ratio) / 2.0

    x_windows = []
    for j in range(gx.count):
        a, b = xe[j], xe[j + 1]
        x0 = int(np.floor(a + (b - a) * inset))
        x1 = int(np.ceil(b - (b - a) * inset))
        x0 = max(0, min(W - 1, x0))
        x1 = max(x0 + 1, min(W, x1))
        x_windows.append((x0, x1))

    for i in range(gy.count):
        a, b = ye[i], ye[i + 1]
        y0 = int(np.floor(a + (b - a) * inset))
        y1 = int(np.ceil(b - (b - a) * inset))
        y0 = max(0, min(H - 1, y0))
        y1 = max(y0 + 1, min(H, y1))
        row = packed[y0:y1]
        for j, (x0, x1) in enumerate(x_windows):
            window = row[:, x0:x1].ravel()
            values, counts = np.unique(window, return_counts=True)
            out[i, j] = unpack_rgb(int(values[counts.argmax()]))
    return out


# ---------------------------------------------------------------------------
# 3) Dama deseni -> gercek alfa
# ---------------------------------------------------------------------------

def _cluster_counts(packed: np.ndarray, merge_tol: int) -> list[tuple[np.ndarray, int]]:
    """Paketlenmis renkleri frekansa gore kumeler; birbirine `merge_tol` kadar yakin
    renkler tek kumede toplanir ve sayilari birlesir.

    Neden gerekli: AI render'inda ayni dama karesi 203/205/206 gibi bir kac degere
    dagiliyor. Ham frekansa bakinca hicbiri tek basina anlamli bir paya ulasmiyor,
    birlikte bakinca kenarin yarisini kapliyorlar."""
    values, counts = np.unique(packed, return_counts=True)
    clusters: list[tuple[np.ndarray, int]] = []
    for idx in np.argsort(-counts, kind="stable"):
        color = np.array(unpack_rgb(int(values[idx])), dtype=np.int32)
        for pos, (anchor, total) in enumerate(clusters):
            if np.abs(anchor - color).max() <= merge_tol:
                clusters[pos] = (anchor, total + int(counts[idx]))
                break
        else:
            clusters.append((color, int(counts[idx])))
    # Birlesme sonrasi toplamlar degistigi icin yeniden siralaniyor: cagiranlar
    # "en kalabalik kume once" varsayimina dayanip pay esiginde donguyu kiriyor.
    clusters.sort(key=lambda c: -c[1])
    return clusters


def detect_background_tones(small: np.ndarray, ring: int = 2, per_side: int = 3,
                            merge_tol: int = 4, min_share: float = 0.15) -> list[tuple[int, int, int]]:
    """Gorselin kenar seridinden dama deseninin GERCEK tonlarini ogrenir.

    Sabit "acik gri" varsayimi yerine ornekleme yapiyoruz; boylece pembe, mavi, bej
    ya da koyu temali dama desenleri de calisiyor.

    Her kenar AYRI ornekleniyor: bazi render'larda dama tuval boyunca renk kaydiriyor
    (olculen bir ornekte ust kenarda tonlar 229/253 iken alt bolgede 203/243'e
    iniyordu). Tum kenari birlikte sayip en sik birkac rengi almak, azinlikta kalan
    kenarin tonlarini eliyor ve o bolgede arka plan silinmeden kaliyordu.

    Sayim BIREBIR renklere degil, `merge_tol` icinde kumelenmis renklere bakiyor.
    Sebebi olculdu: kanal basina bagimsiz +/-1 gurultu tek bir dama tonunu
    (252,253,253), (252,252,253), (252,252,254)... gibi onlarca ayri renge
    dagitiyor. Birebir sayimda hicbiri %15 paya ulasamiyor ve fonksiyon BOS
    liste donuyordu — yani arka plan hic silinmiyordu."""
    h, w = small.shape[:2]
    sides = (small[:ring, :], small[-ring:, :], small[:, :ring], small[:, -ring:])

    tones: list[tuple[int, int, int]] = []
    for region in sides:
        clusters = _cluster_counts(pack_rgb(region), merge_tol)
        total = max(1, region.shape[0] * region.shape[1])
        for color, count in clusters[:per_side]:
            # Karakter kenara dayaniyorsa onun rengi de bu kenarda gorunur; dama
            # deseni kenarin buyuk kismini kaplamak zorunda oldugu icin kucuk
            # paylari eliyoruz.
            if count / total < min_share:
                break
            renk = tuple(int(v) for v in color)
            if any(max(abs(a - b) for a, b in zip(renk, t)) <= merge_tol for t in tones):
                continue
            tones.append(renk)
    return tones


def dilate(mask: np.ndarray) -> np.ndarray:
    """3x3 (8-yonlu) genisletme."""
    out = mask.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            out |= np.roll(np.roll(mask, dy, axis=0), dx, axis=1)
    out[0, :] |= mask[0, :]
    out[-1, :] |= mask[-1, :]
    return out


def _checker_square(small: np.ndarray, merge_tol: int = 6, default: int = 3) -> int:
    """Dama karesinin native piksel cinsinden kenar uzunlugunu tahmin eder.

    Kenar seridinden kac piksel ornekleyecegimiz buna bagli: seritte ton CIFTININ
    ikisi de gorunmuyorsa o satir icin yerel ton ogrenilemez, eksik kalan ton
    global degerine geri duser ve olculen sapma sisar (bir testte tolerans
    olmasi gereken 3 yerine 9 seciliyordu)."""
    runs: list[int] = []
    for line in (small[0], small[-1], small[:, 0], small[:, -1]):
        step = np.abs(line[1:].astype(np.int32) - line[:-1].astype(np.int32)).max(axis=1)
        edges = np.flatnonzero(step > merge_tol)
        if len(edges) >= 2:
            runs.extend(np.diff(edges).tolist())
    if not runs:
        return default
    return int(np.clip(np.median(runs), 1, max(1, min(small.shape[:2]) // 6)))


class BackgroundToneField:
    """Dama tonlarini SABIT degil, KONUMA BAGLI tutar.

    Neden gerekli: olculen bir Gemini ciktisinda dama deseninin tonu goruntunun
    ortasindaki bir bantta kayiyor — koyu ton 231'den 203'e, acik ton 253'ten
    243'e iniyor, sonra tekrar yukseliyor. Iki tonu global sabit kabul edip
    tolerans vermek o bandi opak birakiyordu; bant karakterin koluna degdigi icin
    "kopuk parca" temizligine de takilmiyor, ekranda ince yatay bir cizgi olarak
    kaliyordu.

    Toleransi buyutmek cozum degil: kayma 24 birime ulasiyor, o kadar genis bir
    esik karakterin acik renkli bolgelerini de yutar. Onun yerine her SATIR ve her
    SUTUN icin kenar seridinden ayri ornek aliyoruz — o satirdaki gercek dama rengi
    zaten o satirin kenarinda duruyor.

    Guvenlik: bir seritten en fazla global ton sayisi kadar yerel ton alinir,
    aday ancak global tonlarin BIRINE `max_drift` kadar yakinsa ve serittte
    `min_share` paya ulasiyorsa kabul edilir. Yani karakter kenara dayadiginda
    rengi tonun yerine gecebilmesi icin hem dama tonuna yakin olmasi hem de o
    seritte dama deseninden daha cok piksel kaplamasi gerekir.

    ONEMLI: adaylar global tonlara TEK TEK eslenmez. Denendi ve yanlisti: kayma
    24 birime ulastiginda kaymis ACIK ton (241), global KOYU tona (231) kaymis
    koyu tondan (207) daha yakin oluyor; ikisi de koyu tona atanip acik ton
    bosta kaliyordu ve o satirda arka planin yarisi opak kaliyordu."""

    def __init__(self, small: np.ndarray, tones: list[tuple[int, int, int]],
                 ring: int | None = None, max_drift: int = 45,
                 min_share: float = 0.08, merge_tol: int = 6):
        h, w = small.shape[:2]
        self.tones = tones
        self.empty = not tones
        if not tones:
            self.distance = np.full((h, w), 255, dtype=np.int32)
            self.drift = 0
            return

        rgb = small.astype(np.int32)
        base = np.array(tones, dtype=np.int32)
        # Serit, dama karesinden genis olmali ki satirda ton ciftinin IKISI de
        # gorunsun; ama gereginden genis olmamali, yoksa kenara yakin duran
        # karakter parcalari da orneklemeye giriyor (olculen bir gorselde serit
        # 12'den 14'e cikinca secilen tolerans 3'ten 9'a firliyordu). Bu yuzden
        # sabit bir genislik yok: yetmedigi SATIRDA genisletiliyor.
        widths = self._ring_widths(small, ring)

        distance = np.min(np.abs(rgb[:, :, None, :] - base[None, None, :, :]).max(axis=3),
                          axis=2)
        self.drift = 0

        for axis in (0, 1):
            if axis == 0:
                stacks = [np.concatenate([small[:, :r], small[:, -r:]], axis=1)
                          for r in widths]
            else:
                stacks = [np.concatenate([small[:r, :], small[-r:, :]], axis=0)
                          .transpose(1, 0, 2) for r in widths]
            local = self._line_tones([pack_rgb(s) for s in stacks], base,
                                     max_drift, min_share, merge_tol)
            for i, palette in enumerate(local):
                if palette is None:
                    continue
                line = rgb[i] if axis == 0 else rgb[:, i]
                d = np.abs(line[:, None, :] - palette[None, :, :]).max(axis=2).min(axis=1)
                target = distance[i] if axis == 0 else distance[:, i]
                np.minimum(target, d, out=target)
                # yerel tonun global tondan ne kadar uzaklastigi — raporlanabilir bir sayi
                gap = np.abs(palette[:, None, :] - base[None, :, :]).max(axis=2).min(axis=1)
                self.drift = max(self.drift, int(gap.max()))

        self.distance = distance

    @staticmethod
    def _ring_widths(small: np.ndarray, ring: int | None) -> list[int]:
        """Denenecek serit genislikleri, dardan genise."""
        cap = max(2, min(small.shape[:2]) // 3)
        start = ring if ring is not None else _checker_square(small) + 2
        widths, r = [], int(np.clip(start, 2, cap))
        while True:
            widths.append(r)
            if r >= cap or len(widths) >= 3:
                return widths
            r = min(cap, r * 2)

    @staticmethod
    def _line_tones(packed_by_width: list[np.ndarray], base: np.ndarray,
                    max_drift: int, min_share: float,
                    merge_tol: int) -> list[np.ndarray | None]:
        """Her satir/sutun icin yerel ton listesi. Global ton sayisini asmaz.

        Serit dar basliyor; o satirda ton ciftinin tamami cikmazsa serit
        genisletilip tekrar deneniyor. Boylece daralmanin bedeli (eksik ton)
        ile genislemenin bedeli (karakterin orneklemeye sizmasi) yalnizca
        gerekli satirlarda odenir."""
        n = packed_by_width[0].shape[0]
        out: list[np.ndarray | None] = []
        for i in range(n):
            best: list[np.ndarray] = []
            for packed in packed_by_width:
                line = packed[i]
                total = max(1, line.size)
                picked: list[np.ndarray] = []
                for color, count in _cluster_counts(line, merge_tol):
                    if len(picked) >= len(base):
                        break                  # dama kac tonluysa o kadar yerel ton
                    if count / total < min_share:
                        break                  # kumeler frekansa gore sirali
                    if np.abs(base - color).max(axis=1).min() > max_drift:
                        continue               # hicbir dama tonuna benzemiyor
                    picked.append(color)
                if len(picked) > len(best):
                    best = picked
                if len(best) >= len(base):
                    break                      # bu genislik yetti
            out.append(np.array(best, dtype=np.int32) if best else None)
        return out


def tone_cluster_edge(distance: np.ndarray, min_width: int = 8,
                      quiet_share: float = 0.0002, limit: int = 200) -> int | None:
    """Arka plan renk kumesinin nerede bittigini bulur.

    Piksellerin ton alanina uzakliklarinin histogramina bakip ilk GENIS BOSLUGU
    arar: altinda kalan her uzaklik degerinde piksel var, ustunde uzun bir sessizlik
    basliyor. Bu bosluk, "arka plan ve karisimlari" ile "karakterin renkleri"
    arasindaki dogal sinirdir.

    Neden gerekli: dama karelerinin sinirindaki karisim pikselleri tonlardan
    epeyce uzak olabiliyor. Olculen bir magenta render'inda tonlar (184,0,184) ve
    (254,1,252) iken sinir pikselleri (210,0,211) civarinda cikti — tonlara 27
    birim uzak. Kenar seridinden olculen tolerans 8'de kaliyor ve arka planin
    buyuk parcalari opak kaliyordu. Histogramda ise 34 ile 76 arasi tamamen bos:
    34 arka planin sonu, 76 karakterin baslangici.

    Sabit bir ust sinir (eskiden 14) bu ayrimi yapamaz, cunku guvenli tolerans
    tamamen dama renginin karakterin paletine ne kadar uzak oldugua baglidir:
    magenta damada 36 rahatca guvenliyken, gri damada 4 bile riskli."""
    h = np.bincount(np.clip(distance.ravel(), 0, limit), minlength=limit + 1)
    esik = max(1, int(quiet_share * distance.size))
    dolu = np.flatnonzero(h > esik)
    if dolu.size < 2:
        return None
    for i in range(len(dolu) - 1):
        if dolu[i + 1] - dolu[i] >= min_width:
            return int(dolu[i])
    return None


def estimate_background_tolerance(field: BackgroundToneField, ring: int = 3,
                                  margin: int = 3, low: int = 3, high: int = 60) -> int:
    """Arka planin kendi ton referansindan ne kadar saptigini OLCUP tolerans secer.

    Sabit bir tolerans ise yaramiyor: olculen render'larda kenar seridinin sapmasi
    (%95'lik dilim) 0 ile 9 arasinda degisiyor. 1024'luk temiz bir ornekten
    turetilen tol=3, 2048'lik gurultulu render'larda arka planin buyuk kismini
    birakiyordu (bir gorselde 5437 opak piksel yerine 3191 olmaliydi).

    Olcum YEREL ton alanina gore yapilir. Global tonlara gore olculdugunde ton
    kaymasi gurultu sanilip tolerans sisiyordu (olculen bir gorselde 11'e cikip
    karakterin acik renklerini riske atiyordu); yerel referansla ayni gorselde 4."""
    if field.empty:
        return low
    h, w = field.distance.shape
    mask = np.zeros((h, w), dtype=bool)
    mask[:ring, :] = mask[-ring:, :] = True
    mask[:, :ring] = mask[:, -ring:] = True
    p95 = float(np.percentile(field.distance[mask], 95))
    olculen = round(p95) + margin

    # Kenar seridi dama sinirlarindaki karisimlari her zaman gormuyor; renk
    # kumesinin gercek sinirini histogram soyluyor. Ikisinin BUYUGU aliniyor:
    # serit olcumu tabani, kume siniri tavani belirliyor.
    kenar = tone_cluster_edge(field.distance)
    if kenar is not None:
        olculen = max(olculen, kenar + 1)
    return int(np.clip(olculen, low, high))


def background_to_alpha(small: np.ndarray, field: BackgroundToneField,
                        tol: int = 3, halo_tol_factor: float = 2.5,
                        halo_width: int = 2) -> np.ndarray:
    """Dama tonlarina yakin VE goruntu kenarina bagli pikselleri seffaf yapar.

    Iki kademeli esik:
      - guclu maske (tol): kesin dama pikselleri. Flood-fill SADECE bunun icinde
        yayilir.
      - zayif maske (tol * halo_tol_factor): konturun damayla karistigi ara tonlar.
        Buraya yayilma `halo_width` piksel ile SINIRLI.

    Yayilmanin sinirli olmasi kritik: onceki surumde flood-fill dogrudan zayif
    maskede kosuyordu ve karakterin dama tonuna yakin (ör. beyaza calan) bolgeleri
    kenara bagliysa ICERI DOGRU yiyordu. Hale bir piksel kalinligindadir, dolayisiyla
    genisletmeyi `halo_width` ile kapatmak haleyi temizler ama karakteri yemez.

    Varsayilanlar olculerek secildi: gercek bir Gemini ciktisinda arka plan
    piksellerinin %98'i dama tonuyla BIREBIR ayni, en buyuk sapma 3. Ayrica hucre
    merkezinden mode ornekledigimiz icin anti-aliasing zaten disarida kaliyor —
    bu yuzden halo_width varsayilani 0. Konturda bulanik bir hale kalirsa 1 yapin.

    BILINEN SINIR: karakterin uzerinde dama tonuna `tol` kadar yakin bir renk varsa
    ve o bolge kenara bagliysa, renk temelli hicbir yontem ikisini ayiramaz. Boyle
    bir durumda --bg-tol degerini dusurun."""
    if field.empty:
        # Kenarlarda baskin bir ton yok — silinecek bir dama deseni de yok demektir.
        return np.dstack([small.astype(np.uint8),
                          np.full(small.shape[:2], 255, dtype=np.uint8)])

    strong = field.distance <= tol
    weak = field.distance <= tol * halo_tol_factor

    border_seed = np.zeros_like(strong)
    border_seed[0, :] = border_seed[-1, :] = True
    border_seed[:, 0] = border_seed[:, -1] = True
    seeds = strong & border_seed
    if not seeds.any():
        # Karakter tuvalin dort kenarina da dayaniyorsa kenar tohumu bulunamaz;
        # o zaman tum guclu maskeyi tohum kabul et.
        seeds = strong

    background = flood_from_seeds(strong, seeds, connectivity=4)

    for _ in range(max(0, halo_width)):
        background = dilate(background) & weak

    alpha = np.where(background, 0, 255).astype(np.uint8)
    return np.dstack([small.astype(np.uint8), alpha])


# ---------------------------------------------------------------------------
# 4) Artefakt temizligi
# ---------------------------------------------------------------------------

def remove_background_remnants(rgba: np.ndarray, field: BackgroundToneField,
                               tol: int, share: float = 0.7) -> np.ndarray:
    """Ana silüetten kopuk VE dama renginde olan parcalari siler.

    Dama sinirina denk gelen bazi hucreler iki tonun arasinda bir renk aliyor ve
    esigin disinda kaliyor; geriye ince seritler kaliyor. Bunlar boyut esigini
    asabildigi icin leke temizleyicisine takilmiyorlar. Boyuta degil RENGE bakarak
    eliyoruz: karakterin gercek parcalari dama tonunda olmaz.

    NOT: bu bir emniyet agi, cozum degil. Kalinti ana silüete DEGIYORSA (olculen
    bir ornekte ton kaymasi karakterin kolunun altinda yatay bir serit birakiyordu)
    burasi onu yakalayamaz — o yuzden asil is `BackgroundToneField` tarafinda.

    Olcut, ONAYLANMIS arka planin renk gamutu: "bu renk, seffaf yapilmis
    piksellerde gecen bir renge yakin mi?" Kayma iki boyutlu olabiliyor (olculen
    bir ornekte satirin solunda tonlar 219/252 iken saginda 204/233'tu) ve
    satir/sutun ornekleme boyle yerel bir golgeyi tam yakalayamiyor; ama o
    golgenin komsulugu zaten silinmis oluyor, dolayisiyla dogru referans
    bastaki iki ton degil, gercekten silinmis piksellerin renkleri.

    Bu gevsek olcut yalnizca KOPUK parcalara uygulandigi icin guvenli — ana
    silüete uygulansa karakterin gri tonlarini yerdi."""
    if field.empty:
        return rgba
    rgba = rgba.copy()
    opaque = rgba[:, :, 3] > 0
    if opaque.all():
        return rgba
    labels, num = label_components(opaque, connectivity=8)
    if num <= 1:
        return rgba

    confirmed = np.array([unpack_rgb(int(v))
                          for v in np.unique(pack_rgb(rgba[:, :, :3][~opaque]))],
                         dtype=np.int32)
    sizes = np.bincount(labels.ravel())
    main = int(np.argmax(sizes[1:])) + 1
    wide = tol * 3
    for lbl in range(1, num + 1):
        if lbl == main:
            continue
        mask = labels == lbl
        colors = rgba[:, :, :3][mask].astype(np.int32)
        near = np.abs(colors[:, None, :] - confirmed[None, :, :]).max(axis=2).min(axis=1)
        if (near <= wide).mean() >= share:
            rgba[mask] = (0, 0, 0, 0)
    return rgba


def remove_detached_specks(rgba: np.ndarray, max_size: int = 12) -> np.ndarray:
    """Ana silüetten KOPUK kucuk opak parcalari siler."""
    rgba = rgba.copy()
    opaque = rgba[:, :, 3] > 0
    labels, num = label_components(opaque, connectivity=8)
    if num <= 1:
        return rgba
    sizes = np.bincount(labels.ravel())
    main = int(np.argmax(sizes[1:])) + 1
    for lbl in range(1, num + 1):
        if lbl != main and sizes[lbl] <= max_size:
            rgba[labels == lbl] = (0, 0, 0, 0)
    return rgba


def fill_interior_holes(rgba: np.ndarray, max_size: int = 12) -> np.ndarray:
    """Karakterin icinde yanlislikla seffaf kalmis kucuk delikleri KENDI orijinal
    rengiyle geri acar. 4-yonlu baglanti kullanilir: capraz bir noktadan disa
    'sizan' bosluklar aksi halde kenara bagli sayilip doldurulmadan kaliyordu.

    Onceki surum komsu renklerin ORTALAMASINI yaziyordu; bu, script'in "hicbir
    rengi uydurmam" sozunu bozuyordu — olculen bir ornekte beyaz (255,255,255)
    bir ayakkabi pikseli (115,115,117) ile boyaniyordu, ki bu renk kaynakta
    hicbir yerde yok. Seffaf piksellerin RGB'si zaten kaynaktaki degeri
    tasiyor, dolayisiyla dogru doldurma sadece alfayi geri acmaktir."""
    rgba = rgba.copy()
    transparent = rgba[:, :, 3] == 0
    labels, num = label_components(transparent, connectivity=4)
    if num == 0:
        return rgba

    border = set(labels[0, :].tolist()) | set(labels[-1, :].tolist()) \
        | set(labels[:, 0].tolist()) | set(labels[:, -1].tolist())
    border.discard(0)

    sizes = np.bincount(labels.ravel())
    for lbl in range(1, num + 1):
        if lbl in border or sizes[lbl] > max_size:
            continue
        rgba[labels == lbl, 3] = 255
    return rgba


def open_enclosed_gaps(rgba: np.ndarray, field: BackgroundToneField, tol: int,
                       max_size: int) -> tuple[np.ndarray, list[tuple[int, int, int, int]]]:
    """Silüetin ICINDE kapali kalmis, dama renginde kucuk adaciklari seffaf yapar.

    Neden gerekli: AI bazen kolla govde arasinda 1-3 piksellik bir bosluk
    birakiyor. Bosluk dama renginde ama kontur tarafindan tamamen cevrelendigi
    icin kenardan gelen flood-fill oraya ulasamiyor; sonucta ekranda gri bir
    leke olarak kaliyor. Bosluk dama karesinden kucuk oldugu icin icinde desen
    de gorunmuyor, sadece tek bir ton var.

    NEDEN VARSAYILAN OLARAK KAPALI: bu adim guvenli bir sekilde OTOMATIKLESTIRILEMIYOR.
    Olculen karakterlerde goz akiligi (254-255) ile damanin acik tonu (253)
    ayni renk, ve ikisi de silüetin icinde kapali birer adacik. Ayirt etmek icin
    denenen olcutler ve neden yetersiz kaldiklari:
      - dama kafesinin geometrisi: dama, native piksel izgarasina oturmuyor
        (olculen uyum %52, sansa esit) — kaynak cozunurlukte cizildigi icin
        periyodu hucre boyutunun tam kati degil.
      - adacik boyutu: olculen bir gorselde gercek bosluk 4 piksel, goz akinin
        bir parcasi da 4 piksel.
      - komsularin koyulugu: bosluklarin bir kismi tene komsu, konturla
        cevrelenmis degil.
    Bu yuzden secim kullaniciya birakiliyor: --fill-gaps N ile boyut siniri
    verilir, silinen her adacik raporlanir, --preview ile gozle dogrulanir."""
    silinen: list[tuple[int, int, int, int]] = []
    if max_size <= 0 or field.empty:
        return rgba, silinen

    rgba = rgba.copy()
    opaque = rgba[:, :, 3] > 0
    aday = opaque & (field.distance <= tol)
    labels, num = label_components(aday, connectivity=4)
    for lbl in range(1, num + 1):
        mask = labels == lbl
        size = int(mask.sum())
        if size > max_size:
            continue

        # Adacik KENDI renginde bir komsuya sahipse ona dokunmuyoruz: o zaman
        # daha buyuk bir acik renkli parcanin ucudur (olculen ornekte ayakkabinin
        # beyaz tabani), gercek bir bosluk degil. Gercek bosluklar renk olarak
        # yalitiktir — cevrelerinde yalnizca kontur ya da ten vardir.
        cevre = dilate(mask) & ~mask & opaque
        if cevre.any():
            ic = rgba[:, :, :3][mask].astype(np.int32)
            dis = rgba[:, :, :3][cevre].astype(np.int32)
            if (np.abs(dis[:, None, :] - ic[None, :, :]).max(axis=2).min() <= 2 * tol):
                continue

        ys, xs = np.where(mask)
        silinen.append((int(ys.min()), int(xs.min()), size,
                        int(rgba[ys[0], xs[0], :3].mean())))
        rgba[mask] = (0, 0, 0, 0)
    return rgba, silinen


def remove_isolated_singletons(rgba: np.ndarray, color_tol: int = 12) -> np.ndarray:
    """Hicbir opak komsusuyla ayni renkte olmayan tek piksellik yabanci noktalari
    temizler. Silueti tasan cikintilar silinir, ic azinlik renkler baskin komsu
    rengiyle degistirilir. Gercek kontur cizgileri en az bir ayni renkli komsuya
    sahip oldugu icin etkilenmez."""
    rgba = rgba.copy()
    h, w = rgba.shape[:2]
    alpha = rgba[:, :, 3]
    offsets = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))

    ys, xs = np.where(alpha > 0)
    for y, x in zip(ys, xs):
        neighbor_colors = []
        for dy, dx in offsets:
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and alpha[ny, nx] > 0:
                neighbor_colors.append(tuple(int(v) for v in rgba[ny, nx, :3]))
        if not neighbor_colors:
            continue

        this = rgba[y, x, :3].astype(int)
        if any(np.abs(this - np.array(nc)).max() <= color_tol for nc in neighbor_colors):
            continue

        if len(neighbor_colors) <= 3:
            rgba[y, x] = (0, 0, 0, 0)
        else:
            values, counts = np.unique(np.array(neighbor_colors), axis=0, return_counts=True)
            rgba[y, x] = (*values[counts.argmax()], 255)
    return rgba


def merge_near_colors(rgba: np.ndarray, tol: int) -> np.ndarray:
    """Birbirine cok yakin renkleri en sik gorulen komsusuna yaslar.

    AI render'lari duz olmasi gereken bolgelerde bile piksel basina hafif renk
    oynamasi uretiyor (bu gorselde 2299 opak piksele karsi 664 farkli renk).
    Renkler frekansa gore siralanip, her renk toleransa giren ILK baskin renge
    atanir — boylece hakim tonlar korunur, sadece gurultu onlara yaslanir.

    Varsayilan olarak KAPALI: kasitli ince golgelendirmeyi de duzleyebilir."""
    rgba = rgba.copy()
    opaque = rgba[:, :, 3] > 0
    if not opaque.any():
        return rgba

    packed = pack_rgb(rgba[:, :, :3])
    values, counts = np.unique(packed[opaque], return_counts=True)
    # kararli siralama: esit frekansta hep ayni renk cipa secilsin (tekrarlanabilirlik)
    order = np.argsort(-counts, kind="stable")

    anchors: list[np.ndarray] = []
    mapping: dict[int, tuple[int, int, int]] = {}
    for idx in order:
        color = np.array(unpack_rgb(int(values[idx])), dtype=np.int32)
        for anchor in anchors:
            if np.abs(color - anchor).max() <= tol:
                mapping[int(values[idx])] = tuple(int(v) for v in anchor)
                break
        else:
            anchors.append(color)
            mapping[int(values[idx])] = tuple(int(v) for v in color)

    ys, xs = np.where(opaque)
    for y, x in zip(ys, xs):
        rgba[y, x, :3] = mapping[int(packed[y, x])]
    log(f"  palet birlestirme (tol={tol}): {len(values)} -> {len(anchors)} renk")
    return rgba


def crop_to_content(rgba: np.ndarray, padding: int = 0) -> np.ndarray:
    """Seffaf kenar bosluklarini kirpar."""
    alpha = rgba[:, :, 3]
    rows = np.where((alpha > 0).any(axis=1))[0]
    cols = np.where((alpha > 0).any(axis=0))[0]
    if len(rows) == 0 or len(cols) == 0:
        return rgba
    y0 = max(0, rows.min() - padding)
    y1 = min(rgba.shape[0], rows.max() + 1 + padding)
    x0 = max(0, cols.min() - padding)
    x1 = min(rgba.shape[1], cols.max() + 1 + padding)
    return rgba[y0:y1, x0:x1]


# ---------------------------------------------------------------------------
# Hata ayiklama ciktilari
# ---------------------------------------------------------------------------

def cell_cores(arr: np.ndarray, gx: AxisGrid, gy: AxisGrid, center_ratio: float = 0.5):
    """Her hucrenin AA sinirlarindan uzak cekirdek bolgesini dolasir.

    Pencere ORANSAL (hucrenin ortadaki `center_ratio` kadari) — ornekleyicinin
    kullandigi pencereyle ayni. Sabit piksel payi kullanmak buyuk hucrelerde
    (2048'lik render'larda hucre 20px) kenar yumusamasini olcume karistirip
    "detay kaybi" sayisini yapay olarak iki katina cikariyordu.

    Donen: (i, j, core) — core: (N,3) int32."""
    xe, ye = gx.edges(arr.shape[1]), gy.edges(arr.shape[0])
    inset = (1.0 - center_ratio) / 2.0
    for i in range(gy.count):
        pad = (ye[i + 1] - ye[i]) * inset
        y0, y1 = int(np.ceil(ye[i] + pad)), int(np.floor(ye[i + 1] - pad))
        if y1 <= y0:
            continue
        for j in range(gx.count):
            xpad = (xe[j + 1] - xe[j]) * inset
            x0, x1 = int(np.ceil(xe[j] + xpad)), int(np.floor(xe[j + 1] - xpad))
            if x1 <= x0:
                continue
            yield i, j, arr[y0:y1, x0:x1].reshape(-1, 3).astype(np.int32)


def intra_cell_variance(arr: np.ndarray, gx: AxisGrid, gy: AxisGrid) -> float:
    """Hucre ici renk varyansinin agirlikli ortalamasi.

    Izgara dogruysa her hucre tek bir renktir ve bu deger kaynak gurultusu
    seviyesinde kalir. Izgara kaydiysa hucreler sinir asar ve deger patlar —
    olculen: dogru izgarada ~12, blok boyutu tam sayiya yuvarlandiginda ~739."""
    total, count = 0.0, 0
    for _, _, core in cell_cores(arr, gx, gy):
        total += float(core.var(axis=0).sum()) * len(core)
        count += len(core)
    return total / max(1, count)


def verify_extraction(arr: np.ndarray, gx: AxisGrid, gy: AxisGrid,
                      small: np.ndarray, opaque: np.ndarray,
                      color_tol: int = 6, conflict_tol: int = 25) -> dict:
    """Cikarimin kayipsizligini OLCER — iddia degil, rapor.

    Uc soruya cevap verir:
      1. Izgara dogru mu?  -> hucre ici varyans, tam sayi izgarayla kiyaslamali
      2. Her hucreye tek bir renk atanabiliyor mu?  -> secilen rengin cekirdegi
         temsil orani
      3. Bir hucrede GERCEKTEN iki farkli renk carpisiyor mu? -> gerçek detay
         kaybinin tek olasi kaynagi. Arka plan hucreleri disarida birakilir."""
    represent, conflicts = [], []

    for i, j, core in cell_cores(arr, gx, gy):
        chosen = small[i, j].astype(np.int32)
        represent.append(float((np.abs(core - chosen).max(axis=1) <= color_tol).mean()))
        if not opaque[i, j]:
            continue  # arka plandaki dama sinirlari hucre asar, onemsiz

        far = core[np.abs(core - chosen).max(axis=1) > conflict_tol]
        if len(far) >= 0.25 * len(core):
            values, counts = np.unique(pack_rgb(far), return_counts=True)
            rival = unpack_rgb(int(values[counts.argmax()]))
            conflicts.append((i, j, tuple(int(v) for v in chosen), rival,
                              len(far) / len(core)))

    represent = np.array(represent)
    rounded = AxisGrid(period=round(gx.period), phase=0.0,
                       count=int(arr.shape[1] // round(gx.period)), quality=0.0)
    return {
        "variance": intra_cell_variance(arr, gx, gy),
        "variance_if_rounded": intra_cell_variance(arr, rounded, rounded),
        "mean_representation": float(represent.mean()),
        "cells_clean": float((represent >= 0.90).mean()),
        "conflicts": conflicts,
        "character_cells": int(opaque.sum()),
    }


def measure_noise_floor(rgba: np.ndarray) -> dict:
    """Kaynagin rastgele renk gurultusunun buyuklugunu olcer ve buna dayali,
    guvenli bir palet birlestirme toleransi onerir.

    Olcum yalnizca YEREL OLARAK DUZ bolgelerde yapilir (3x3 komsulugundaki renk
    yayilimi kucuk olan hucreler): orada olmasi gereken tek bir renktir, sapma ne
    varsa gurultudur. Kenarlarin ve golge basamaklarinin buyuklugu bilincli olarak
    olculmuyor — duz bir tonal basamakta yerel medyan basamagi aynen urettigi icin
    o olcum yaniltici cikiyordu, arkasinda duramayacagimiz bir sayiyi raporlamak
    yerine hic raporlamiyoruz.

    Onerilen tolerans = olculen gurultu tavaninin (95. yuzdelik) iki kati. Bu
    YAPISI GEREGI guvenli: gurultu mesafesinin iki katindan uzak hicbir rengi
    birlestirmedigi icin kasitli tonal adimlara (olculen ornekte 20+ birim)
    dokunamaz."""
    alpha = rgba[:, :, 3] > 0
    A = rgba[:, :, :3].astype(np.float32)

    shifts = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
    stacks = [np.stack([np.roll(np.roll(A[:, :, c], dy, 0), dx, 1)
                        for dy, dx in shifts]) for c in range(3)]
    median = np.stack([np.median(s, axis=0) for s in stacks], axis=-1)
    spread = np.max([s.max(0) - s.min(0) for s in stacks], axis=0)
    inner = np.stack([np.roll(np.roll(alpha, dy, 0), dx, 1) for dy, dx in shifts]).all(0)

    deviation = np.abs(A - median).max(axis=2)
    flat = alpha & inner & (spread <= 25)

    if flat.sum() < 20:
        return {"reliable": False, "flat_cells": int(flat.sum()),
                "palette": int(len(np.unique(pack_rgb(rgba[:, :, :3][alpha]))))}

    p95 = float(np.percentile(deviation[flat], 95))
    return {
        "reliable": True,
        "flat_cells": int(flat.sum()),
        "jitter": float(deviation[flat].mean()),
        "jitter_p95": p95,
        "palette": int(len(np.unique(pack_rgb(rgba[:, :, :3][alpha])))),
        "recommended_merge_tol": int(np.clip(round(p95 * 2), 2, 12)),
    }


def print_noise_floor(noise: dict, rgba: np.ndarray):
    print(f"4) Kaynak gurultusu: palet {noise['palette']} renk")
    if not noise["reliable"]:
        print(f"   duz bolge az ({noise['flat_cells']} hucre) — gurultu olcumu "
              "guvenilir degil, palet birlestirmeyi gozle kontrol edin")
        return

    tol = noise["recommended_merge_tol"]
    print(f"   duz bolgelerde sapma: ort {noise['jitter']:.2f}, "
          f"%95'i <= {noise['jitter_p95']:.1f}  ({noise['flat_cells']} hucre uzerinden)")

    merged = merge_near_colors(rgba.copy(), tol)
    alpha = rgba[:, :, 3] > 0
    shift = np.abs(merged[:, :, :3].astype(int) - rgba[:, :, :3].astype(int)).max(axis=2)[alpha]
    after = int(len(np.unique(pack_rgb(merged[:, :, :3][alpha]))))
    print(f"   -> --merge-colors {tol} kullanilsaydi: palet {noise['palette']} -> {after}, "
          f"piksellerin %{(shift == 0).mean() * 100:.0f}'i hic degismezdi, "
          f"en buyuk kayma {int(shift.max())}/255")


def print_verification(report: dict):
    print("\n--- DOGRULAMA ---")
    print(f"1) Izgara:  hucre ici varyans = {report['variance']:.1f}"
          f"   (blok tam sayiya yuvarlansaydi: {report['variance_if_rounded']:.1f})")
    if report["variance_if_rounded"] > report["variance"] * 3:
        print("   -> ondalikli izgara belirgin sekilde daha iyi oturuyor")

    print(f"2) Atama:   secilen renk hucre cekirdeginin ortalama "
          f"%{report['mean_representation'] * 100:.1f}'ini temsil ediyor; "
          f"hucrelerin %{report['cells_clean'] * 100:.1f}'i >=%90 tek renk")

    n = len(report["conflicts"])
    total = report["character_cells"]
    print(f"3) Detay kaybi: karakterin {total} hucresinden {n} tanesinde gercekten "
          f"farkli iki renk carpisiyor")
    if n == 0:
        print("   -> hicbir hucrede detay kaybi yok; cikarim kaynagin izin verdigi "
              "olcude birebir")
    else:
        print("   -> asagidaki hucrelerde kaynagin kendisi izgaraya uymuyor "
              "(AI'nin hucre icine tasan cizimi):")
        for i, j, chosen, rival, share in report["conflicts"][:8]:
            print(f"      ({i},{j}) {chosen} vs {rival} (%{share * 100:.0f})")
        if n > 8:
            print(f"      ... ve {n - 8} tane daha")


def dump_grid_overlay(arr: np.ndarray, gx: AxisGrid, gy: AxisGrid, path: str):
    """Tespit edilen izgarayi orijinal gorselin uzerine cizer — gozle dogrulamanin
    en hizli yolu, cizgiler blok kenarlarina oturmuyorsa tespit yanlistir."""
    overlay = arr.copy()
    for x in gx.edges(arr.shape[1]):
        xi = int(round(x))
        if 0 <= xi < overlay.shape[1]:
            overlay[:, xi] = (255, 0, 0)
    for y in gy.edges(arr.shape[0]):
        yi = int(round(y))
        if 0 <= yi < overlay.shape[0]:
            overlay[yi, :] = (0, 128, 255)
    Image.fromarray(overlay).save(path)
    log(f"  hata ayiklama: izgara katmani -> {path}")


# ---------------------------------------------------------------------------
# Ana akis
# ---------------------------------------------------------------------------

def load_image(path: str) -> tuple[np.ndarray, np.ndarray | None]:
    """RGB diziyi ve (varsa) gercek alfa kanalini dondurur."""
    img = Image.open(path)
    real_alpha = None
    if img.mode in ("RGBA", "LA") or "transparency" in img.info:
        rgba = np.array(img.convert("RGBA"))
        if (rgba[:, :, 3] < 255).any():
            real_alpha = rgba[:, :, 3]
        return rgba[:, :, :3], real_alpha
    return np.array(img.convert("RGB")), None


def extract(input_path: str, output_path: str, preview_path: str | None = None,
            preview_scale: int = 8, bg_tol: int | None = None, speck_size: int = 12,
            center_ratio: float = 0.5, debug_dir: str | None = None,
            no_crop: bool = False, merge_colors: int = 0,
            cleanup: bool = True, verify: bool = False,
            fill_gaps: int = 0) -> Image.Image:
    arr, real_alpha = load_image(input_path)
    H, W = arr.shape[:2]
    print(f"Girdi: {input_path} ({W}x{H})")
    if real_alpha is not None:
        log("  not: dosyada gercek alfa kanali var, dama tespiti yerine o kullanilacak")

    upscaled = not looks_already_native(arr)

    # 1) izgara
    if not upscaled:
        print("Gorsel zaten native cozunurlukte gorunuyor — izgara indirgeme atlaniyor.")
        gx = AxisGrid(period=1.0, phase=0.0, count=W, quality=1.0)
        gy = AxisGrid(period=1.0, phase=0.0, count=H, quality=1.0)
        small = arr.copy()
    else:
        log("Izgara tespiti:")
        gx, gy = detect_grid(arr)
        print(f"Izgara: periyot X={gx.period:.4f}px  Y={gy.period:.4f}px   "
              f"faz X={gx.phase:.2f}  Y={gy.phase:.2f}")
        print(f"NATIVE cozunurluk: {gx.count}x{gy.count}  "
              f"(uyum X={gx.quality:.0%} Y={gy.quality:.0%})")

        if min(gx.quality, gy.quality) < 0.3:
            print("UYARI: izgara uyumu dusuk — sonucu --debug-dir ile gozle dogrulayin.",
                  file=sys.stderr)

        if debug_dir:
            os.makedirs(debug_dir, exist_ok=True)
            dump_grid_overlay(arr, gx, gy, os.path.join(debug_dir, "1_izgara.png"))

        # 2) native cozunurluge in
        small = downsample_by_mode(arr, gx, gy, center_ratio=center_ratio)

    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        Image.fromarray(small).resize(
            (small.shape[1] * 8, small.shape[0] * 8), Image.NEAREST
        ).save(os.path.join(debug_dir, "2_native.png"))

    # 3) arka plan -> alfa
    field = None
    tol = bg_tol or 0
    if real_alpha is not None:
        alpha_small = downsample_by_mode(
            np.dstack([real_alpha] * 3), gx, gy, center_ratio=center_ratio
        )[:, :, 0]
        rgba = np.dstack([small, np.where(alpha_small > 127, 255, 0).astype(np.uint8)])
    else:
        tones = detect_background_tones(small)
        field: BackgroundToneField | None = BackgroundToneField(small, tones)
        tol = bg_tol if bg_tol is not None else estimate_background_tolerance(field)
        if not tones:
            print("UYARI: kenar seridinde baskin bir dama tonu bulunamadi — arka plan "
                  "SILINMEDEN birakiliyor. Gorselin arka plani gercekten duz/desensiz "
                  "degilse bu bir tespit hatasidir; --debug-dir ile 2_native.png'ye bakin.",
                  file=sys.stderr)
        print("Dama tonlari:", ", ".join(f"#{r:02x}{g:02x}{b:02x}" for r, g, b in tones),
              f"(tolerans {tol}{'' if bg_tol is not None else ', olculerek secildi'})")
        if field.drift > tol:
            log(f"  ton kaymasi: goruntu boyunca en fazla {field.drift} birim — "
                f"satir/sutun basina yerel ton kullaniliyor")
        rgba = background_to_alpha(small, field, tol=tol)
        rgba = remove_background_remnants(rgba, field, tol)

    if verify:
        if upscaled:
            print_verification(verify_extraction(arr, gx, gy, small, rgba[:, :, 3] > 0))
        else:
            print("\n--- DOGRULAMA ---\nGorsel zaten native; indirgeme yapilmadigi icin "
                  "kayip da soz konusu degil.")
        print_noise_floor(measure_noise_floor(rgba), rgba)

    opaque_before = int((rgba[:, :, 3] > 0).sum())
    if debug_dir:
        Image.fromarray(rgba).resize(
            (rgba.shape[1] * 8, rgba.shape[0] * 8), Image.NEAREST
        ).save(os.path.join(debug_dir, "3_alfa.png"))

    # 4) temizlik — kirpma ONCESI, cunku uzakta kalan tek bir leke kirpma sinirini
    #    gereksiz genisletip karakteri tuvalde kaydiriyor
    if cleanup:
        rgba = remove_detached_specks(rgba, max_size=speck_size)
        rgba = fill_interior_holes(rgba, max_size=speck_size)

    # 4b) kapali bosluklar. Sirasi kritik: delik doldurmadan SONRA (yoksa hemen
    #     geri kapatilirlar) ama tek-piksel duzeltmesinden ONCE (o adim renkleri
    #     komsuya yasliyor ve adacigin dama rengi oldugu bilgisi kayboluyor).
    if fill_gaps > 0 and field is None:
        print("--fill-gaps yoksayildi: dosyada gercek alfa kanali var, "
              "dama tespiti calismadi.", file=sys.stderr)
    elif fill_gaps > 0:
        rgba, acilan = open_enclosed_gaps(rgba, field, tol, fill_gaps)
        if acilan:
            print(f"Kapali bosluk acildi ({len(acilan)} adet) — gozle dogrulayin:")
            for y, x, size, ton in acilan:
                print(f"  y={y} x={x}  {size} piksel  parlaklik {ton}")
        else:
            print(f"Kapali bosluk bulunamadi (--fill-gaps {fill_gaps}).")

    if cleanup:
        rgba = remove_isolated_singletons(rgba)
        log(f"  temizlik: {opaque_before} -> {int((rgba[:, :, 3] > 0).sum())} opak piksel")

    if merge_colors > 0:
        rgba = merge_near_colors(rgba, merge_colors)

    # 5) kirp
    if not no_crop:
        before = rgba.shape[:2]
        rgba = crop_to_content(rgba)
        log(f"  kirpma: {before[1]}x{before[0]} -> {rgba.shape[1]}x{rgba.shape[0]}")

    palette = len(np.unique(pack_rgb(rgba[:, :, :3][rgba[:, :, 3] > 0])))
    out = Image.fromarray(rgba)
    out.save(output_path)
    print(f"Kaydedildi: {output_path} ({out.width}x{out.height}, {palette} renk) "
          f"— native cozunurluk, hicbir olcekleme uygulanmadi")

    if preview_path:
        out.resize((out.width * preview_scale, out.height * preview_scale),
                   Image.NEAREST).save(preview_path)
        print(f"Onizleme (sadece gorsel buyutme): {preview_path}")

    return out


def main(argv=None):
    global VERBOSE
    parser = argparse.ArgumentParser(
        description="AI'nin urettigi buyutulmus pixel art'i native cozunurluge indirir.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", help="Girdi PNG")
    parser.add_argument("output", help="Cikti PNG (native cozunurluk, gercek alfa)")
    parser.add_argument("--preview", help="Buyutulmus onizleme PNG (sadece gozle kontrol icin)")
    parser.add_argument("--preview-scale", type=int, default=8, help="Onizleme buyutme orani (varsayilan 8)")
    parser.add_argument("--bg-tol", type=int, default=None,
                        help="Dama rengi eslesme toleransi. Varsayilan: goruntunun kenar "
                             "seridinden OLCULEREK secilir. Arka planin bir kismi kaldiysa "
                             "artirin; karakterin acik renkleri yeniyorsa azaltin.")
    parser.add_argument("--speck-size", type=int, default=12,
                        help="Bu boyuta kadar olan kopuk lekeler/delikler temizlenir (varsayilan 12)")
    parser.add_argument("--center-ratio", type=float, default=0.5,
                        help="Her hucrenin ortadan kacta kaci ornekleniyor (varsayilan 0.5)")
    parser.add_argument("--merge-colors", type=int, default=0, metavar="TOL",
                        help="Bu mesafeden yakin renkleri baskin tona yaslar (ör. 8). "
                             "AI render'larindaki piksel gurultusunu temizler; varsayilan 0 = kapali.")
    parser.add_argument("--no-crop", action="store_true", help="Kenar bosluklarini kirpma")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Leke/delik/tek-piksel temizligini atlar — ham cikarim. "
                             "Temizlik gercek bir detayi yediginde bunu kullanin.")
    parser.add_argument("--fill-gaps", type=int, default=0, metavar="N",
                        help="Silüetin icinde kapali kalmis, dama renginde, en fazla N "
                             "piksellik adaciklari seffaf yapar (ör. 4). Varsayilan 0 = kapali. "
                             "GUVENLI DEGIL: goz akligi damanin acik tonuyla ayni renk "
                             "olabiliyor. Silinen her adacik raporlanir; --preview ile "
                             "gozle dogrulayin.")
    parser.add_argument("--debug-dir", help="Ara adimlari bu klasore yazar (izgara katmani dahil)")
    parser.add_argument("--verify", action="store_true",
                        help="Cikarimin kayipsizligini olcup raporlar: izgara oturmasi, "
                             "hucre basina renk kesinligi ve gercek detay kaybi sayisi.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Ayrintili tani ciktisi")
    args = parser.parse_args(argv)

    VERBOSE = args.verbose
    try:
        extract(args.input, args.output, args.preview, args.preview_scale,
                bg_tol=args.bg_tol, speck_size=args.speck_size,
                center_ratio=args.center_ratio, debug_dir=args.debug_dir,
                no_crop=args.no_crop, merge_colors=args.merge_colors,
                cleanup=not args.no_cleanup, verify=args.verify,
                fill_gaps=args.fill_gaps)
    except (ValueError, FileNotFoundError) as err:
        print(f"HATA: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
