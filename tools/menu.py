#!/usr/bin/env python3
"""
menu.py — tools/ altındaki araçlar için etkileşimli menü.

    npm run tools

NEDEN VAR
    Araçların tek tek CLI'ı zaten çalışıyor; zahmet olan şey onları DOĞRU SIRADA
    birbirine zincirlemek. split_sheet.py'nin başlığında anlatılan sıra
    (önce çıkar, sonra böl, sonra paketle) sezgiye ters ve yanlış sırada
    yapıldığında hata vermiyor — sadece kareler farklı piksel ölçeğinde çıkıyor.
    Buradaki 1 numaralı akış o sırayı garanti eder ve ara dosyaları kendisi
    yönetir.

    Ayrıca her adımda ÇALIŞTIRDIĞI KOMUTU ekrana basar; menüyü öğrenme
    tekerleği gibi kullanıp sonra doğrudan CLI'a geçebilirsin.

BAĞIMLILIK
    Menünün kendisi saf standart kütüphane. numpy/Pillow yalnızca alt
    araçlarda gerekiyor, o yüzden menü uygun yorumlayıcıyı kendisi arıyor.
"""
from __future__ import annotations

import glob
import os
import re
import shlex
import subprocess
import sys
import time

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARAC = os.path.join(KOK, "tools")


# ---------------------------------------------------------------------------
# Ortam
# ---------------------------------------------------------------------------

def yorumlayici() -> str:
    """numpy + Pillow'u olan ilk python3'ü bulur.

    Sabit `python3` yazmak kırılgan: bu makinede PATH'in başında pyenv shim'i
    duruyor ve kurulu paketler yorumlayıcıdan yorumlayıcıya değişiyor. Yanlışını
    seçince hata, aracın ilk satırındaki ImportError olarak çıkıyor ve kullanıcı
    için "araç bozuk" gibi görünüyor."""
    adaylar = [sys.executable, "python3", "/opt/homebrew/bin/python3",
               "/usr/bin/python3", "python"]
    for aday in adaylar:
        if not aday:
            continue
        try:
            subprocess.run([aday, "-c", "import numpy, PIL"],
                           check=True, capture_output=True, timeout=30)
            return aday
        except (OSError, subprocess.SubprocessError):
            continue
    print("HATA: numpy ve Pillow'u olan bir python3 bulunamadı.\n"
          "      Kurmak için:  python3 -m pip install numpy pillow", file=sys.stderr)
    sys.exit(1)


PY = ""   # ilk kullanımda dolduruluyor


# ---------------------------------------------------------------------------
# Girdi yardımcıları
# ---------------------------------------------------------------------------

def temizle(yol: str) -> str:
    """Terminale sürükle-bırakla gelen yolu kullanılabilir hale getirir.

    macOS Terminal boşlukları `\\ ` diye kaçırıyor, bazı kabuklar da yolu
    tırnak içine alıyor. İkisi de olduğu gibi bırakılırsa dosya bulunamıyor."""
    yol = yol.strip()
    if len(yol) >= 2 and yol[0] == yol[-1] and yol[0] in "\"'":
        yol = yol[1:-1]
    else:
        yol = yol.replace("\\ ", " ")
    return os.path.expanduser(yol.strip())


def sor(soru: str, varsayilan: str | None = None) -> str:
    ek = f" [{varsayilan}]" if varsayilan else ""
    while True:
        try:
            cevap = input(f"{soru}{ek}: ").strip()
        except EOFError:
            raise KeyboardInterrupt
        if cevap:
            return cevap
        if varsayilan is not None:
            return varsayilan
        print("  (boş geçilemez)")


IPTAL = ("q", "iptal", "geri")


def _iptal_mi(cevap: str) -> None:
    """`q` her yerde menüye döndürür.

    Olmayan bir yol girildiğinde soru tekrarlanıyor; çıkış yolu olmayınca
    kullanıcı Ctrl-C'ye basmak zorunda kalıyordu ve o da tüm menüyü kapatıyor."""
    if cevap.strip().lower() in IPTAL:
        raise KeyboardInterrupt


