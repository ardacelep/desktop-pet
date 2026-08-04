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
    2. Her hucrenin merkezinden baskin rengi ornekleyerek native cozunurluge iner.
    3. Dama desenini gercek alfa seffafligina cevirir.
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

@dataclass
class AxisGrid:
    period: float   # bir pixel-art hucresinin kac gercek piksel oldugu (ondalikli!)
    phase: float    # ilk izgara cizgisinin konumu (0 olmak zorunda degil)
    count: int      # eksende kac hucre var
    quality: float  # 0..1, sinirlarin izgaraya oturma orani

    def edges(self, size: int) -> np.ndarray:
        """Hucre sinirlarini dondurur: count+1 adet ondalikli konum."""
        start = self.phase - np.floor((self.phase + 1e-9) / self.period) * self.period
        return start + np.arange(self.count + 1) * self.period


def quiet_line_ratios(arr: np.ndarray, noise_tol: float = 1.0) -> tuple[float, float]:
    """Komsu sutun/satir ciftlerinin ne kadarinin birbirinin "ayni" oldugunu olcer.

    TAM esitlik yerine kucuk bir tolerans kullaniliyor: AI render'lari duz bir blok
    icinde bile piksel basina hafif oynama uretiyor, gercek bir Gemini ciktisinda
    birebir ayni komsu sutun orani %0 cikiyor."""
    dc = np.abs(np.diff(arr.astype(np.float32), axis=1)).mean(axis=(0, 2))
    dr = np.abs(np.diff(arr.astype(np.float32), axis=0)).mean(axis=(1, 2))
    return float((dc < noise_tol).mean()), float((dr < noise_tol).mean())


def looks_already_native(arr: np.ndarray, max_quiet_ratio: float = 0.5) -> bool:
    """Gorsel zaten native cozunurlukte mi? Bu on kontrol olmadan, zaten native bir
    dosya verildiginde izgara tespiti anlamsiz bir periyot uydurabiliyor.

    Olcut IKI eksenin de sessiz olmasi: buyutulmus bir pixel art'ta hem sutunlarin
    hem satirlarin cogu komsusuyla ayni (olculen: %81 / %95). Native bir gorselde
    en az bir eksen yogundur — kenar boslugu yuzunden sutunlarin %60'i sessiz olsa
    bile satirlar %9'da kalir. Bu yuzden max degil MIN'e bakiyoruz."""
    quiet_cols, quiet_rows = quiet_line_ratios(arr)
    return min(quiet_cols, quiet_rows) < max_quiet_ratio


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


def detect_axis_grid(arr: np.ndarray, axis: int, min_period: float = 2.0,
                     name: str = "") -> AxisGrid:
    size = arr.shape[1] if axis == 1 else arr.shape[0]
    sig = boundary_signal(arr, axis)
    pos, wt = cluster_boundaries(sig)
    if len(pos) < 3:
        raise ValueError(f"{name}: yeterli izgara siniri bulunamadi — gorsel pixel art olmayabilir.")

    # Periyot taramasi. DIKKAT: gercek periyodun BOLENLERI de mukemmel skor verir
    # (p'ye oturan her sinir p/2'ye de oturur), bu yuzden yuksek skorlu EN BUYUK
    # periyodu seciyoruz. Tam kati olan periyotlar (2p) skoru dusurur.
    max_period = max(min_period + 1.0, size / 8.0)
    periods = np.arange(min_period, max_period, 0.01)
    scores = np.array([_lattice_quality(pos, wt, p)[0] for p in periods])

    threshold = max(0.90 * scores.max(), 0.60)
    good = np.where(scores >= threshold)[0]
    coarse_period = float(periods[good[-1]])
    _, coarse_phase = _lattice_quality(pos, wt, coarse_period)
    log(f"  {name} kaba tarama: periyot={coarse_period:.3f} (skor {scores[good[-1]]:.3f}, "
        f"maks {scores.max():.3f})")

    period, phase, inlier_ratio = _refine_lsq(pos, wt, coarse_period, coarse_phase)

    # Cogu render'da izgara tuvali TAM bolen (1024 = 100 x 10.24). LSQ sonucu buna
    # cok yakinsa tam bolmeye yasla — boylece son hucrede yuvarlama artigi kalmaz.
    n_exact = int(round(size / period))
    if n_exact > 0:
        exact_period = size / n_exact
        phase_snapped = phase - round(phase / exact_period) * exact_period
        if abs(exact_period - period) < 0.02 * period and abs(phase_snapped) < 0.15 * exact_period:
            log(f"  {name} tam bolmeye yaslandi: {size}/{n_exact} = {exact_period:.4f} "
                f"(LSQ {period:.4f}, faz {phase:.3f})")
            period, phase = exact_period, 0.0

    start = phase - np.floor((phase + 1e-9) / period) * period
    count = int(np.floor((size - start) / period + 1e-6))
    if count < 1:
        raise ValueError(f"{name}: gecerli bir izgara kurulamadi (periyot={period}).")

    return AxisGrid(period=period, phase=phase, count=count, quality=inlier_ratio)


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

