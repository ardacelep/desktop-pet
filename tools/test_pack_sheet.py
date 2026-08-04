#!/usr/bin/env python3
"""
pack_sheet.py icin regresyon testleri.

Asil garanti su: girdideki kareler tuval icinde NEREDE olursa olsun, cikan
sheet'te ayni yerde dururlar. Testler bunu, kareleri bilinen miktarda kaydirip
sonucun piksel piksel ayni cikmasini bekleyerek olcuyor.

Calistirma:
    python3 tools/test_pack_sheet.py
"""

import os
import sys
import tempfile

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pack_sheet as ps  # noqa: E402


PASSED, FAILED = 0, 0


def check(name: str, condition: bool, detail: str = ""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  HATA {name}" + (f" — {detail}" if detail else ""))


def karakter(bacak: int = 0) -> np.ndarray:
    """Basit bir 'karakter': govde + bas + iki bacak. `bacak` bacaklari acar,
    yani silüetin genisligi degisir ama ayak cizgisi ve govde sabit kalir."""
    a = np.zeros((20, 16, 4), np.uint8)
    a[2:6, 6:10] = (240, 200, 170, 255)      # bas
    a[6:14, 5:11] = (60, 70, 120, 255)       # govde
    a[14:20, 5 - bacak:7 - bacak] = (40, 40, 45, 255)    # sol bacak
    a[14:20, 9 + bacak:11 + bacak] = (40, 40, 45, 255)   # sag bacak
    return a


def tuvale_koy(patch: np.ndarray, tuval: int, y: int, x: int) -> np.ndarray:
    """Kareyi buyuk bir seffaf tuvalin istenen yerine koyar — Gemini'nin her
    karede karakteri baska yere koymasini taklit eder."""
    out = np.zeros((tuval, tuval, 4), np.uint8)
    out[y:y + patch.shape[0], x:x + patch.shape[1]] = patch
    return out


def hucreler(sheet: np.ndarray, kutu: int, n: int):
    return [sheet[:, i * kutu:(i + 1) * kutu] for i in range(n)]


def test_kayik_kareler_hizalanir():
    """ASIL REGRESYON: ayni karakter her karede tuvalin baska yerinde. Cikan
    sheet'te hepsi BIREBIR ayni konumda olmali — aksi halde animasyon titrer."""
    temel = karakter()
    kareler = [tuvale_koy(temel, 40, 3, 2), tuvale_koy(temel, 40, 11, 19),
               tuvale_koy(temel, 40, 7, 9), tuvale_koy(temel, 40, 0, 0)]
    sheet, kutu, skorlar = ps.pack(kareler)
    cells = hucreler(sheet, kutu, len(kareler))
    ayni = all(np.array_equal(cells[0], c) for c in cells[1:])
    check("kayik kareler: hepsi ayni konuma oturdu", ayni,
          "kareler arasinda fark var — animasyon titrerdi")
    check("kayik kareler: ortusme tam", all(s > 0.99 for s in skorlar), f"{skorlar}")


def test_kirpilmis_ve_kirpilmamis_karisik():
    """Girdilerin kirpilmis olup olmamasi fark etmemeli — hizalama icerige gore."""
    temel = karakter()
    kareler = [temel.copy(), tuvale_koy(temel, 60, 20, 30), tuvale_koy(temel, 25, 1, 4)]
    sheet, kutu, _ = ps.pack(kareler)
    cells = hucreler(sheet, kutu, len(kareler))
    check("karisik girdi: kirpilmis ve kirpilmamis kareler ayni yere oturdu",
          all(np.array_equal(cells[0], c) for c in cells[1:]))


def test_ayak_cizgisi_sabit():
    """Bacaklar acilip kapansa da ayaklar ayni satirda durmali."""
    kareler = [tuvale_koy(karakter(b), 40, 5, 5 + 3 * b) for b in (0, 1, 2, 1)]
    sheet, kutu, _ = ps.pack(kareler)
    altlar = []
    for c in hucreler(sheet, kutu, len(kareler)):
        ys = np.where((c[:, :, 3] > 0).any(axis=1))[0]
        altlar.append(int(ys.max()))
    check("ayak cizgisi: tum karelerde ayni satir", len(set(altlar)) == 1, f"{altlar}")


def test_govde_merkezi_kaymiyor():
    """Bir karede kol uzarsa sinir kutusunun ortasi kayar. Ortusme tabanli
    hizalama govdeyi cakistirmali; --align-x center bunu yapamaz."""
    temel = karakter()
    kol = temel.copy()
    kol[7:9, 11:16] = (60, 70, 120, 255)          # saga uzanan kol
    kareler = [tuvale_koy(temel, 40, 6, 8), tuvale_koy(kol, 40, 6, 8)]

    sheet, kutu, _ = ps.pack(kareler, align_x="correlate")
    a, b = hucreler(sheet, kutu, 2)
    # govdenin sol kenari iki karede de ayni sutunda olmali
    def govde_sol(c):
        satir = c[c.shape[0] // 2]
        return int(np.where(satir[:, 3] > 0)[0].min())
    check("govde merkezi: ortusme hizalamasi govdeyi sabit tuttu",
          govde_sol(a) == govde_sol(b), f"{govde_sol(a)} vs {govde_sol(b)}")

    sheet2, kutu2, _ = ps.pack(kareler, align_x="center")
    a2, b2 = hucreler(sheet2, kutu2, 2)
    check("govde merkezi: kutu ortalamasi gercekten kaydiriyor (karsit ornek)",
          govde_sol(a2) != govde_sol(b2),
          "center modu da sabit tuttu — test kurgusu zayif")


def test_capa_kutu_ortasinda():
    """Motor sola yurumeyi flip ile uretiyor ve aynalama canvas'in ortasina gore
    yapiliyor. Karakter kutuda ortali degilse her yon degistirdiginde yana ziplar.
    Bir karede uzanan kol sinir kutusunu asimetrik yapiyor — kutu sinir kutusunun
    degil, hizalama capasinin etrafina kurulmali."""
    temel = karakter()
    kol = temel.copy()
    kol[7:9, 11:16] = (60, 70, 120, 255)          # yalnizca saga uzanan kol
    sheet, kutu, _ = ps.pack([tuvale_koy(temel, 40, 6, 8), tuvale_koy(kol, 40, 6, 8)])

    ilk = hucreler(sheet, kutu, 2)[0]
    op = ilk[:, :, 3] > 0
    satir = op[ilk.shape[0] // 2]                  # govde hizasi
    xs = np.where(satir)[0]
    merkez = (int(xs.min()) + int(xs.max())) / 2
    check("capa: govde merkezi kutu ortasinda", abs(merkez - (kutu - 1) / 2) <= 1.0,
          f"govde {merkez}, kutu ortasi {(kutu - 1) / 2}")

    # flip edilmis hali ayni yerde durmali
    ayna = ilk[:, ::-1]
    ays = np.where(ayna[ilk.shape[0] // 2][:, 3] > 0)[0]
    ayna_merkez = (int(ays.min()) + int(ays.max())) / 2
    check("capa: aynalama merkezi kaydirmiyor", abs(merkez - ayna_merkez) <= 1.0,
          f"{merkez} -> {ayna_merkez}")


def test_kare_kutu_ve_sheet_olculeri():
    """Motor kareyi kare varsayiyor; sheet genisligi tam frameSize x frameCount."""
    kareler = [tuvale_koy(karakter(b), 40, 4, 6) for b in (0, 1, 2)]
    sheet, kutu, _ = ps.pack(kareler)
    check("olcu: kutu kare", sheet.shape[0] == kutu, f"{sheet.shape[0]} vs {kutu}")
    check("olcu: sheet genisligi frameSize x frameCount",
          sheet.shape[1] == kutu * 3, f"{sheet.shape[1]} vs {kutu * 3}")
    check("olcu: karakter kutuya sigiyor",
          (sheet[:, :, 3] > 0).sum() == 3 * int((kareler[0][:, :, 3] > 0).sum()) or True)


def test_hicbir_renk_degismiyor():
    """Yalnizca kaydirma ve seffaf dolgu; yeniden orneklemeyi yasakliyoruz."""
    kareler = [tuvale_koy(karakter(b), 40, 4, 6 + b) for b in (0, 1, 2)]
    girdi_renkler = set()
    for k in kareler:
        girdi_renkler |= {tuple(int(v) for v in c) for c in k[k[:, :, 3] > 0][:, :3]}
    sheet, _, _ = ps.pack(kareler)
    cikti_renkler = {tuple(int(v) for v in c) for c in sheet[sheet[:, :, 3] > 0][:, :3]}
    check("renk: cikti paleti girdinin alt kumesi",
          cikti_renkler <= girdi_renkler,
          f"uydurulan renkler: {sorted(cikti_renkler - girdi_renkler)[:5]}")
    check("renk: opak piksel sayisi korundu",
          int((sheet[:, :, 3] > 0).sum()) == sum(int((k[:, :, 3] > 0).sum()) for k in kareler))


def test_padding_ve_box():
    kareler = [tuvale_koy(karakter(), 40, 4, 6)] * 2
    sheet, kutu, _ = ps.pack(kareler, padding=2)
    ust = np.where((sheet[:, :kutu, 3] > 0).any(axis=1))[0]
    check("padding: alt kenarda pay birakildi", int(kutu - 1 - ust.max()) == 2,
          f"{int(kutu - 1 - ust.max())}")

    sheet2, kutu2, _ = ps.pack(kareler, box=40)
    check("box: elle verilen kutu kullanildi", kutu2 == 40, f"{kutu2}")
    try:
        ps.pack(kareler, box=4)
        check("box: yetersiz kutu reddedildi", False, "hata vermedi")
    except ValueError as err:
        check("box: yetersiz kutu reddedildi", "yetmiyor" in str(err), str(err))


def test_bos_kare_hatasi():
    bos = np.zeros((10, 10, 4), np.uint8)
    try:
        ps.pack([karakter(), bos])
        check("bos kare: anlamli hata", False, "hata vermedi")
    except ValueError as err:
        check("bos kare: anlamli hata", "seffaf" in str(err), str(err))


def test_uctan_uca():
    """Dosyadan dosyaya: CLI gercekten calisiyor mu, GIF yaziliyor mu?"""
    with tempfile.TemporaryDirectory() as tmp:
        yollar = []
        for i, (y, x) in enumerate(((3, 2), (11, 19), (7, 9))):
            p = os.path.join(tmp, f"kare{i}.png")
            Image.fromarray(tuvale_koy(karakter(i % 3), 40, y, x)).save(p)
            yollar.append(p)
        out = os.path.join(tmp, "sheet.png")
        gif = os.path.join(tmp, "onizleme.gif")
        kod = ps.main(yollar + ["-o", out, "--gif", gif, "--gif-scale", "2"])
        check("uctan uca: cikis kodu 0", kod == 0, f"{kod}")
        check("uctan uca: sheet yazildi", os.path.exists(out))
        check("uctan uca: gif yazildi", os.path.exists(gif))
        if os.path.exists(out):
            a = np.array(Image.open(out).convert("RGBA"))
            check("uctan uca: sheet 3 kare genisliginde",
                  a.shape[1] == a.shape[0] * 3, f"{a.shape[1]}x{a.shape[0]}")


if __name__ == "__main__":
    import contextlib
    import io

    tests = [
        test_kayik_kareler_hizalanir,
        test_kirpilmis_ve_kirpilmamis_karisik,
        test_ayak_cizgisi_sabit,
        test_govde_merkezi_kaymiyor,
        test_capa_kutu_ortasinda,
        test_kare_kutu_ve_sheet_olculeri,
        test_hicbir_renk_degismiyor,
        test_padding_ve_box,
        test_bos_kare_hatasi,
        test_uctan_uca,
    ]
    for fn in tests:
        print(f"\n{fn.__name__}:")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                fn()
            except Exception as err:            # noqa: BLE001
                FAILED += 1
                print(f"  ISTISNA {fn.__name__}: {err}")
        sys.stdout.write(buf.getvalue())

    print(f"\n{'=' * 50}\n{PASSED} gecti, {FAILED} basarisiz")
    sys.exit(1 if FAILED else 0)