def yol_sor(soru: str, varsayilan: str | None = None, olmali: bool = True) -> str:
    while True:
        cevap = sor(soru, varsayilan)
        _iptal_mi(cevap)
        yol = temizle(cevap)
        if not olmali or os.path.exists(yol):
            return yol
        print(f"  bulunamadı: {yol}  (q = menüye dön)")


ARANAN_KLASORLER = ("~/Desktop", "~/Downloads", "~/Masaüstü", "~/İndirilenler")


def _boyut(bayt: int) -> str:
    for birim in ("B", "KB", "MB", "GB"):
        if bayt < 1024 or birim == "GB":
            return f"{bayt:.0f} {birim}" if birim == "B" else f"{bayt:.1f} {birim}"
        bayt /= 1024.0
    return ""


def _kisa_ad(ad: str, en: int = 40) -> str:
    """Uzun adı ORTADAN kısaltır.

    Sondan kesmek işe yaramıyor: `Gemini_Generated_Image_<hash>.png` adlarında
    ayırt edici kısım sonda ve baştan 40 karakter alınca iki ayrı dosya listede
    birebir aynı görünüyor — yanlış olanı seçmek çok kolay."""
    if len(ad) <= en:
        return ad
    bas = (en - 1) // 2
    return ad[:bas] + "…" + ad[len(ad) - (en - 1 - bas):]


def _yas(saniye: float) -> str:
    dk = saniye / 60
    if dk < 1:
        return "az önce"
    if dk < 60:
        return f"{dk:.0f} dk önce"
    if dk < 24 * 60:
        return f"{dk / 60:.0f} saat önce"
    gun = dk / (24 * 60)
    return "dün" if gun < 2 else f"{gun:.0f} gün önce"


# Araçların KENDİ ürettiği dosyaların ad ekleri. Ham AI çıktısı istenen adımda
# bunlar listeden düşürülüyor: hepsi taze olduğu için listenin tepesine çıkıyor
# ve "en yenisi" varsayılanı bir önceki çalıştırmanın çıktısını seçiyordu.
TURETILMIS = ("_native", "_onizleme", "_spritesheet", "_kare_sinirlari")


def son_pngler(limit: int = 12, haric: tuple[str, ...] = ()) -> list[str]:
    """Masaüstü/İndirilenler ve repo kökündeki PNG'ler, yeniden eskiye.

    AI çıktısı neredeyse her zaman bu iki klasöre iniyor; asıl istenen dosya da
    genelde en yenisi oluyor. Tek seviye taranıyor — özyineleme büyük bir
    İndirilenler klasöründe menüyü bekletir ve aranan dosya zaten tepede."""
    bulunan: dict[str, float] = {}
    for klasor in (*ARANAN_KLASORLER, KOK, os.getcwd()):
        kok = os.path.expanduser(klasor)
        try:
            with os.scandir(kok) as girisler:
                for g in girisler:
                    ad = g.name.lower()
                    if not ad.endswith(".png") or not g.is_file():
                        continue
                    if any(ek in ad for ek in haric):
                        continue
                    bulunan[os.path.realpath(g.path)] = g.stat().st_mtime
        except OSError:
            continue
    return sorted(bulunan, key=lambda y: -bulunan[y])[:limit]