def detect_background_tones(small: np.ndarray, ring: int = 2, coverage: float = 0.90,
                            max_tones: int = 4) -> list[tuple[int, int, int]]:
    """Gorselin kenar seridinden dama deseninin GERCEK tonlarini ogrenir.

    Sabit "acik gri" varsayimi yerine ornekleme yapiyoruz; boylece pembe, mavi, bej
    ya da koyu temali dama desenleri de calisiyor. Kenar seridi kullaniliyor cunku
    dama oradaki neredeyse tum pikselleri kapliyor."""
    mask = np.zeros(small.shape[:2], dtype=bool)
    mask[:ring, :] = mask[-ring:, :] = True
    mask[:, :ring] = mask[:, -ring:] = True

    values, counts = np.unique(pack_rgb(small[mask]), return_counts=True)
    order = np.argsort(counts)[::-1]
    total = counts.sum()

    tones, acc = [], 0
    for idx in order[:max_tones]:
        tones.append(unpack_rgb(int(values[idx])))
        acc += counts[idx]
        if acc / total >= coverage:
            break
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


def background_to_alpha(small: np.ndarray, tones: list[tuple[int, int, int]],
                        tol: int = 3, halo_tol_factor: float = 2.5,
                        halo_width: int = 0) -> np.ndarray:
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
    rgb = small.astype(np.int32)
    strong = np.zeros(small.shape[:2], dtype=bool)
    weak = np.zeros(small.shape[:2], dtype=bool)

    for tone in tones:
        dist = np.abs(rgb - np.array(tone, dtype=np.int32)).max(axis=2)
        strong |= dist <= tol
        weak |= dist <= tol * halo_tol_factor

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
    """Karakterin icinde yanlislikla seffaf kalmis kucuk delikleri komsu renklerin
    ortalamasiyla doldurur. 4-yonlu baglanti kullanilir: capraz bir noktadan disa
    'sizan' bosluklar aksi halde kenara bagli sayilip doldurulmadan kaliyordu."""
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
        ys, xs = np.where(labels == lbl)
        neighbors = []
        for y, x in zip(ys, xs):
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < rgba.shape[0] and 0 <= nx < rgba.shape[1] and rgba[ny, nx, 3] > 0:
                    neighbors.append(rgba[ny, nx, :3])
        if neighbors:
            fill = np.mean(neighbors, axis=0).astype(np.uint8)
            rgba[ys, xs] = (*fill, 255)
    return rgba


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

