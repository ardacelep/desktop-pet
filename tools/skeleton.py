#!/usr/bin/env python3
"""
skeleton.py — karakter karesinden ISKELET cikarir ve poz verisini tasir.

NEDEN BU ARAC VAR
    Animasyon uretmenin iki yolu var ve IKISI DE ayni veriye ihtiyac duyuyor:
    hareketin zaman icinde EKLEM KOORDINATLARI olarak ifadesi.

      - Yerel yol: `rig_pose.py` parcalari eklemlerden donduruyor; dondurme
        merkezleri bu iskeletin eklemleri.
      - Bulut yolu: PixelLab'in /v2/animate-with-skeleton ucu tam olarak bu
        formati istiyor (kare basina keypoint listesi).

    Bu yuzden iskelet katmani ortak zemin. Etiketler PixelLab'in
    SkeletonLabel'iyla BIREBIR ayni tutuldu ki cikti dogrudan gonderilebilsin;
    uydurma bir sema kullanip sonra cevirmek gereksiz bir kayip noktasi olurdu.

OLCEREK BULUNAN LANDMARK'LAR
    Eklemleri "kafa %20, govde %50" gibi ORANLARLA yerlestirmek denenebilirdi;
    olcum bunun yanlis oldugunu gosterdi. Dort gercek karakterde boyun yuksekligi
    %30 (ael), %37 (mag), %41 (g1), %47 (omerhan) cikiyor — yani sabit bir oran
    hangi degeri secerse secsin en az iki karakterde 10 puandan fazla sapardi.

    Bunun yerine siluetten OLCULEBILEN uc capa kullaniliyor:

      BOYUN — satir genisligi profilinin, boyun %25-55 bandindaki en kucuk
        degeri. Kafa ile govde arasindaki daralma gercek ve derin bir yerel
        minimum: olculen genislikler 21/18/18/13 piksel, komsu satirlar
        26-35 piksel. Bant sinirlari gerekli, cunku profilin GLOBAL minimumu
        cogu zaman ayak bileginde.

      KALCA — bacaklarin govdede birlestigi satir; asagidan yukari tarayip
        sutunlarin tek banda dustugu ilk yer. Dort karakterde %76, %76, %76,
        %78 cikti; landmark'lar icinde en kararlisi bu.

      AYAKLAR — en alttaki %10'luk seridin sutun bantlari. TEK satir kullanmak
        kirilgan (ayakkabi konturundaki bir piksellik bosluk mag'de 4,
        omerhan'da 4 bant uretiyor); %10'luk serit dordunde de tam 2 bant
        veriyor. %15 fazla: omerhan'da iki ayak tek banda birlesiyor.

    Diz ve dirsek siluetten OLCULEMEZ (yan gorunuste uzuv govdeyle ortusuyor),
    bu yuzden capalar arasinda dogrusal yerlestiriliyorlar. Bu bir tahmin ve
    oyle isaretleniyor: `Iskelet.olculen` hangi noktalarin olculdugunu,
    hangilerinin turetildigini tutar.

YAN GORUNUS VE SOL/SAG
    Yandan bakan bir karakterde sol ve sag uzuv AYNI x'te durur; siluet
    hangisinin onde oldugunu soylemez. Ayak bantlari icin bir secim yapmak
    gerekiyor ve secim keyfi: bakis yonundeki ON banda "RIGHT", arkadakine
    "LEFT" deniyor ve on uzuv daha buyuk z_index aliyor. Anatomik dogruluk
    iddiasi yok; onemli olan tutarlilik, cunku poz sablonlari da ayni
    kurali kullaniyor.

KULLANIM
    python3 tools/skeleton.py characters/mag/idle_spritesheet.png --frame 0 \\
        --overlay iskelet.png
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

# PixelLab /v2/animate-with-skeleton ile BIREBIR ayni sira ve yazim.
# Kaynak: pixellab-code/pixellab-python, pixellab/models/keypoint.py
LABELS = (
    "NOSE", "NECK",
    "RIGHT SHOULDER", "RIGHT ELBOW", "RIGHT ARM",
    "LEFT SHOULDER", "LEFT ELBOW", "LEFT ARM",
    "RIGHT HIP", "RIGHT KNEE", "RIGHT LEG",
    "LEFT HIP", "LEFT KNEE", "LEFT LEG",
    "RIGHT EYE", "LEFT EYE", "RIGHT EAR", "LEFT EAR",
)

# "ARM" = el, "LEG" = ayak (PixelLab'in adlandirmasi; uzuv degil UC nokta).
EL = ("RIGHT ARM", "LEFT ARM")
AYAK = ("RIGHT LEG", "LEFT LEG")


@dataclass
class Iskelet:
    """Eklem konumlari, karenin SOL UST kosesine gore native piksel.

    `olculen` siluetten OLCULEN eklemler; digerleri turetilmis tahmin.
    `supheli` ise olculdu ama SINYAL ZAYIFTI demek — deger var, guvenilmez.
    Ikisini ayirmak sart: "olcum yaptik" ile "olcum anlamli" ayni sey degil.
    Karakterlerin cizim tarzi ayni olmadigi icin bir karakterde net olan
    isaret digerinde hic olmayabiliyor, ve bunu sessizce yutmak yanlis
    sonucu dogru gibi gosteriyor."""

    noktalar: dict[str, tuple[float, float]]
    z: dict[str, float] = field(default_factory=dict)
    olculen: frozenset[str] = frozenset()
    supheli: frozenset[str] = frozenset()

    def __post_init__(self):
        eksik = set(LABELS) - set(self.noktalar)
        if eksik:
            raise ValueError(f"eksik eklem: {sorted(eksik)}")

    def to_pixellab(self) -> list[dict]:
        """PixelLab'in `keypoints` listesi (tek kare)."""
        return [{"x": float(self.noktalar[a][0]), "y": float(self.noktalar[a][1]),
                 "label": a, "z_index": float(self.z.get(a, 0.0))}
                for a in LABELS]

    def tasi(self, dx: float, dy: float) -> "Iskelet":
        return Iskelet({a: (x + dx, y + dy) for a, (x, y) in self.noktalar.items()},
                       dict(self.z), self.olculen)