def dosya_sor(soru: str, haric: tuple[str, ...] = ()) -> str:
    """PNG seçtirir: listeden numarayla, ya da yol yapıştırarak/sürükleyerek.

    Yol yazdırmak menünün asıl sürtünme noktasıydı. Liste ilk seçenek, çünkü
    aranan dosya çoğu zaman en son inen dosya; ama liste dışında bir şey
    isteyene de yol girişi açık kalıyor — `haric` yalnızca LİSTEYİ süzer,
    elle verilen yolu engellemez."""
    adaylar = son_pngler(haric=haric)
    if not adaylar:
        return yol_sor(soru)

    print("\n  Masaüstü/İndirilenler ve repodaki son PNG'ler:")
    simdi = time.time()
    for i, yol in enumerate(adaylar, 1):
        try:
            st = os.stat(yol)
        except OSError:
            continue
        nere = kisalt(os.path.dirname(yol))
        print(f"   {i:2d}) {_kisa_ad(os.path.basename(yol)):<40s} {_boyut(st.st_size):>9s}"
              f"  {_yas(simdi - st.st_mtime):<11s} {nere}")

    while True:
        cevap = sor(f"\n{soru} — numara, ya da yol yapıştır/sürükle (q = geri)", "1")
        _iptal_mi(cevap)
        if cevap.isdigit() and 1 <= int(cevap) <= len(adaylar):
            secilen = adaylar[int(cevap) - 1]
            print(f"  → {kisalt(secilen)}")
            return secilen
        yol = temizle(cevap)
        if os.path.exists(yol):
            return yol
        print(f"  bulunamadı: {yol}  (listeden numara da seçebilirsin)")


def sayi_sor(soru: str, varsayilan: str = "") -> str:
    """Boş bırakılabilen sayı. Boş = aracın kendi varsayılanı/otomatiği."""
    if not varsayilan:
        soru += " (boş = otomatik)"
    while True:
        cevap = sor(soru, varsayilan).strip()
        if not cevap or cevap.isdigit():
            return cevap
        print("  sayı ya da boş bırak")


def evet_mi(soru: str, varsayilan: bool = True) -> bool:
    v = "E/h" if varsayilan else "e/H"
    cevap = sor(f"{soru} [{v}]", "e" if varsayilan else "h").lower()
    return cevap.startswith("e") or cevap.startswith("y")


# ---------------------------------------------------------------------------
# Çalıştırma
# ---------------------------------------------------------------------------

def kisalt(parca: str) -> str:
    """Yankılanan komutu okunur tutar.

    Yolları olduğu gibi basınca komut satırı ekrana sığmıyor ve "bunu ben de
    elle yazabilirim" duygusu kayboluyor — oysa komutu göstermenin amacı tam da
    o. Repo içi yollar repoya göre, dışarıdakiler ev dizinine göre kısaltılıyor;
    ikisi de çalışan komut üretir çünkü alt süreçler cwd=KOK ile başlıyor."""
    if not os.path.isabs(parca):
        return parca
    icerde = os.path.relpath(parca, KOK)
    if not icerde.startswith(".."):
        return icerde
    ev = os.path.expanduser("~")
    return "~" + parca[len(ev):] if parca.startswith(ev + os.sep) else parca


def alintila(parca: str) -> str:
    """shlex.quote, ama baştaki `~` tırnağın DIŞINDA kalır.

    shlex.quote('~/x y.png') -> '~/x y.png' ve kabuk tırnaklı tilde'yi
    genişletmez; yankılanan komut kopyalanınca çalışmaz. `~` dışarıda
    bırakılınca hem genişliyor hem gövde tırnaklanmış oluyor."""
    if parca.startswith("~/"):
        return "~" + shlex.quote(parca[1:])
    return shlex.quote(parca)


def calistir(komut: list[str]) -> bool:
    """Komutu gösterip çalıştırır. Çıktı doğrudan terminale akar."""
    print(f"\n  $ {' '.join(alintila(kisalt(p)) for p in komut)}\n")
    try:
        return subprocess.run(komut, cwd=KOK).returncode == 0
    except OSError as err:
        print(f"HATA: komut çalıştırılamadı — {err}", file=sys.stderr)
        return False


def arac(ad: str, *argumanlar: str) -> bool:
    return calistir([PY, os.path.join(ARAC, ad), *argumanlar])