def cell_cores(arr: np.ndarray, gx: AxisGrid, gy: AxisGrid, inset: float = 1.5):
    """Her hucrenin AA sinirlarindan uzak cekirdek bolgesini dolasir.
    Donen: (i, j, core) — core: (N,3) int32."""
    xe, ye = gx.edges(arr.shape[1]), gy.edges(arr.shape[0])
    for i in range(gy.count):
        y0, y1 = int(np.ceil(ye[i] + inset)), int(np.floor(ye[i + 1] - inset))
        if y1 <= y0:
            continue
        for j in range(gx.count):
            x0, x1 = int(np.ceil(xe[j] + inset)), int(np.floor(xe[j + 1] - inset))
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
    Image.fromarray(overlay, "RGB").save(path)
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
            preview_scale: int = 8, bg_tol: int = 3, speck_size: int = 12,
            center_ratio: float = 0.5, debug_dir: str | None = None,
            no_crop: bool = False, merge_colors: int = 0,
            cleanup: bool = True, verify: bool = False) -> Image.Image:
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
        gx = detect_axis_grid(arr, axis=1, name="X")
        gy = detect_axis_grid(arr, axis=0, name="Y")
        print(f"Izgara: periyot X={gx.period:.4f}px  Y={gy.period:.4f}px   "
              f"faz X={gx.phase:.2f}  Y={gy.phase:.2f}")
        print(f"NATIVE cozunurluk: {gx.count}x{gy.count}  "
              f"(uyum X={gx.quality:.0%} Y={gy.quality:.0%})")

        if min(gx.quality, gy.quality) < 0.6:
            print("UYARI: izgara uyumu dusuk — sonucu --debug-dir ile gozle dogrulayin.",
                  file=sys.stderr)

        if debug_dir:
            os.makedirs(debug_dir, exist_ok=True)
            dump_grid_overlay(arr, gx, gy, os.path.join(debug_dir, "1_izgara.png"))

        # 2) native cozunurluge in
        small = downsample_by_mode(arr, gx, gy, center_ratio=center_ratio)

    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        Image.fromarray(small, "RGB").resize(
            (small.shape[1] * 8, small.shape[0] * 8), Image.NEAREST
        ).save(os.path.join(debug_dir, "2_native.png"))

    # 3) arka plan -> alfa
    if real_alpha is not None:
        alpha_small = downsample_by_mode(
            np.dstack([real_alpha] * 3), gx, gy, center_ratio=center_ratio
        )[:, :, 0]
        rgba = np.dstack([small, np.where(alpha_small > 127, 255, 0).astype(np.uint8)])
    else:
        tones = detect_background_tones(small)
        print("Dama tonlari:", ", ".join(f"#{r:02x}{g:02x}{b:02x}" for r, g, b in tones))
        rgba = background_to_alpha(small, tones, tol=bg_tol)

    if verify:
        if upscaled:
            print_verification(verify_extraction(arr, gx, gy, small, rgba[:, :, 3] > 0))
        else:
            print("\n--- DOGRULAMA ---\nGorsel zaten native; indirgeme yapilmadigi icin "
                  "kayip da soz konusu degil.")

    opaque_before = int((rgba[:, :, 3] > 0).sum())
    if debug_dir:
        Image.fromarray(rgba, "RGBA").resize(
            (rgba.shape[1] * 8, rgba.shape[0] * 8), Image.NEAREST
        ).save(os.path.join(debug_dir, "3_alfa.png"))

    # 4) temizlik — kirpma ONCESI, cunku uzakta kalan tek bir leke kirpma sinirini
    #    gereksiz genisletip karakteri tuvalde kaydiriyor
    if cleanup:
        rgba = remove_detached_specks(rgba, max_size=speck_size)
        rgba = fill_interior_holes(rgba, max_size=speck_size)
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
    out = Image.fromarray(rgba, "RGBA")
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
    parser.add_argument("--bg-tol", type=int, default=3,
                        help="Dama rengi eslesme toleransi (varsayilan 3). Arka planin bir "
                             "kismi kaldiysa artirin; karakterin acik renkleri yeniyorsa azaltin.")
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
                cleanup=not args.no_cleanup, verify=args.verify)
    except (ValueError, FileNotFoundError) as err:
        print(f"HATA: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