# ---------------------------------------------------------------------------
# Siluet olcumleri
# ---------------------------------------------------------------------------

def bantlar(maske: np.ndarray, bosluk: int = 1) -> list[tuple[int, int]]:
    """1B maskedeki dolu araliklar; `bosluk` kadar deligi kapatarak."""
    i = np.flatnonzero(maske)
    if i.size == 0:
        return []
    k = np.flatnonzero(np.diff(i) > bosluk)
    b = np.concatenate(([i[0]], i[k + 1]))
    e = np.concatenate((i[k], [i[-1]])) + 1
    return [(int(x), int(y)) for x, y in zip(b, e)]


def boyun_satiri(opak: np.ndarray, y0: int, y1: int, marj: int = 3) -> int:
    """Boynun GOVDEYLE BIRLESTIGI satir.

    Once %25-55 bandindaki en dar satir bulunuyor (bant sart: profilin global
    minimumu genelde ayak bileginde). Ama o satir boynun TEPESI, yani cene
    alti; eklem olarak istedigimiz sey boynun TABANI.

    Fark karaktere gore buyuyor ve dogrudan omuzlari da bozuyordu, cunku omuz
    satiri boyundan turetiliyor. Olculdu: tepe aliniyorken boyun yuksekligi
    dort karakterde %30/%37/%41/%47 diye dagiliyordu ve en dusuk deger (ael)
    cene hizasindaydi — omuzlar da oraya, ceketin yakasina cikip dar kaliyordu.
    Taban alininca dagilim %36/%40/%42/%49'a toplaniyor; en buyuk duzeltmeyi
    (+6 piksel) tam da sorunlu karakter aliyor.

    Taban, genisligin en dar degerin `marj` icinde kaldigi son satir."""
    h = y1 - y0 + 1
    gen = opak.sum(axis=1)
    bas, son = int(0.25 * h), max(int(0.25 * h) + 1, int(0.55 * h))
    tepe = y0 + bas + int(np.argmin(gen[y0 + bas:y0 + son]))
    sinir = y0 + int(0.60 * h)
    alt = tepe
    while alt + 1 <= sinir and gen[alt + 1] <= gen[tepe] + marj:
        alt += 1
    return alt


def el_satiri(opak: np.ndarray, omuz_y: int, kalca_y: int, tol: int = 2) -> int:
    """Elin yuksekligi: kolun dis kenarinin UC degerine yakin oldugu son satir.

    Once el yuksekligi kalcadan turetiliyordu (`kalca - %2h`) ve bu YANLISTI.
    Kalca dogru olculur olmaz hata ortaya cikti: mag'de kalca %77'ye
    oturunca el hizasi %75'e indi, ama mag'in kollari %73'te bitiyor —
    o satirda siluet artik yalnizca PANTOLON (bant (31,55)), dolayisiyla
    "el" noktalari pacanin kenarina, yani BACAKLARA tasiyordu.

    Kol ile govdeyi kiyaslamak da denendi ve kirilgan cikti: govde
    genisligini hangi satirdan okudugunuza gore mag'de pay 1-2 piksele
    dusuyor, faküs'te ise bol pacali pantolon koldan genis oldugu icin olcut
    hic calismiyor.

    Bunun yerine referanssiz bir olcut kullaniliyor: kollar siluetin en dis
    noktalarini olusturur, o yuzden dis kenarin KENDI uc degerine `tol`
    kadar yakin kaldigi son satir kolun bittigi yerdir. Bes karakterde de
    calisiyor (%73-%79), faküs dahil."""
    if kalca_y <= omuz_y:
        return kalca_y
    satirlar, sol, sag = [], [], []
    for y in range(int(omuz_y), int(kalca_y) + 1):
        b = bantlar(opak[y], bosluk=2)
        if b:
            satirlar.append(y)
            sol.append(b[0][0])
            sag.append(b[-1][1] - 1)
    if not satirlar:
        return kalca_y
    ml, mr = min(sol), max(sag)
    uygun = [y for y, l, r in zip(satirlar, sol, sag) if l <= ml + tol or r >= mr - tol]
    return max(uygun) if uygun else kalca_y