def secenek(bayrak: str, deger: str) -> list[str]:
    """Boş değerli seçeneği komut satırından tamamen düşürür."""
    return [bayrak, deger] if deger else []


# ---------------------------------------------------------------------------
# Adımlar
# ---------------------------------------------------------------------------

def adim_extract() -> None:
    """Ham AI çıktısı -> native çözünürlük + gerçek alfa."""
    print("\n— Pixel art çıkar (pixelart_extract.py) —")
    print("  Ham Gemini/AI çıktısını native çözünürlüğe indirir, dama desenli")
    print("  arka planı gerçek şeffaflığa çevirir.")
    girdi = dosya_sor("Ham PNG", haric=TURETILMIS)
    kok = os.path.splitext(girdi)[0]
    cikti = temizle(sor("Çıktı PNG", kisalt(kok + "_native.png")))

    ek: list[str] = []
    if evet_mi("Büyütülmüş önizleme de üretilsin mi?", True):
        ek += ["--preview", kok + "_onizleme.png"]
    if evet_mi("Ayrıntılı tanı çıktısı (--verify -v)?", False):
        ek += ["--verify", "-v"]

    if arac("pixelart_extract.py", girdi, cikti, *ek):
        print(f"\n✓ Bitti: {kisalt(cikti)}")
        print("  Sonuç kötüyse: --bg-tol ile tolerans, --debug-dir ile ara adımlar.")


def adim_split() -> str | None:
    """Çıkarılmış sheet -> tek tek kareler."""
    print("\n— Sheet'i karelere böl (split_sheet.py) —")
    print("  DİKKAT: girdi, pixelart_extract'ten GEÇMİŞ olmalı. Kareleri ayıran")
    print("  boşluğu bulabilmek için arka planın gerçekten şeffaf olması gerekiyor.")
    sheet = dosya_sor("Çıkarılmış sheet PNG")
    klasor = temizle(sor("Karelerin yazılacağı klasör",
                         kisalt(os.path.splitext(sheet)[0] + "_kareler")))
    kare_sayisi = sayi_sor("Beklenen kare sayısı")

    # Otomatik bulma kareler arasindaki BOS seride dayaniyor. Sikisik bir izgarada
    # kareler birbirine degebiliyor; o zaman tek care esit bolme. Bunu menude
    # sormazsak kullanicinin CLI'a dusmesi gerekiyordu.
    satir = sutun = ""
    if not evet_mi("Kareler arasında boşluk var mı (otomatik bulunsun)?", True):
        print("  Izgara ölçüsünü ver — içerik eşit hücrelere bölünecek.")
        satir = sayi_sor("Satır sayısı", "2")
        sutun = sayi_sor("Sütun sayısı", "4")

    # Onizleme kare klasorunun DISINA yaziliyor: paketleme adimi o klasordeki
    # butun PNG'leri kare sayiyor, iceri konsa fazladan bir kare olarak girerdi.
    onizleme = klasor.rstrip(os.sep) + "_bolme.png"

    if arac("split_sheet.py", sheet, "-o", klasor,
            *secenek("--frames", kare_sayisi),
            *secenek("--rows", satir), *secenek("--cols", sutun),
            "--preview", onizleme):
        print(f"\n✓ Bitti: {kisalt(klasor)}")
        print(f"  Bölme doğru mu: {kisalt(onizleme)} (kare sınırları kırmızı)")
        return klasor
    return None


