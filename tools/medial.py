#!/usr/bin/env python3
"""
medial.py — siluetin medial ekseni (topolojik iskelet) ve uzerinde yol bulma.

NEDEN BU MODUL VAR
    `skeleton.py`nin satir/sutun bant olcumleri ONDEN gorunuste iyi calisiyor
    ama YANDAN cokuyor: uzuvlar ust uste bindigi icin el ve ayak bantlardan
    okunamiyor, ara eklemler de duz interpolasyonla yerlestiriliyor. Olculdu —
    ayni yurume klibinin kareleri arasinda kemik uzunluklari %79-144 oynuyordu.
    Gercek bir iskelette kemik uzamaz; yani o tahminler tutarli bir rig degildi.

    Medial eksen bu bosluğu tam olarak dolduruyor. Olculdu: bir yurume karesinde
    eksen omurgayi, iki kolu ve iki bacagi ayri dallar halinde veriyor, dallarin
    UCLARI el ve ayaklara denk geliyor ve dallar bacagin BUKULMESINI izliyor.
    Yani hem uc noktalar hem de uzuv yolu olculebilir hale geliyor.

    Yontem klasik (Zhang-Suen inceltmesi) ve bilerek bagimsiz secildi: numpy
    disinda bir sey gerektirmiyor, insansi varsaymiyor ve 87 piksellik bir
    karede 2-3 ms suruyor.

BUDAMA SART
    Ham eksen gurultulu: chunky bir pixel art siluetinde kucuk cikintilarin her
    biri kisa bir dal uretiyor (olculdu, mag'in idle karesinde 47 dallanma
    noktasi). Budanmadan uc noktalari saymak anlamsiz. `buda` kisa mahmuzlari
    ucundan geriye dogru siliyor.
"""
from __future__ import annotations

import numpy as np

# P2..P9, saat yonunde, P2 yukari (Zhang-Suen'in orijinal numaralandirmasi)
_OFS = ((0, 1), (0, 2), (1, 2), (2, 2), (2, 1), (2, 0), (1, 0), (0, 0))


def _komsu_katmanlari(a: np.ndarray) -> np.ndarray:
    pad = np.pad(a, 1)
    return np.stack([pad[dy:dy + a.shape[0], dx:dx + a.shape[1]] for dy, dx in _OFS])


def zhang_suen(maske: np.ndarray, max_tur: int = 200) -> np.ndarray:
    """Siluetin bir piksel kalinligindaki topolojik iskeleti.

    Iki alt adimli klasik algoritma: her turda sadece SINIR pikselleri, hem de
    baglantiyi bozmayanlar siliniyor. `A == 1` sarti tam olarak bunu koruyor —
    piksel cevresinde 0'dan 1'e tek bir gecis varsa o piksel bir kopru degildir."""
    img = maske.astype(np.uint8).copy()
    for _ in range(max_tur):
        degisti = False
        for adim in (0, 1):
            p = _komsu_katmanlari(img)
            B = p.sum(axis=0)                                  # dolu komsu sayisi
            halka = np.concatenate([p, p[:1]], axis=0)
            A = ((halka[:-1] == 0) & (halka[1:] == 1)).sum(axis=0)   # 0->1 gecisi
            P2, P3, P4, P5, P6, P7, P8, P9 = p
            if adim == 0:
                k1, k2 = P2 * P4 * P6, P4 * P6 * P8
            else:
                k1, k2 = P2 * P4 * P8, P2 * P6 * P8
            sil = (img == 1) & (B >= 2) & (B <= 6) & (A == 1) & (k1 == 0) & (k2 == 0)
            if sil.any():
                img[sil] = 0
                degisti = True
        if not degisti:
            break
    return img.astype(bool)


def komsu_sayisi(iskelet: np.ndarray) -> np.ndarray:
    """Her iskelet pikselinin 8-komsulugundaki iskelet pikseli sayisi."""
    pad = np.pad(iskelet, 1).astype(np.uint8)
    toplam = np.zeros(iskelet.shape, np.uint8)
    for dy in range(3):
        for dx in range(3):
            toplam += pad[dy:dy + iskelet.shape[0], dx:dx + iskelet.shape[1]]
    return toplam - iskelet.astype(np.uint8)


def uclar(iskelet: np.ndarray) -> list[tuple[int, int]]:
    """Tam bir komsusu olan pikseller — dal uclari (el, ayak, bas)."""
    k = komsu_sayisi(iskelet)
    return [(int(y), int(x)) for y, x in zip(*np.where(iskelet & (k == 1)))]