def goz_satiri(rgba: np.ndarray, y0: int, boyun_y: int,
               esik: int = 225, en_az: int = 2) -> tuple[int, list[tuple[int, int]]] | None:
    """Goz satirini SCLERA'dan (goz aki) olcer; bulunamazsa None.

    Gozleri kafa kutusunun ortasindan turetmek tutarsizdi ve gozle
    yakalandi: kutu SACI da iceriyor, topuzlu ya da uzun sacli bir
    karakterde kafa merkezi yukari kayiyor ve noktalar alina/saca biniyor.

    Sclera bu sprite'larda ayirt edici: ten orta tonda, sac koyu, goz aki
    neredeyse beyaz. Olculdu — dort karakterde de bulunuyor (satir basina
    4/5/6/9 parlak piksel), ve gozlukluler dahil calisiyor.

    Kapali gozde ya da koyu gozlukte sinyal yok; o zaman None donuyor ve
    cagiran turetilmis konuma dusuyor."""
    kafa = rgba[y0:boyun_y]
    if kafa.size == 0:
        return None
    parlak = (kafa[:, :, 3] > 0) & (kafa[:, :, :3].mean(axis=2) > esik)
    say = parlak.sum(axis=1)
    if say.max() < en_az:
        return None
    y = int(np.argmax(say))
    return y0 + y, bantlar(parlak[y], bosluk=2)


VARSAYILAN_KALCA = 0.77     # dort karakterin idle olcumu: %76,%76,%76,%78


def kalca_satiri(opak: np.ndarray, y0: int, y1: int, min_satir: int = 2,
                 en_alt: float = 0.95, dibe_kadar: float = 0.95,
                 bosluk: int = 5) -> int:
    """Bacaklarin govdede birlestigi satir (kasik).

    Olcut "bacaklar ayri mi" DEGIL, "ayrim SURUYOR mu". Fark kritik, cunku
    ayakkabi konturundaki bir piksellik bosluk da tek bir satiri iki bantli
    gosteriyor ve onu bacak ayrimi saymak kasigi tabana indiriyor. Olculdu:
    g1'in yurume sheet'inde 0. ve 5. karede iki bantli satir sayisi TEK
    (%98 ve %99) — gecis pozunda bacaklar tamamen ust uste, ayrim yok; kare
    2'de ise %65'ten baslayan 8 satirlik gercek bir dizi var.

    Bu yuzden en az `min_satir` uzunlugunda bir dizi araniyor ve kasik o
    dizinin EN UST satiri oluyor. Dizinin altini almak da yanlisti: kare 2'de
    ayrim %65-73 ve %84-99 diye iki parcaya bolunuyor (bacaklarin ust uste
    bindigi ara bolge), alttan bakan bir tarama %97'yi buluyordu.

    Uc sart birlikte gerekiyor; olculdu, her biri digerlerinin kacirdigi bir
    vakayi eliyor:

      `dibe_kadar` — bacaklar YERE kadar iner, kol boslugu inmez. Bu sart
        olmadan olcut kollari bacak saniyordu: mag'in idle karesinde kol ile
        govde arasindaki bosluk %59'da basliyor ve tarama kasigi oraya
        koyuyordu (dogrusu %77). Kasik 18 puan yukari kayinca el yuksekligi
        de (kasik - %2) yukari kayiyor ve ELLER ile DIRSEKLER bozuluyordu.

      TAM 2 BANT — kasikta iki bant vardir (bacak|bacak); kol hizasinda uc
        (kol|govde|kol). Bolgenin en ust satirini almak yerine en ust TAM
        IKI BANTLI satirini almak ikisini kesin ayiriyor. mag'de kol bolgesi
        3 bant, bacaklar 2.

      `en_alt` + `min_satir` — ayakkabi konturundaki bir piksellik bosluk da
        satiri iki bantli gosteriyor. g1'in yurume sheet'inde 0. ve 5. karede
        iki bantli satir sayisi TEK ve %98-99'da; bu sartlar onlari eliyor.

    `bosluk` bacaklar birbirine degdiginde ayrimin satirlarca kesilmesini
    tolere ediyor (omerhan'da 5 satir).

    Hic uygun bolge yoksa olculebilir bir sey yok; %77'ye dusuluyor."""
    h = y1 - y0 + 1
    ust = y0 + h // 2
    sayi = np.array([len(bantlar(opak[y])) for y in range(ust, y1 + 1)])
    if not (sayi >= 2).any():
        return y0 + int(VARSAYILAN_KALCA * h)

    # Boslukları kapat: bacaklar birbirine degdiginde ayrim satirlarca
    # kesilebiliyor (omerhan'da 5 satir), kontur da tek satirlik kesintiler
    # yapiyor.
    i = np.flatnonzero(sayi >= 2)
    kes = np.flatnonzero(np.diff(i) > bosluk)
    baslar = np.concatenate(([i[0]], i[kes + 1]))
    sonlar = np.concatenate((i[kes], [i[-1]]))

    for b, s in zip(baslar, sonlar):
        b, s = int(b), int(s)
        if s - b + 1 < min_satir:
            continue
        if (ust + s - y0) / h < dibe_kadar:          # bacaklar yere kadar iner
            continue
        if (ust + b - y0) / h > en_alt:              # en altta baslayan = kontur
            continue
        tam2 = [j for j in range(b, s + 1) if sayi[j] == 2]
        return y0 + (ust - y0) + (tam2[0] if tam2 else b)
    return y0 + int(VARSAYILAN_KALCA * h)