def adim_pack(klasor: str | None = None) -> None:
    """Tek tek kareler -> hizalanmış sprite sheet + meta.json bloğu."""
    print("\n— Kareleri hizala ve paketle (pack_sheet.py) —")
    print("  Kareleri ayak çizgisine ve gövde örtüşmesine göre hizalar;")
    print("  animasyondaki titremeyi bu adım giderir.")
    klasor = klasor or yol_sor("Karelerin bulunduğu klasör")
    kareler = sorted(glob.glob(os.path.join(klasor, "*.png")))
    if not kareler:
        print(f"  {klasor} içinde PNG yok.")
        return
    print(f"  {len(kareler)} kare bulundu: {', '.join(os.path.basename(k) for k in kareler[:4])}"
          + (" …" if len(kareler) > 4 else ""))

    klip = sor("Klip adı (meta.json'daki)", "walk_right")
    cikti = temizle(sor("Çıktı sheet PNG",
                        kisalt(os.path.join(klasor, f"{klip}_spritesheet.png"))))
    gif = os.path.join(klasor, f"{klip}_onizleme.gif")
    sure = sayi_sor("Kare başına ms", "120") or "120"

    if arac("pack_sheet.py", *kareler, "-o", cikti,
            "--clip", klip, "--duration", sure, "--gif", gif):
        print(f"\n✓ Bitti: {kisalt(cikti)}")
        print(f"  Önizleme GIF: {kisalt(gif)} — titreme varsa orada görünür.")
        print("  Yukarıdaki meta.json bloğunu karakterin meta.json'ına kopyala.")


def akis_tam() -> None:
    """Ham AI çıktısından oynamaya hazır sprite sheet'e kadar tüm boru hattı."""
    print("\n— Tam boru hattı —")
    print("  Ham sheet → çıkar → karelere böl → hizala/paketle.")
    print("  Ara dosyalar bir çalışma klasöründe kalır, adım adım gözle bakabilirsin.")
    girdi = dosya_sor("Ham AI sheet PNG (animasyonun tüm kareleri)", haric=TURETILMIS)
    kok = os.path.splitext(girdi)[0]
    calisma = temizle(sor("Çalışma klasörü", kisalt(kok + "_calisma")))
    klip = sor("Klip adı", "walk_right")
    kare_sayisi = sayi_sor("Beklenen kare sayısı")
    os.makedirs(calisma, exist_ok=True)

    native = os.path.join(calisma, "1_native.png")
    kareler_dir = os.path.join(calisma, "2_kareler")
    sheet = os.path.join(calisma, f"{klip}_spritesheet.png")
    gif = os.path.join(calisma, f"{klip}_onizleme.gif")

    print("\n[1/3] Native çözünürlüğe indiriliyor…")
    if not arac("pixelart_extract.py", girdi, native,
                "--preview", os.path.join(calisma, "1_native_onizleme.png")):
        print("\n✗ Çıkarım başarısız — boru hattı durdu.")
        return

    print("\n[2/3] Kareler ayrılıyor…")
    if not arac("split_sheet.py", native, "-o", kareler_dir,
                "--preview", os.path.join(calisma, "2_kare_sinirlari.png"),
                *secenek("--frames", kare_sayisi)):
        print(f"\n✗ Bölme başarısız. {kisalt(native)} dosyasına bakıp kareler arasında")
        print("  gerçekten boş satır/sütun var mı kontrol et.")
        return

    kareler = sorted(glob.glob(os.path.join(kareler_dir, "*.png")))
    print(f"\n[3/3] {len(kareler)} kare hizalanıyor…")
    if not arac("pack_sheet.py", *kareler, "-o", sheet,
                "--clip", klip, "--gif", gif):
        print("\n✗ Paketleme başarısız.")
        return

    print("\n" + "=" * 60)
    print(f"✓ Sprite sheet : {kisalt(sheet)}")
    print(f"  Önizleme GIF : {kisalt(gif)}   ← önce buna bak, titreme varsa görünür")
    print(f"  Ara adımlar  : {kisalt(calisma)}")
    print("\n  Sıradaki: yukarıdaki meta.json bloğunu characters/<ad>/meta.json'a")
    print("  kopyala, sonra doğrulamak için bu menüden 6'yı çalıştır.")