def buda(iskelet: np.ndarray, en_az: int = 6, max_tur: int = 20) -> np.ndarray:
    """`en_az` pikselden kisa MAHMUZLARI siler; uzun dallara dokunmaz.

    Gerekli, cunku ham eksende her kucuk siluet cikintisi bir dal uretiyor ve
    budanmadan "uc sayisi" anlamli bir sinyal olmuyor (olculdu: mag'in idle
    karesinde 47 dallanma noktasi).

    Yontem mahmuzu TANIYIP siliyor: her uctan dallanma noktasina kadar
    yuruyor, yol `en_az`dan kisaysa o yolu tumuyle kaldiriyor. Once "uc
    pikselleri N kez soy, sonra geri buyut" denendi ve ISE YARAMADI — geri
    buyutme mahmuzu dallanma noktasindan yeniden dolduruyor, yani islem
    kimlik fonksiyonuna donuyordu (olculdu: budanmis uc sayisi hamla birebir
    ayni cikti). Soymayi geri buyutmeden birakmak da yanlis: gercek uzuv
    uclari da N piksel kisaliyor ve el/ayak konumu kayiyor.

    Mahmuz silmek yeni uclar dogurabilir, o yuzden kararli hale gelene kadar
    tekrarlaniyor."""
    kalan = iskelet.copy()
    h, w = kalan.shape
    for _ in range(max_tur):
        k = komsu_sayisi(kalan)
        silinecek: set[tuple[int, int]] = set()
        for uc in [(int(y), int(x)) for y, x in zip(*np.where(kalan & (k == 1)))]:
            izlek, d, onceki = [uc], uc, None
            while len(izlek) <= en_az:
                ileri = [n for n in _komsular(*d, h, w)
                         if kalan[n] and n != onceki and n not in izlek]
                if len(ileri) != 1:
                    break                      # dallanma ya da cikmaz
                onceki, d = d, ileri[0]
                if k[d] >= 3:
                    break                      # dallanmaya varildi
                izlek.append(d)
            if len(izlek) <= en_az and k[d] >= 3:
                silinecek.update(izlek)
        if not silinecek:
            break
        for p in silinecek:
            kalan[p] = False
    return kalan


def _komsular(y: int, x: int, h: int, w: int):
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w:
                    yield ny, nx


def yol(iskelet: np.ndarray, bas: tuple[int, int],
        son: tuple[int, int]) -> list[tuple[int, int]]:
    """Iskelet uzerinde `bas`tan `son`a en kisa yol (BFS, 8-komsuluk).

    Yol duz cizgi DEGIL: uzvun kendi egrisini izliyor. Ara eklemi (diz,
    dirsek) bu yolun uzerine koymak, iki uc arasinda dogrusal interpolasyon
    yapmaktan bu yuzden farkli — bacak bukuldugunde diz gercekten bukulmenin
    oldugu yere dusuyor."""
    h, w = iskelet.shape
    if not (iskelet[bas] and iskelet[son]):
        return []
    onceki = {bas: None}
    kuyruk = [bas]
    while kuyruk:
        yeni = []
        for d in kuyruk:
            if d == son:
                z, p = [], d
                while p is not None:
                    z.append(p)
                    p = onceki[p]
                return z[::-1]
            for n in _komsular(*d, h, w):
                if iskelet[n] and n not in onceki:
                    onceki[n] = d
                    yeni.append(n)
        kuyruk = yeni
    return []


def yol_uzerinde(izlek: list[tuple[int, int]], oran: float) -> tuple[float, float]:
    """Yolun `oran` kadarindaki nokta (x, y). Oran YAY UZUNLUGUNA gore.

    Indeks ortasini almak yanlis olurdu: capraz adimlar duz adimlardan 1.41 kat
    uzun, yani indeks ortasi geometrik orta degil."""
    if not izlek:
        raise ValueError("bos yol")
    if len(izlek) == 1:
        y, x = izlek[0]
        return float(x), float(y)
    d = [0.0]
    for (y0, x0), (y1, x1) in zip(izlek, izlek[1:]):
        d.append(d[-1] + float(np.hypot(y1 - y0, x1 - x0)))
    hedef = d[-1] * oran
    i = int(np.searchsorted(d, hedef))
    i = max(1, min(i, len(izlek) - 1))
    pay = (hedef - d[i - 1]) / max(d[i] - d[i - 1], 1e-9)
    (y0, x0), (y1, x1) = izlek[i - 1], izlek[i]
    return float(x0 + (x1 - x0) * pay), float(y0 + (y1 - y0) * pay)


def en_yakin_iskelet(iskelet: np.ndarray, x: float, y: float) -> tuple[int, int] | None:
    """Verilen noktaya en yakin iskelet pikseli."""
    ys, xs = np.where(iskelet)
    if ys.size == 0:
        return None
    i = int(np.argmin((ys - y) ** 2 + (xs - x) ** 2))
    return int(ys[i]), int(xs[i])