def ayak_bantlari(opak: np.ndarray, y0: int, y1: int,
                  pay: float = 0.10) -> list[tuple[int, int]]:
    """En alttaki `pay` oranindaki seridin sutun bantlari.

    Serit sart: tek satirda ayakkabi konturundaki bir piksellik bosluk iki
    karakterde ikiser sahte bant uretiyordu. %10 dort karakterde de tam iki
    bant veriyor; %15 fazla, omerhan'da ayaklari birlestiriyor."""
    ust = max(y0, y1 - int(pay * (y1 - y0 + 1)))
    return bantlar(opak[ust:y1 + 1].any(axis=0), bosluk=2)


# ---------------------------------------------------------------------------
# Tahmin
# ---------------------------------------------------------------------------

def _orta(bant: tuple[int, int]) -> float:
    return (bant[0] + bant[1] - 1) / 2.0


PROFIL_YONLERI = ("east", "west")

# Onden gorunuste eklemlerin siluet kenarindan ne kadar iceri alinacagi,
# govde genisliginin orani olarak. Uc deger de gozle ayarlandi — eklemin
# "kolun uzerinde" durup durmadigini olcecek bir referans yok.
OMUZ_ICERI = 0.18      # omuz basi, kolun govdeye baglandigi yer
DIRSEK_ICERI = 0.08    # ust kol on koldan kalin, dirsek biraz daha iceride
EL_ICERI = 0.04        # el neredeyse siluetin ucunda