def adim_iki_gorunus() -> None:
    """PROMPTS.md bolum 5'teki iki gorunuslu ciktiyi onden+yandan kareye ayirir.

    Ayri bir adim, cunku bu ikisi ayni animasyonun kareleri DEGIL — iki farkli
    gorunus. Tam boru hatti onlari sprite sheet'e paketlerdi."""
    print("\n— İki görünüşü ayır —")
    print("  Gemini'ye 2x2 düzende önden + sağa bakan hali ürettirdiysen buradan geç.")
    print("  Önden kare ÖLÇEK ÇIPASI: ana karakteri de o çıktıdan al, eskisini saklama.")
    girdi = dosya_sor("Ham Gemini PNG (iki görünüş)", haric=TURETILMIS)
    kok = os.path.splitext(girdi)[0]
    cikti = temizle(sor("Çıktı klasörü", kisalt(kok + "_gorunusler")))
    periyot = sayi_sor("Izgara periyodu (boş = otomatik; 2048'lik çıktıda 10.24)")
    bg = sayi_sor("Dama toleransı (boş = ölçülerek seçilsin)")
    if arac("iki_gorunus.py", girdi, "-o", cikti,
            *secenek("--period", periyot), *secenek("--bg-tol", bg)):
        print(f"\n✓ Bitti: {kisalt(cikti)}")
    else:
        print("\n✗ Ölçüm kabul etmedi — yukarıdaki işaretli maddeye bak.")


def adim_grid_ref() -> None:
    """Bitmis sheet -> Gemini'ye verilecek izgara referansi."""
    print("\n— Izgara referansı üret (grid_ref.py) —")
    print("  Bitmiş bir sprite sheet'i Gemini'ye poz referansı olarak verilecek")
    print("  ızgaraya çevirir: magenta dama, kenar payı, ve sağ alt hücre BOŞ")
    print("  (Gemini filigranı oraya düşsün, karakterin üstüne gelmesin).")
    sheet = dosya_sor("Bitmiş sprite sheet PNG (şeffaf arka planlı)")
    cikti = temizle(sor("Çıktı PNG",
                        kisalt(os.path.splitext(sheet)[0] + "_izgara_ref.png")))
    hedef = sayi_sor("Hedeflenen çıktı kenarı (px)", "2048")

    if arac("grid_ref.py", sheet, "-o", cikti, *secenek("--target", hedef)):
        print(f"\n✓ Bitti: {kisalt(cikti)}")
        print("  Bunu karakter referansıyla birlikte Gemini'ye ver —")
        print("  prompt PROMPTS.md'de 3. bölümde.")


def adim_iskelet() -> None:
    """Tarayıcıda iskelet düzenleyiciyi açar."""
    print("\n— İskelet düzenleyici (skeleton_edit.py) —")
    print("  Tarayıcıda açılır; sprite'ı pencereye sürüklersin, iskelet")
    print("  otomatik çıkarılır, eklemleri fareyle düzeltirsin.")
    print("  Otomatik tespitin garantisi yok: cübbeli, dört ayaklı ya da çok")
    print("  küçük figürlerde şaşıyor — düzeltme adımı bu yüzden var.")
    print("  Sarı noktalar türetilmiştir, önce onlara bak.")
    print("\n  Kapatmak için o terminalde Ctrl-C.")
    arac("skeleton_edit.py")