def estimate(rgba: np.ndarray, direction: str = "south") -> Iskelet:
    """Tek bir karakter karesinden iskelet cikarir.

    `direction` PixelLab'in Direction'iyla ayni (south = one bakan, east =
    saga bakan). Iki gorunus AYRI ele alinmali, cunku bu projenin
    karakterlerinde ikisi de var: idle ONDEN, walk YANDAN cizilmis.

    Fark yalnizca etiketleme degil, neyin OLCULEBILIR oldugu:

      ONDEN (south/north) — sol ve sag uzuv yatayda ayri duruyor, yani omuz,
        el ve ayak hepsi siluetten okunabiliyor. Kollar govdenin iki yanina
        sarkiyor ve o yukseklikte siluetin EN DIS sutunlari ellerdir.

      YANDAN (east/west) — uzuvlar ust uste biniyor, siluet hangisinin onde
        oldugunu soylemiyor. Omuz ve el olculemiyor; govde ekseninden
        turetiliyor ve ayrim z_index'e birakiliyor."""
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError("RGBA bekleniyor")
    if direction not in ("south", "north", "east", "west"):
        raise ValueError(f"desteklenmeyen yon: {direction} "
                         "(south/north/east/west)")
    opak = rgba[:, :, 3] > 0
    ys, xs = np.where(opak)
    if ys.size == 0:
        raise ValueError("kare tamamen seffaf")
    y0, y1, x0, x1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
    h = y1 - y0 + 1
    profil = direction in PROFIL_YONLERI
    yon = 1.0 if direction in ("east", "south") else -1.0

    boyun_y = boyun_satiri(opak, y0, y1)
    kalca_y = kalca_satiri(opak, y0, y1)
    ayaklar = ayak_bantlari(opak, y0, y1)

    # Sinyal gucu. Her olcumun bir "bu karakterde gercekten var miydi"
    # kontrolu var; olculdu ama zayifsa deger yine uretiliyor, ama supheli
    # isaretleniyor ki kullanici once oraya baksin.
    supheli: set[str] = set()

    # Boyun: kafa ile govde arasindaki daralma NE KADAR belirgin? Dar bolge
    # uzunsa boyun ile gogus ayni genislikte demektir ve minimum keyfi kalir.
    # Olculdu — bes karakterde oran %2.4/%3.5/%3.6/%7.1 ve faküs'te %13.2;
    # faküs'te sacin omuzlara inmesi ve govdenin ince olmasi cukuru tamamen
    # yok ediyor (boyunda 26 piksel, gogüste 25-27).
    # Bolge TEPEDEN tabana sayilir: `boyun_satiri` zaten tabani donduruyor,
    # oradan asagi saymak bolgenin tamamini degil yalnizca kuyrugunu olcerdi.
    gen_prof = opak.sum(axis=1)
    _bas, _son = int(0.25 * h), max(int(0.25 * h) + 1, int(0.55 * h))
    tepe = y0 + _bas + int(np.argmin(gen_prof[y0 + _bas:y0 + _son]))
    dar = sum(1 for y in range(tepe, min(y0 + int(0.60 * h), y1) + 1)
              if gen_prof[y] <= gen_prof[tepe] + 3)
    if dar / h > 0.10:
        supheli.update({"NECK", "RIGHT SHOULDER", "LEFT SHOULDER"})
    if len(ayaklar) < 2:
        supheli.update({"RIGHT LEG", "LEFT LEG", "RIGHT KNEE", "LEFT KNEE"})

    def uclar(y: int) -> tuple[float, float]:
        """Satirin en dis opak sutunlari; bos satirda govde eksenine duser."""
        b = bantlar(opak[int(y)], bosluk=2)
        return (float(b[0][0]), float(b[-1][1] - 1)) if b else (govde_x, govde_x)

    def satir_ortasi(y: int, varsayilan: float) -> float:
        b = bantlar(opak[int(y)], bosluk=2)
        return _orta((b[0][0], b[-1][1])) if b else varsayilan

    govde_x = (x0 + x1) / 2.0
    govde_x = satir_ortasi((boyun_y + kalca_y) // 2, govde_x)
    boyun_x = satir_ortasi(boyun_y, govde_x)

    kafa_y = (y0 + boyun_y) / 2.0
    kafa_x = satir_ortasi((y0 + boyun_y) // 2, govde_x)
    kafa_h = max(1.0, boyun_y - y0)

    omuz_y = boyun_y + 0.05 * h
    kalca_ust = kalca_y - 0.04 * h      # eklem, bacaklarin ayrildigi yerin biraz ustu
    el_y = float(el_satiri(opak, int(omuz_y), int(kalca_y)))

    def uzuv(ust, uc):
        """Ara eklem (diz/dirsek): olculemiyor, capalar arasinda turetiliyor."""
        return ((ust[0] + uc[0]) / 2.0, (ust[1] + uc[1]) / 2.0)

    def dirsek(ust, uc, sag_taraf: bool):
        """Dirsek: yuksekligi turetilir, X'i KOLUN dis konturundan olculur.

        Duz orta nokta almak yanlisti: omuz siluetin %18 iceride, el ise dis
        kenarinda oldugu icin ikisinin ortasi kolu birakip GOVDENIN ICINE
        dusuyordu. Oysa kolun dis hatti o yukseklikte zaten siluetin kenari;
        olculdu, omuzdan ele inerken siluet once disari aciliyor (mag'de 28 ->
        40 piksel) sonra plato yapiyor — aciklanan bolge ust kol, plato ise
        dikey sarkan on kol. Dirsek ikisinin sinirinda ve X'i o satirin dis
        kenarindan bir kol yarisi iceride.

        Yukseklik olculmuyor: kol govdeye kaynastigi icin platonun basladigi
        satir karakterden karaktere %49-%75 arasinda dagiliyor (dort karakterde
        olculdu), yani guvenilir bir capa degil. Orta nokta korunuyor."""
        y = (ust[1] + uc[1]) / 2.0
        kenar_sol, kenar_sag = uclar(y)
        if sag_taraf:
            return (kenar_sol + DIRSEK_ICERI * genis, y)
        return (kenar_sag - DIRSEK_ICERI * genis, y)

    genis = max(1.0, uclar(omuz_y)[1] - uclar(omuz_y)[0])

    if profil:
        # Uzuvlar ust uste; govde ekseninden kucuk kaydirmalarla ayriliyorlar.
        on_omuz = arka_omuz = boyun_x
        on_omuz += yon * 0.02 * h
        arka_omuz -= yon * 0.02 * h
        on_el_x = govde_x + yon * 0.10 * (x1 - x0 + 1)
        arka_el_x = govde_x - yon * 0.04 * (x1 - x0 + 1)
        on_kalca_x = govde_x + yon * 0.02 * h
        arka_kalca_x = govde_x - yon * 0.02 * h
        olculen = frozenset({"NECK", "RIGHT LEG", "LEFT LEG"})
    else:
        # Onden: omuz ve el siluetin dis sutunlarindan OLCULUYOR.
        sol_u, sag_u = uclar(omuz_y)
        on_omuz, arka_omuz = sol_u + OMUZ_ICERI * genis, sag_u - OMUZ_ICERI * genis
        el_sol, el_sag = uclar(el_y)
        on_el_x, arka_el_x = el_sol + EL_ICERI * genis, el_sag - EL_ICERI * genis
        k_sol, k_sag = uclar(kalca_ust)
        k_gen = max(1.0, k_sag - k_sol)
        on_kalca_x, arka_kalca_x = k_sol + 0.28 * k_gen, k_sag - 0.28 * k_gen
        olculen = frozenset({"NECK", "RIGHT LEG", "LEFT LEG",
                             "RIGHT SHOULDER", "LEFT SHOULDER",
                             "RIGHT ARM", "LEFT ARM"})

    # Ayak bantlari: iki bant varsa ayrilir, yoksa ikisi de ayni yere.
    #
    # Profilde "on" = bakis yonundeki bant. Onden bakista ise ayaklar omuz ve
    # kalcayla AYNI tarafa dusmeli; yoksa kalca-diz-ayak zinciri capraziyor.
    # Bu tam olarak olan seydi: onden gorunuste omuz/kalca kucuk x'e (RIGHT),
    # ayak buyuk x'e atanip iskelet X ciziyordu. Onden bakan bir karakterde
    # (south) karakterin SAGI izleyicinin SOLUdur, yani kucuk x.
    if len(ayaklar) >= 2:
        ters = (yon > 0) if profil else (direction == "north")
        sirali = sorted(ayaklar, key=_orta, reverse=ters)
        on_ayak, arka_ayak = _orta(sirali[0]), _orta(sirali[-1])
    else:
        on_ayak = arka_ayak = _orta(ayaklar[0]) if ayaklar else govde_x

    n: dict[str, tuple[float, float]] = {
        "NOSE": (kafa_x + (yon * 0.22 * kafa_h if profil else 0.0), kafa_y),
        "NECK": (boyun_x, float(boyun_y)),
        "RIGHT SHOULDER": (on_omuz, omuz_y),
        "LEFT SHOULDER": (arka_omuz, omuz_y),
        "RIGHT ARM": (on_el_x, el_y),
        "LEFT ARM": (arka_el_x, el_y),
        "RIGHT HIP": (on_kalca_x, kalca_ust),
        "LEFT HIP": (arka_kalca_x, kalca_ust),
        "RIGHT LEG": (on_ayak, float(y1)),
        "LEFT LEG": (arka_ayak, float(y1)),
    }
    # Gozler once OLCULMEYE calisiliyor (sclera); bulunamazsa turetiliyor.
    olculen_goz = goz_satiri(rgba, y0, boyun_y)
    if olculen_goz is None:
        # Sclera yok (koyu goz, gozluk, kapali goz). Yuz noktalari kafa
        # KUTUSUNDAN turetiliyor ve kutu saci da iceriyor; sacli bir
        # karakterde bu belirgin sekilde kayiyor.
        supheli.update({"RIGHT EYE", "LEFT EYE", "NOSE", "RIGHT EAR", "LEFT EAR"})
    if olculen_goz is not None:
        goz_y, kumeler = olculen_goz
        if len(kumeler) >= 2 and not profil:
            sirali = sorted(kumeler, key=_orta, reverse=(direction == "north"))
            sag_goz, sol_goz = _orta(sirali[0]), _orta(sirali[-1])
        else:
            # Tek kume: profilde zaten tek goz gorunur, onden bakista da iki
            # goz bitisik cizilmis olabilir — kumeyi ikiye boluyoruz.
            k = kumeler[0]
            sag_goz, sol_goz = k[0] + (k[1] - k[0]) * 0.25, k[0] + (k[1] - k[0]) * 0.75
            if profil:
                sag_goz = sol_goz = _orta(k)
        n["RIGHT EYE"] = (sag_goz, float(goz_y))
        n["LEFT EYE"] = (sol_goz, float(goz_y))
        olculen = olculen | {"RIGHT EYE", "LEFT EYE"}
    elif profil:
        n["RIGHT EYE"] = (kafa_x + yon * 0.28 * kafa_h, kafa_y - 0.10 * kafa_h)
        n["LEFT EYE"] = (kafa_x + yon * 0.12 * kafa_h, kafa_y - 0.10 * kafa_h)
    else:
        n["RIGHT EYE"] = (kafa_x - 0.20 * kafa_h, kafa_y - 0.10 * kafa_h)
        n["LEFT EYE"] = (kafa_x + 0.20 * kafa_h, kafa_y - 0.10 * kafa_h)

    # Burun goz ile boyun arasinda, iki gozun ortasinda. Kafa kutusunun
    # merkezinden turetmek yerine goze baglaniyor: kutu saci da iceriyor.
    goz_orta_y = n["RIGHT EYE"][1]
    n["NOSE"] = ((n["RIGHT EYE"][0] + n["LEFT EYE"][0]) / 2.0
                 + (yon * 0.10 * kafa_h if profil else 0.0),
                 goz_orta_y + 0.30 * (boyun_y - goz_orta_y))

    # Kulaklar goz hizasinda, siluetin iki kenarinda.
    kulak_y = n["RIGHT EYE"][1]
    kulak_sol, kulak_sag = uclar(kulak_y)
    if profil:
        n["RIGHT EAR"] = (kafa_x - yon * 0.15 * kafa_h, kulak_y)
        n["LEFT EAR"] = (kafa_x - yon * 0.22 * kafa_h, kulak_y)
    else:
        n["RIGHT EAR"] = (kulak_sol, kulak_y)
        n["LEFT EAR"] = (kulak_sag, kulak_y)

    if profil:
        n["RIGHT ELBOW"] = uzuv(n["RIGHT SHOULDER"], n["RIGHT ARM"])
        n["LEFT ELBOW"] = uzuv(n["LEFT SHOULDER"], n["LEFT ARM"])
    else:
        n["RIGHT ELBOW"] = dirsek(n["RIGHT SHOULDER"], n["RIGHT ARM"], True)
        n["LEFT ELBOW"] = dirsek(n["LEFT SHOULDER"], n["LEFT ARM"], False)
    n["RIGHT KNEE"] = uzuv(n["RIGHT HIP"], n["RIGHT LEG"])
    n["LEFT KNEE"] = uzuv(n["LEFT HIP"], n["LEFT LEG"])

    # Profilde on uzuv kameraya yakin: z buyuk. Onden bakista derinlik farki
    # yok, z sifir kaliyor.
    z = {a: 0.0 for a in LABELS}
    if profil:
        for a in ("RIGHT SHOULDER", "RIGHT ELBOW", "RIGHT ARM",
                  "RIGHT HIP", "RIGHT KNEE", "RIGHT LEG"):
            z[a] = 1.0

    return Iskelet(n, z, olculen, frozenset(supheli))


# ---------------------------------------------------------------------------
# Rig: kareler arasinda DEGISMEYEN kemik uzunluklari
# ---------------------------------------------------------------------------

# Iki ucu da olculebilen zincirler. Ara eklem (dirsek/diz) IK ile cozuluyor.
ZINCIRLER = (
    ("RIGHT SHOULDER", "RIGHT ELBOW", "RIGHT ARM"),
    ("LEFT SHOULDER", "LEFT ELBOW", "LEFT ARM"),
    ("RIGHT HIP", "RIGHT KNEE", "RIGHT LEG"),
    ("LEFT HIP", "LEFT KNEE", "LEFT LEG"),
)


def kemik_uzunluklari(isk: "Iskelet") -> dict[tuple[str, str], float]:
    u = {}
    for a, b, c in ZINCIRLER:
        for p, q in ((a, b), (b, c)):
            (x0, y0), (x1, y1) = isk.noktalar[p], isk.noktalar[q]
            u[(p, q)] = float(np.hypot(x1 - x0, y1 - y0))
    return u


def rig_olustur(iskeletler: list["Iskelet"]) -> dict[tuple[str, str], float]:
    """Bir klibin karelerinden karakterin DEGISMEZ kemik uzunluklarini cikarir.

    Fikir AnimatedDrawings'ten: karakterin TEK bir rig'i vardir, pozlar onun
    varyasyonudur. Bizim avantajimiz ayni karakterin 4-8 karesine sahip
    olmamiz — bir tahmin kareler arasinda kemik uzunlugunu tutturamiyorsa
    yanlistir ve bunu dis bir modele ihtiyac duymadan olcebiliyoruz.

    Olculdu: duzeltmeden once ayni yurume klibinde kemik uzunluklari %79-144
    oynuyordu, yani tahminler tutarli bir rig degildi.

    Medyan aliniyor, ortalama degil: birkac karede tespit tamamen kaciyor ve
    ortalama o kacaklardan cekiliyor."""
    if not iskeletler:
        raise ValueError("en az bir iskelet gerekli")
    toplu: dict[tuple[str, str], list[float]] = {}
    for isk in iskeletler:
        for kb, u in kemik_uzunluklari(isk).items():
            toplu.setdefault(kb, []).append(u)
    return {kb: float(np.median(v)) for kb, v in toplu.items()}


def _iki_kemik_ik(uc1: tuple[float, float], uc2: tuple[float, float],
                  l1: float, l2: float,
                  tercih: tuple[float, float]) -> tuple[float, float]:
    """Iki ucu ve iki kemik uzunlugu bilinen zincirde ara eklemi bulur.

    Iki cozum var (zincir ileri ya da geri bukuluyor); `tercih`e yakin olani
    seciliyor — o da medial eksenden ya da onceki tahminden geliyor.

    Zincir yetismiyorsa (uclar l1+l2'den uzak) cember kesisimi yok; ara eklem
    iki uc arasinda oranli yerlestiriliyor. Bu durum gercek bir sinyaldir:
    ya uclar yanlis olculmustur ya da rig o kareye uymuyordur."""
    (x1, y1), (x2, y2) = uc1, uc2
    dx, dy = x2 - x1, y2 - y1
    d = float(np.hypot(dx, dy))
    if d < 1e-6:
        return (x1 + l1, y1)
    if d >= l1 + l2 or d <= abs(l1 - l2):
        t = l1 / max(l1 + l2, 1e-6)
        return (x1 + dx * t, y1 + dy * t)
    a = (l1 * l1 - l2 * l2 + d * d) / (2 * d)
    yuk = float(np.sqrt(max(0.0, l1 * l1 - a * a)))
    mx, my = x1 + dx * a / d, y1 + dy * a / d
    nx, ny = -dy / d, dx / d
    aday = ((mx + nx * yuk, my + ny * yuk), (mx - nx * yuk, my - ny * yuk))
    return min(aday, key=lambda p: (p[0] - tercih[0]) ** 2 + (p[1] - tercih[1]) ** 2)


def rige_oturt(isk: "Iskelet", rig: dict[tuple[str, str], float]) -> "Iskelet":
    """Ara eklemleri rig'in kemik uzunluklarina uyacak sekilde yeniden koyar.

    Uc noktalar (omuz, el, kalca, ayak) DOKUNULMADAN birakiliyor: onlar
    olculuyor. Degisen yalnizca dirsek ve diz — zaten olculemeyen, turetilen
    iki eklem."""
    n = dict(isk.noktalar)
    for a, b, c in ZINCIRLER:
        l1, l2 = rig.get((a, b)), rig.get((b, c))
        if not l1 or not l2:
            continue
        n[b] = _iki_kemik_ik(n[a], n[c], l1, l2, tercih=n[b])
    return Iskelet(n, dict(isk.z), isk.olculen, isk.supheli)


# ---------------------------------------------------------------------------
# Gorsel dogrulama
# ---------------------------------------------------------------------------

KEMIKLER = (
    ("NOSE", "NECK"),
    ("NECK", "RIGHT SHOULDER"), ("RIGHT SHOULDER", "RIGHT ELBOW"),
    ("RIGHT ELBOW", "RIGHT ARM"),
    ("NECK", "LEFT SHOULDER"), ("LEFT SHOULDER", "LEFT ELBOW"),
    ("LEFT ELBOW", "LEFT ARM"),
    ("NECK", "RIGHT HIP"), ("RIGHT HIP", "RIGHT KNEE"), ("RIGHT KNEE", "RIGHT LEG"),
    ("NECK", "LEFT HIP"), ("LEFT HIP", "LEFT KNEE"), ("LEFT KNEE", "LEFT LEG"),
)


def overlay(rgba: np.ndarray, iskelet: Iskelet, olcek: int = 8) -> Image.Image:
    """Iskeleti karenin uzerine cizer. Tek dogrulama yolu goz — eklemlerin
    dogru yerde olup olmadigini olcecek bir referans yok."""
    from PIL import ImageDraw

    im = Image.fromarray(rgba).resize(
        (rgba.shape[1] * olcek, rgba.shape[0] * olcek), Image.NEAREST
    ).convert("RGBA")
    kat = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(kat)
    p = lambda a: ((iskelet.noktalar[a][0] + 0.5) * olcek,
                   (iskelet.noktalar[a][1] + 0.5) * olcek)

    for a, b in KEMIKLER:
        d.line([p(a), p(b)], fill=(0, 200, 255, 200), width=max(1, olcek // 4))
    for a in LABELS:
        x, y = p(a)
        if a in iskelet.supheli:                      # zayif sinyal: once buna bak
            r, renk = olcek * 0.5, (255, 140, 0, 255)
        elif a in iskelet.olculen:
            r, renk = olcek * 0.45, (255, 60, 60, 255)
        else:
            r, renk = olcek * 0.3, (255, 220, 0, 255)
        d.ellipse([x - r, y - r, x + r, y + r], fill=renk)
    return Image.alpha_composite(im, kat)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def kareyi_al(yol: str, kare: int, kutu: int | None) -> np.ndarray:
    rgba = np.array(Image.open(yol).convert("RGBA"))
    k = kutu or rgba.shape[0]
    if rgba.shape[1] % k == 0 and rgba.shape[1] > k:
        return rgba[:, kare * k:(kare + 1) * k]
    return rgba


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Karakter karesinden iskelet cikarir (PixelLab uyumlu).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Ornek:\n  python3 tools/skeleton.py characters/mag/idle_spritesheet.png "
               "--overlay iskelet.png")
    p.add_argument("sprite", help="Karakter PNG (tek kare ya da yatay serit)")
    p.add_argument("--frame", type=int, default=0, help="Serit ise kacinci kare (varsayilan 0)")
    p.add_argument("--frame-size", type=int, default=None, help="Kare kutusu (varsayilan yukseklik)")
    p.add_argument("--direction", choices=("south", "north", "east", "west"),
                   default="south",
                   help="Karakterin baktigi yon, PixelLab Direction'iyla ayni: "
                        "south = one bakan (idle), east = saga bakan (walk). "
                        "Varsayilan south.")
    p.add_argument("--overlay", help="Iskeleti kareye cizip bu dosyaya yazar")
    p.add_argument("--overlay-scale", type=int, default=8, help="Overlay buyutmesi (varsayilan 8)")
    p.add_argument("--json", help="Eklem koordinatlarini bu dosyaya yazar")
    args = p.parse_args(argv)

    try:
        kare = kareyi_al(args.sprite, args.frame, args.frame_size)
        isk = estimate(kare, direction=args.direction)
    except (ValueError, FileNotFoundError, OSError) as err:
        print(f"HATA: {err}", file=sys.stderr)
        return 1

    print(f"{os.path.basename(args.sprite)} kare {args.frame} ({kare.shape[1]}x{kare.shape[0]}):")
    for a in LABELS:
        x, y = isk.noktalar[a]
        isaret = ("ZAYIF SINYAL" if a in isk.supheli
                  else "olculdu " if a in isk.olculen else "turetildi")
        print(f"  {a:<16s} x={x:6.1f} y={y:6.1f}  z={isk.z.get(a, 0.0):.0f}  {isaret}")
    if isk.supheli:
        print(f"\nUYARI: {len(isk.supheli)} eklem zayif sinyalle bulundu — bu "
              "karakterin cizim tarzinda o isaret yok.\n"
              "Once bunlari elle duzeltin:  npm run skeleton", file=sys.stderr)

    if args.overlay:
        overlay(kare, isk, args.overlay_scale).save(args.overlay)
        print(f"Overlay: {args.overlay}  (kirmizi = olculdu, turuncu = zayif "
              f"sinyal, sari = turetildi)")
    if args.json:
        with open(args.json, "w") as f:
            json.dump({"keypoints": isk.to_pixellab()}, f, indent=2)
        print(f"JSON: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