def adim_rig() -> None:
    """Tek kareden kukla kurup yeni pozlar üretir."""
    print("\n— Poz üret (rig_pose.py) —")
    print("  Tek bir karakter karesini parçalara bölüp eklemlerden döndürür.")
    print("  Çıktı nihai sanat DEĞİL: ControlNet'e girecek bir kontrol görüntüsü.")
    print("  İki JSON gerekiyor (elle yazılıyor, örnek dosya repoda yok):")
    print("    --rig : {\"parcalar\": [{\"ad\":…, \"rect\":[x0,y0,x1,y1], \"capa\":[x,y], \"z\":…}]}")
    print("    --poz : {\"pozlar\": [{\"ad\":…, \"parcalar\": {\"<parça adı>\": <derece>, …}}]}")
    if not evet_mi("JSON'lar hazır mı?", False):
        print("  Şema için: tools/rig_pose.py başlığındaki açıklamaya bak.")
        return

    karakter = dosya_sor("Kaynak kare PNG (native, RGBA)")
    rig = yol_sor("rig.json")
    poz = yol_sor("poz.json")
    cikti = temizle(sor("Çıktı klasörü", kisalt(os.path.splitext(karakter)[0] + "_pozlar")))
    onizleme = os.path.join(cikti, "onizleme.png")

    if arac("rig_pose.py", karakter, "--rig", rig, "--poz", poz,
            "-o", cikti, "--onizleme", onizleme):
        print(f"\n✓ Bitti: {kisalt(cikti)}\n  Tüm pozlar yan yana: {kisalt(onizleme)}")


def adim_pixellab() -> None:
    """Tek görselden PixelLab ile tam karakter üretir."""
    print("\n— PixelLab ile karakter üret (pixellab_karakter.py) —")
    print("  Önden bakan tek bir PNG'den idle ve yürüyüş animasyonlarını")
    print("  ürettirip characters/<ad>/ altına kurar. Girdi native çözünürlükte")
    print("  ve şeffaf zeminli olmalı — ham AI çıktısıysa önce 'Pixel art çıkar'.")
    print("  ÜCRETLİ: karakter başına 3-4 generation.")

    gorsel = dosya_sor("Karakter görseli (önden bakan native PNG)")
    tahmin = re.sub(r"[^a-z0-9]", "",
                    os.path.splitext(os.path.basename(gorsel))[0].lower())
    ad = sor("Klasör adı (küçük harf, ASCII)", tahmin or "karakter")
    gosterilen = sor("Ekranda görünecek ad", ad.capitalize())
    tarif = sor("Karakter tarifi (rotasyon için, İngilizce)",
                "full body pixel art character, front view, standing")

    ek: list[str] = []
    # Dört ayaklıda iskelet şablonu değişmek zorunda; iki ayaklıda varsayılan
    # doğru olduğu için soru tek Enter'la geçiliyor.
    if not evet_mi("Karakter iki ayaklı mı (insan/insansı)?", True):
        ek += ["--govde", sor("Gövde tipi (bear/cat/dog/horse/lion)", "cat")]
    if evet_mi("Önizleme GIF'leri de üretilsin mi?", True):
        ek.append("--gif")
    # Maliyeti üretmeden gösterip onay al: geri alınamaz ve ücretli.
    arac("pixellab_karakter.py", gorsel, "--ad", ad, "--dry-run")
    if not evet_mi("Üretilsin mi?", True):
        return

    if arac("pixellab_karakter.py", gorsel, "--ad", ad,
            "--display-name", gosterilen, "--tarif", tarif, *ek):
        print(f"\n✓ Bitti: characters/{ad}/")


def adim_check() -> None:
    """characters/ altındaki her karakteri doğrular."""
    print("\n— Karakterleri doğrula (check-characters.js) —")
    print("  Eksik dosya, bozuk JSON, meta.json ile uyuşmayan sheet ölçüsü;")
    print("  hepsi uygulamada sessizce yanlış çizime yol açıyor.")
    calistir(["node", os.path.join(ARAC, "check-characters.js")])

def adim_palette_reduce() -> None:
    """Karakterin renk paletini gerçek pixel art seviyesine indirir."""
    print("\n— Renk Paletini Küçült (palette_reduce.py) —")
    print("  AI üretimi sprite'ların şişirilmiş renk paletini (binlerce renk)")
    print("  gerçek pixel art paletine (örn: 32-64 renk) indirir.")
    
    # Hedef dosya veya klasörü soruyoruz. palette_reduce.py ikisini de kabul ediyor.
    hedef = yol_sor("Karakter klasörü (örn: characters/g1) veya tek PNG")

    ek: list[str] = []

    # --in-place bayrağı tehlikeli olabileceği için varsayılanı False ('h') yapıyoruz.
    if evet_mi("Dosyaların üzerine doğrudan yazılsın mı (--in-place)?", False):
        ek.append("--in-place")
    else:
        cikis = temizle(sor("Çıktı klasörü", hedef + "_kucultulmus"))
        ek.extend(["--out", cikis])

    # --colors parametresi. Kullanıcı boş geçerse aracın kendi otomatik k-means seçimi devreye girecek.
    renk_sayisi = sayi_sor("Sabit renk sayısı (Boş bırakılırsa hedefe göre otomatik seçilir)")
    if renk_sayisi:
        ek.extend(["--colors", renk_sayisi])

    # Önizleme dökümü. Görsel hata ayıklama için çok faydalı olduğundan varsayılanı True ('e').
    if evet_mi("Önce/sonra karşılaştırması için önizleme PNG'si üretilsin mi?", True):
        onizleme = temizle(sor("Önizleme dosyası yolu", kisalt(hedef + "_onizleme.png")))
        ek.extend(["--preview", onizleme])

    # arac() fonksiyonu, komutu terminale basar ve çalıştırır.
    if arac("palette_reduce.py", hedef, *ek):
        print(f"\n✓ Palet optimizasyonu tamamlandı.")

def adim_test() -> None:
    """Araçların kendi regresyon testleri."""
    print("\n— Araç testleri —")
    for dosya in ("test_pixelart_extract.py", "test_split_sheet.py",
                  "test_pack_sheet.py", "test_grid_ref.py", "test_skeleton.py",
                  "test_pose_dataset.py", "test_veri_kapilari.py",
                  "test_pixellab_karakter.py"):
        if not arac(dosya):
            print(f"\n✗ {dosya} başarısız.")
            return
    print("\n✓ Tüm araç testleri geçti.")


# ---------------------------------------------------------------------------
# Menü
# ---------------------------------------------------------------------------

MENU = [
    ("PixelLab ile karakter üret", "tek görselden, ücretli", adim_pixellab),
    ("Gemini çıktısını sprite sheet'e çevir", "tam boru hattı", akis_tam),
    ("İki görünüşü ayır (önden + sağa bakan)", "iki_gorunus", adim_iki_gorunus),
    ("Pixel art çıkar", "pixelart_extract", adim_extract),
    ("Sheet'i karelere böl", "split_sheet", lambda: adim_split()),
    ("Kareleri hizala/paketle", "pack_sheet", lambda: adim_pack()),
    ("Izgara referansı üret (Gemini için)", "grid_ref", adim_grid_ref),
    ("Renk paletini küçült / optimize et", "palette_reduce", adim_palette_reduce),
    ("İskelet çıkar ve düzelt", "skeleton_edit", adim_iskelet),
    ("Poz üret", "rig_pose", adim_rig),
    ("Karakterleri doğrula", "check-characters", adim_check),
    ("Araç testlerini çalıştır", "test:tools", adim_test),
]


def main() -> int:
    global PY
    PY = yorumlayici()

    while True:
        print("\n" + "=" * 60)
        print("desktop-pet araçları")
        print("=" * 60)
        for i, (baslik, kaynak, _) in enumerate(MENU, 1):
            print(f"  {i}) {baslik:<38s} {kaynak}")
        print("  q) çık")

        try:
            secim = sor("\nSeçim", "q").lower()
        except KeyboardInterrupt:
            print()
            return 0

        if secim in ("q", "çık", "cik", "exit"):
            return 0
        if not secim.isdigit() or not 1 <= int(secim) <= len(MENU):
            print("  geçersiz seçim")
            continue

        try:
            MENU[int(secim) - 1][2]()
        except KeyboardInterrupt:
            print("\n  iptal edildi")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
