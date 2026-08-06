#!/usr/bin/env python3
"""
pixelart_extract.py icin regresyon testleri.

Yontem: bilinen bir pixel art uretiyoruz, onu Gemini'nin yaptigi gibi buyutup
arkasina dama deseni ciziyoruz, sonra script'ten GERI cikarip ORIJINALLE
PIKSEL PIKSEL karsilastiriyoruz. Boylece "goze iyi geliyor" degil, olculebilir
bir dogruluk elde ediyoruz.

Kritik senaryo: ONDALIKLI olcek (1024/100 = 10.24). Eski script'ler blok boyutunu
tam sayiya yuvarladigi icin hata hucre hucre birikiyordu ve gorselin sag/alt
kenarinda ornekleme komsu hucreye kayiyordu.

Calistirma:
    python3 tools/test_pixelart_extract.py
"""

import os
import subprocess
import sys
import tempfile
import time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pixelart_extract as px  # noqa: E402
from split_sheet import detect_frames as ss_detect  # noqa: E402


PASSED, FAILED = 0, 0


def check(name: str, condition: bool, detail: str = ""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  HATA {name}" + (f" — {detail}" if detail else ""))


def make_sprite(w: int, h: int, seed: int = 0) -> np.ndarray:
    """Duz renkli bloklardan olusan, gercekci bir pixel art taklidi uretir.
    RGB + bool maske dondurur (maske: karakterin oldugu yerler)."""
    rng = np.random.default_rng(seed)
    palette = np.array([
        [26, 26, 30], [60, 58, 70], [120, 100, 80], [210, 170, 140],
        [40, 90, 70], [180, 60, 60], [230, 230, 235], [90, 90, 95],
    ], dtype=np.uint8)

    sprite = np.zeros((h, w, 3), dtype=np.uint8)
    mask = np.zeros((h, w), dtype=bool)

    # govde: ortada dikey bir dikdortgen + birkac rastgele blok
    cx0, cx1 = w // 4, w - w // 4
    cy0, cy1 = h // 8, h - h // 8
    mask[cy0:cy1, cx0:cx1] = True
    for _ in range(12):
        by = rng.integers(cy0, max(cy0 + 1, cy1 - 4))
        bx = rng.integers(1, max(2, w - 5))
        mask[by:by + rng.integers(2, 6), bx:bx + rng.integers(2, 6)] = True

    ys, xs = np.where(mask)
    for y, x in zip(ys, xs):
        sprite[y, x] = palette[(x * 3 + y * 5) % len(palette)]
    return sprite, mask


def render_like_gemini(sprite: np.ndarray, mask: np.ndarray, canvas: int,
                       checker_colors=((255, 255, 255), (225, 225, 225)),
                       checker_cell: int = 6) -> np.ndarray:
    """Sprite'i `canvas` boyutuna ONDALIKLI olcekle buyutur ve seffaf alanlara
    dama deseni cizer — tam olarak Gemini ciktisinin yapisi."""
    h, w = sprite.shape[:2]
    ys = np.minimum((np.arange(canvas) * h // canvas), h - 1)
    xs = np.minimum((np.arange(canvas) * w // canvas), w - 1)

    big = sprite[np.ix_(ys, xs)]
    big_mask = mask[np.ix_(ys, xs)]

    cell_px = max(1, int(round(checker_cell * canvas / max(w, h))))
    yy, xx = np.meshgrid(np.arange(canvas), np.arange(canvas), indexing="ij")
    checker = ((yy // cell_px) + (xx // cell_px)) % 2
    bg = np.where(checker[..., None] == 0,
                  np.array(checker_colors[0], dtype=np.uint8),
                  np.array(checker_colors[1], dtype=np.uint8))
    return np.where(big_mask[..., None], big, bg).astype(np.uint8)


def roundtrip(sprite, mask, canvas, cleanup=False, **kwargs):
    """Render et -> script'ten gecir -> sonucu dondur.

    Temizlik varsayilan olarak KAPALI: bu testler CIKARIMIN (izgara + ornekleme +
    alfa) dogrulugunu olcuyor. Temizlik kasitli olarak kayipli bir adim — sentetik
    sprite'lardaki tek piksellik cikintilari hakli olarak siliyor, bu yuzden acikken
    piksel piksel karsilastirma anlamli olmuyor. Temizlik ayrica test ediliyor."""
    rendered = render_like_gemini(sprite, mask, canvas, **kwargs)
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.png")
        dst = os.path.join(tmp, "out.png")
        Image.fromarray(rendered).save(src)
        px.extract(src, dst, no_crop=True, cleanup=cleanup)
        return np.array(Image.open(dst))


def compare(result, sprite, mask, name):
    """Cikan sonucu orijinal sprite ile piksel piksel karsilastirir."""
    h, w = sprite.shape[:2]
    check(f"{name}: cozunurluk {w}x{h}",
          result.shape[:2] == (h, w), f"cikan {result.shape[1]}x{result.shape[0]}")
    if result.shape[:2] != (h, w):
        return

    got_opaque = result[:, :, 3] > 0
    alpha_match = (got_opaque == mask).mean()
    check(f"{name}: alfa maskesi birebir",
          alpha_match == 1.0, f"{alpha_match:.3%} eslesme")

    both = got_opaque & mask
    color_match = (result[:, :, :3][both] == sprite[both]).all(axis=1).mean()
    check(f"{name}: renkler birebir", color_match == 1.0, f"{color_match:.3%} eslesme")


def test_fractional_scale():
    """ASIL REGRESYON: 100 -> 1024, yani hucre basina 10.24 piksel."""
    sprite, mask = make_sprite(100, 100, seed=1)
    compare(roundtrip(sprite, mask, 1024), sprite, mask, "ondalikli olcek (10.24x)")


def test_integer_scale():
    sprite, mask = make_sprite(64, 64, seed=2)
    compare(roundtrip(sprite, mask, 1024), sprite, mask, "tam sayi olcek (16x)")


def test_non_square():
    sprite, mask = make_sprite(48, 96, seed=3)
    rendered_sprite = sprite
    result = roundtrip(sprite, mask, 768)
    compare(result, rendered_sprite, mask, "kare olmayan (48x96)")


def test_colored_checkerboard():
    """Dama deseni gri degil pembe — kod sabit 'acik gri' varsaymamali."""
    sprite, mask = make_sprite(80, 80, seed=4)
    result = roundtrip(sprite, mask, 1024,
                       checker_colors=((250, 210, 225), (235, 185, 205)))
    compare(result, sprite, mask, "pembe dama deseni")


def test_dark_checkerboard():
    sprite, mask = make_sprite(80, 80, seed=5)
    result = roundtrip(sprite, mask, 1024, checker_colors=((45, 45, 55), (30, 30, 38)))
    compare(result, sprite, mask, "koyu dama deseni")


def test_background_color_collision():
    """BILINEN SINIR (belgeleniyor, gizlenmiyor): karakterin uzerinde dama tonuna
    cok yakin bir renk varsa ve o bolge kenara baglyisa, renk temelli hicbir yontem
    ikisini ayiramaz. Varsayilan tol=3 ile 5 birim uzaktaki renk KORUNMALI; tol
    buyutulunce kaybolmali."""
    # Paletteki (230,230,235), dama tonu (225,225,225)'e 5 birim uzakta — sprite'in
    # geri kalani cesitli renklerde kaliyor ki izgara sinyali bozulmasin.
    sprite, mask = make_sprite(64, 64, seed=9)
    risky = mask & (sprite == np.array([230, 230, 235])).all(axis=2)
    check("renk cakismasi: test kurgusu gecerli", risky.sum() > 0, "riskli piksel yok")

    kept = roundtrip(sprite, mask, 1024)          # varsayilan tol=3
    survived = (kept[:, :, 3] > 0)[risky].mean()
    check("renk cakismasi: tol=3'te riskli renk korunuyor", survived == 1.0,
          f"{survived:.1%} hayatta")

    rendered = render_like_gemini(sprite, mask, 1024)
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "i.png"), os.path.join(tmp, "o.png")
        Image.fromarray(rendered).save(src)
        px.extract(src, dst, no_crop=True, cleanup=False, bg_tol=12)
        eaten = np.array(Image.open(dst))
    eaten_ratio = 1.0 - (eaten[:, :, 3] > 0)[risky].mean()
    check("renk cakismasi: tol=12'de beklendigi gibi yeniyor", eaten_ratio > 0,
          "tol buyutuldugunde bile korunmus — sinir belgelendigi gibi degil")


def test_no_crash_on_unstructured_image():
    """BUG RAPORU 1: izgara bulunamayinca IndexError ile cokuyordu.
    Artik anlamli bir ValueError vermeli."""
    # Duz bir gradyan: komsu sutunlar birbirine cok yakin oldugu icin "buyutulmus"
    # sayilir ve izgara tespiti calisir — ama periyodik yapi yoktur.
    yy, xx = np.meshgrid(np.arange(600), np.arange(600), indexing="ij")
    noise = np.stack([(xx * 255 // 600), (yy * 255 // 600),
                      ((xx + yy) * 255 // 1200)], axis=-1).astype(np.uint8)
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "n.png"), os.path.join(tmp, "o.png")
        Image.fromarray(noise).save(src)
        try:
            px.extract(src, dst)
            check("cokme yok: gurultulu gorselde anlamli hata", False, "hata vermedi")
        except ValueError as err:
            check("cokme yok: gurultulu gorselde anlamli hata",
                  "izgara" in str(err).lower() or "pixel art" in str(err).lower(), str(err))
        except IndexError as err:
            check("cokme yok: gurultulu gorselde anlamli hata", False, f"IndexError: {err}")


def test_fundamental_period_not_divisor():
    """BUG RAPORU 2: gercek periyodun boleni (1/8'i) secilebiliyordu.
    Bolenler de kafese oturdugu icin secim EN BUYUK gecerli periyot olmali."""
    sprite, mask = make_sprite(64, 64, seed=12)
    rendered = render_like_gemini(sprite, mask, 1024)     # gercek periyot 16
    g = px.detect_axis_grid(rendered, axis=1, name="X")
    check("bolen tuzagi: periyot 16 bulundu", abs(g.period - 16.0) < 0.3, f"{g.period:.3f}")
    check("bolen tuzagi: 64 hucre", abs(g.count - 64) <= 1, f"{g.count}")

    av = px.AxisVariance(rendered, 1)
    fundamental = av.alignment_score(16.0)[0]
    divisor = av.alignment_score(8.0)[0]
    double = av.alignment_score(32.0)[0]
    check("bolen tuzagi: bolen de yuksek skor aliyor (bu yuzden en buyugu secilir)",
          divisor > 3, f"{divisor:.1f}")
    check("bolen tuzagi: kat dusuk skor aliyor", double < fundamental / 3,
          f"kat={double:.1f} temel={fundamental:.1f}")


def test_phase_offset_grid():
    """Izgara tuvali tam bolmuyorsa (kenar boslugu varsa) faz sifir degildir.
    Gercek bir ornekte periyot 11.06, faz 6.45 olcuuldu; faz sifir varsayilirsa
    goruntu tamamen yanlis cozunuyordu."""
    sprite, mask = make_sprite(50, 50, seed=13)
    inner = render_like_gemini(sprite, mask, 800)
    canvas = np.zeros((1024, 1024, 3), np.uint8)
    yy, xx = np.meshgrid(np.arange(1024), np.arange(1024), indexing="ij")
    checker = ((yy // 32) + (xx // 32)) % 2
    canvas[:] = np.where(checker[..., None] == 0,
                         np.array([255, 255, 255], np.uint8),
                         np.array([225, 225, 225], np.uint8))
    off_y, off_x = 53, 37                      # izgarayi kasitli olarak kaydir
    canvas[off_y:off_y + 800, off_x:off_x + 800] = inner

    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "p.png"), os.path.join(tmp, "o.png")
        Image.fromarray(canvas).save(src)
        px.extract(src, dst, cleanup=False)
        out = np.array(Image.open(dst))

    # 800/50 = 16px hucre; kirpilmis cikti sprite'in dolu bolgesi kadar olmali
    ys, xs = np.where(mask)
    expected = (int(ys.max() - ys.min() + 1), int(xs.max() - xs.min() + 1))
    check("faz kaymasi: yukseklik dogru", abs(out.shape[0] - expected[0]) <= 1,
          f"cikan {out.shape[0]}, beklenen {expected[0]}")
    check("faz kaymasi: genislik dogru", abs(out.shape[1] - expected[1]) <= 1,
          f"cikan {out.shape[1]}, beklenen {expected[1]}")


def test_gradient_checkerboard():
    """Dama deseninin tonu goruntu boyunca kayabiliyor (olculen: ustte 229/253,
    altta 203/243). Tek bir global ton listesi bunu kaciriyor ve alt bolgede arka
    plan silinmeden kaliyordu."""
    sprite, mask = make_sprite(60, 60, seed=14)
    rendered = render_like_gemini(sprite, mask, 960).astype(np.int16)
    fade = np.linspace(0, -30, rendered.shape[0]).astype(np.int16)[:, None, None]
    background = ~np.repeat(np.repeat(mask, 16, 0), 16, 1)
    rendered = np.where(background[..., None], np.clip(rendered + fade, 0, 255), rendered)

    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "g.png"), os.path.join(tmp, "o.png")
        Image.fromarray(rendered.astype(np.uint8)).save(src)
        px.extract(src, dst, no_crop=True, cleanup=False)
        out = np.array(Image.open(dst))

    if out.shape[:2] != mask.shape:
        check("gradyanli dama: cozunurluk", False, f"{out.shape[1]}x{out.shape[0]}")
        return
    leftover = ((out[:, :, 3] > 0) & ~mask).sum()
    check("gradyanli dama: arka plan tamamen silindi", leftover == 0,
          f"{int(leftover)} piksel kaldi")


def test_tone_band_touching_character():
    """BUG RAPORU 3: ton kaymasi MONOTON olmak zorunda degil — olculen gorselde
    dama tonu goruntunun ortasindaki bir bantta 231'den 203'e inip tekrar
    yukseliyordu. Kalinti karakterin koluna degdigi icin "kopuk parca" temizligi
    de onu yakalayamiyor, ekranda ince yatay bir cizgi olarak kaliyordu."""
    sprite, mask = make_sprite(60, 60, seed=15)
    rendered = render_like_gemini(sprite, mask, 960).astype(np.int16)

    # ortada bir bant: arka plan 28 birim koyulasip geri aciliyor
    rows = np.arange(rendered.shape[0])
    dip = -28.0 * np.exp(-((rows - rendered.shape[0] * 0.55) ** 2) / (2 * 60.0 ** 2))
    background = ~np.repeat(np.repeat(mask, 16, 0), 16, 1)
    rendered = np.where(background[..., None],
                        np.clip(rendered + dip.astype(np.int16)[:, None, None], 0, 255),
                        rendered)

    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "b.png"), os.path.join(tmp, "o.png")
        Image.fromarray(rendered.astype(np.uint8)).save(src)
        px.extract(src, dst, no_crop=True, cleanup=False)
        out = np.array(Image.open(dst))

    if out.shape[:2] != mask.shape:
        check("ton banti: cozunurluk", False, f"{out.shape[1]}x{out.shape[0]}")
        return
    opaque = out[:, :, 3] > 0
    check("ton banti: arka plan tamamen silindi", (opaque & ~mask).sum() == 0,
          f"{int((opaque & ~mask).sum())} piksel kaldi")

    # Bant, paletteki (230,230,235)'i dama tonuyla BIREBIR ayni hale getirdigi
    # yerlerde onu yer — bu kacinilmaz ve test_background_color_collision'da
    # belgelenen sinirin ta kendisi. Geri kalan her sey korunmali.
    risky = (sprite == np.array([230, 230, 235])).all(axis=2)
    lost = int((mask & ~opaque & ~risky).sum())
    check("ton banti: karakter yenmedi (bilinen renk cakismasi disinda)", lost == 0,
          f"{lost} piksel kayboldu")


def test_local_tones_not_matched_one_to_one():
    """Kaymis ACIK ton, global KOYU tona kaymis koyu tondan daha yakin olabilir
    (olculen: acik 241 -> global koyu 231'e 10, koyu 207 -> 231'e 24 uzak).
    Adaylari global tonlara tek tek eslemek bu durumda ikisini de ayni tona atayip
    diger tonu bosta birakiyordu; o satirda arka planin yarisi opak kaliyordu."""
    band = np.zeros((12, 40, 3), np.uint8)
    # dama tonlari 231/253 iken bu seritte 207/241'e kaymis durumda

    yy, xx = np.meshgrid(np.arange(12), np.arange(40), indexing="ij")
    band[:] = np.where((((yy // 3) + (xx // 3)) % 2)[..., None] == 0,
                       np.array([207, 207, 207], np.uint8),
                       np.array([241, 241, 241], np.uint8))
    tones = [(231, 231, 231), (253, 253, 253)]
    field = px.BackgroundToneField(band, tones)
    worst = int(field.distance.max())
    check("yerel ton: kaymis ton cifti birlikte yakalandi", worst <= 4,
          f"en kotu sapma {worst} (tek tek esleme yapilsaydi ~26 olurdu)")


def test_noisy_checker_tone_detection():
    """Kanal basina BAGIMSIZ +/-1 gurultu tek bir dama tonunu (252,253,253),
    (252,252,253), (252,252,254)... gibi onlarca ayri renge dagitiyor. Birebir
    renk sayan tespit hicbirini %15 paya ulastiramayip BOS ton listesi donuyor
    ve arka plan hic silinmiyordu — hem de sessizce."""
    rng = np.random.default_rng(21)
    sprite, mask = make_sprite(60, 60, seed=17)
    rendered = render_like_gemini(sprite, mask, 960).astype(np.int16)
    background = ~np.repeat(np.repeat(mask, 16, 0), 16, 1)
    rendered = np.where(background[..., None],
                        np.clip(rendered + rng.integers(-1, 2, rendered.shape), 0, 255),
                        rendered).astype(np.uint8)

    small = px.downsample_by_mode(rendered, *px.detect_grid(rendered))
    tones = px.detect_background_tones(small)
    check("gurultulu dama: ton tespiti bos donmedi", len(tones) > 0,
          "hicbir ton bulunamadi — arka plan silinmeden kalirdi")
    if not tones:
        return

    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "n.png"), os.path.join(tmp, "o.png")
        Image.fromarray(rendered).save(src)
        px.extract(src, dst, no_crop=True, cleanup=False)
        out = np.array(Image.open(dst))
    if out.shape[:2] != mask.shape:
        check("gurultulu dama: cozunurluk", False, f"{out.shape[1]}x{out.shape[0]}")
        return
    kalan = int(((out[:, :, 3] > 0) & ~mask).sum())
    check("gurultulu dama: arka plan silindi", kalan <= 2, f"{kalan} piksel kaldi")


def test_lattice_covers_full_canvas():
    """Faz ne olursa olsun kafes tuvalin tamamini kaplamali. Aksi halde faz arayan
    optimizasyon kapsamayi kucultmeyi 'iyilesme' saniyordu."""
    for phase in (0.0, 3.7, 9.9, -4.2):
        edges = px.lattice_edges(10.24, phase, 1024)
        check(f"kafes kapsama (faz {phase}): sol kenar",
              edges[0] <= 0.6 * 10.24, f"{edges[0]:.2f}")
        check(f"kafes kapsama (faz {phase}): sag kenar",
              edges[-1] >= 1024 - 0.6 * 10.24, f"{edges[-1]:.2f}")


def test_already_native():
    """Zaten native bir dosya verilirse izgara uydurmamali."""
    sprite, mask = make_sprite(60, 60, seed=6)
    rgb = np.where(mask[..., None], sprite, np.array([255, 255, 255], np.uint8))
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "n.png"), os.path.join(tmp, "o.png")
        Image.fromarray(rgb.astype(np.uint8)).save(src)
        px.extract(src, dst, no_crop=True)
        out = np.array(Image.open(dst))
    check("zaten native: boyut korunuyor", out.shape[:2] == (60, 60),
          f"cikan {out.shape[1]}x{out.shape[0]}")


def test_reencoded_still_looks_upscaled():
    """Agir yeniden kodlanmis bir render hala "buyutulmus" sayilmali.

    Gercek hata buydu: sikistirma gurultusu her satira sabit bir taban ekleyince
    medyan/ortalama orani 1'e kayiyor ve gorsel "zaten native" saniliyordu. 5632x704
    bir sheet bu yuzden hic indirgenmeden, 33 bin renkle kaydedildi. Burada ayni
    mekanizma sentetik olarak uretiliyor: buyutulmus bir render'a artan siddette
    gurultu ekleniyor, siniflandirma her seviyede "buyutulmus" kalmali."""
    sprite, mask = make_sprite(64, 64, seed=11)
    base = render_like_gemini(sprite, mask, 704)
    rng = np.random.default_rng(3)
    for sigma in (0, 2, 4, 6, 8):
        noisy = np.clip(base.astype(np.float32) + rng.normal(0, sigma, base.shape),
                        0, 255).astype(np.uint8)
        ratio = max(px.line_diff_shape(noisy))
        check(f"gurultulu render (sigma={sigma}) buyutulmus sayiliyor",
              not px.looks_already_native(noisy), f"oran {ratio:.3f}")


def test_shape_ratio_separation():
    """Bicim orani, iki sinifi belirgin bir boslukla ayirmali.

    Esik (0.7) tek bir dosyaya gore degil, olculen bosluga gore secildi; bu test
    boslugun kapanmadigini korur. Ayrica MAX indirgemesini sabitler: native bir
    sprite sheet'te kareler arasi bos seritler yuzunden X orani 0'a duser, o yuzden
    min() ya da "iki eksen birden" kurali kullanilamaz."""
    sprite, mask = make_sprite(64, 64, seed=12)

    # native: sprite'i bos seritli bir sheet'e diz (kareler arasi bosluk var)
    sheet = np.full((64, 64 * 4, 3), 255, np.uint8)
    for i in range(4):
        sheet[:, i * 64:i * 64 + 64] = np.where(mask[..., None], sprite, 255)
    sheet[:, 64 - 8:64] = 255                      # aradaki bos serit
    rx, ry = px.line_diff_shape(sheet)
    check("native sheet: bir eksen bos kalsa da native sayiliyor",
          px.looks_already_native(sheet), f"oranlar ({rx:.3f}, {ry:.3f})")
    check("native sheet: max indirgemesi sart (min() cok dusuk)",
          min(rx, ry) < max(rx, ry), f"({rx:.3f}, {ry:.3f})")

    rendered = render_like_gemini(sprite, mask, 704)
    up = max(px.line_diff_shape(rendered))
    nat = max(px.line_diff_shape(sheet))
    check("buyutulmus ile native arasinda >=0.15 bosluk var",
          nat - up >= 0.15, f"buyutulmus {up:.3f}, native {nat:.3f}")


def test_alignment_score_bounded_on_native():
    """Zaten native bir gorselde hicbir periyot "mukemmel izgara" gibi gorunmemeli.

    Hucrelerin ic bolgesi iki yandan 1'er px kirpildigi icin periyot ~4'un altinda
    ic bolge TEK piksele duser; tek piksellik bir bolgenin varyansi tanimi geregi
    sifirdir, yani `alignment_score` sifira bolmeye yaklasip patlar. Olculen ornek:
    bu koruma yokken zaten native olan dosyalar periyot ~4.1'de 1.3e10'a varan
    oranlar aliyordu (gercek dosyalarda 1.6e9). Boyle bir skor, izgara aramasinin
    anlamsiz bir periyoda kilitlenmesi demek."""
    sprite, mask = make_sprite(88, 88, seed=21)
    native = np.where(mask[..., None], sprite,
                      np.array([255, 255, 255], np.uint8)).astype(np.uint8)

    # 1) Olculemeyecek kadar kucuk periyotlar sessizce "0 varyans" degil, inf donmeli
    av = px.AxisVariance(native, axis=1)
    for period in (3.2, 3.5, 3.8):
        phases = np.linspace(0, period, 24, endpoint=False)
        worst = min(av.variance(period, float(ph)) for ph in phases)
        check(f"periyot {period}: ic bolge 1px'e dustugunde olcum reddediliyor",
              not np.isfinite(worst), f"en iyi varyans {worst:.4g}")

    # 2) Ince tarama boyunca skor sinirli kalmali. quality = min(1, oran/20) oldugu
    #    icin 20 "tam guvenli izgara" demek; native bir gorsel oraya yaklasmamali.
    best = 0.0
    for axis in (1, 0):
        av = px.AxisVariance(native, axis)
        for period in np.arange(3.2, native.shape[1] / 8.0, 0.02):
            ratio = av.alignment_score(float(period))[0]
            if np.isfinite(ratio):
                best = max(best, ratio)
    check("native gorselde hizalama skoru sinirli kaliyor", best < 20.0,
          f"en yuksek oran {best:.4g}")

    # 3) Karsit ornek: koruma gercek izgara tespitini korelemedi mi?
    rendered = render_like_gemini(*make_sprite(64, 64, seed=21), 704)   # periyot 11.0
    true_ratio = px.AxisVariance(rendered, axis=1).alignment_score(11.0)[0]
    check("gercek periyotta skor hala cok yuksek", true_ratio >= 20.0,
          f"periyot 11.0'da oran {true_ratio:.4g}")


def test_grid_detection_precision():
    """Izgara tespiti dogrudan: periyot ve hucre sayisi tam mi?"""
    sprite, mask = make_sprite(100, 100, seed=7)
    rendered = render_like_gemini(sprite, mask, 1024)
    gx = px.detect_axis_grid(rendered, axis=1, name="X")
    gy = px.detect_axis_grid(rendered, axis=0, name="Y")
    check("izgara: periyot 10.24 (+/-0.02)", abs(gx.period - 10.24) < 0.02,
          f"{gx.period:.4f}")
    check("izgara: 100x100 hucre", (gx.count, gy.count) == (100, 100),
          f"{gx.count}x{gy.count}")


def test_cleanup_removes_specks():
    """Temizlik acikken: arka plan artigi bir leke gercekten siliniyor mu?"""
    sprite, mask = make_sprite(80, 80, seed=8)
    rendered = render_like_gemini(sprite, mask, 1024)
    # govdeden uzakta, tek hucrelik yabanci bir nokta enjekte et (12.8px'lik hucre)
    rendered[3 * 128:3 * 128 + 13, 1 * 128:1 * 128 + 13] = (255, 0, 0)
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "i.png"), os.path.join(tmp, "o.png")
        Image.fromarray(rendered).save(src)
        px.extract(src, dst, no_crop=True, cleanup=False)
        raw = np.array(Image.open(dst))
        px.extract(src, dst, no_crop=True, cleanup=True)
        cleaned = np.array(Image.open(dst))
    red_raw = ((raw[:, :, 0] > 200) & (raw[:, :, 1] < 60) & (raw[:, :, 3] > 0)).sum()
    red_clean = ((cleaned[:, :, 0] > 200) & (cleaned[:, :, 1] < 60) & (cleaned[:, :, 3] > 0)).sum()
    check("temizlik: leke ham cikarimda var", red_raw > 0, f"{red_raw} piksel")
    check("temizlik: leke temizlikte silindi", red_clean == 0, f"{red_clean} piksel kaldi")


def test_noise_floor_measurement():
    """Bilinen buyuklukte gurultu enjekte edip, olcumun onu dogru yakaladigini ve
    onerdigi toleransin kasitli tonal adimin ALTINDA kaldigini dogrular."""
    rng = np.random.default_rng(11)
    rgba = np.zeros((40, 40, 4), np.uint8)
    rgba[5:35, 5:35, 3] = 255
    body = np.zeros((30, 30, 3), np.int16)
    body[:, :] = (120, 120, 130)
    body[:, 15:] = (160, 160, 170)          # 40 birimlik kasitli tonal adim
    body += rng.integers(-1, 2, body.shape)  # +/-1 gurultu
    rgba[5:35, 5:35, :3] = np.clip(body, 0, 255).astype(np.uint8)

    n = px.measure_noise_floor(rgba)
    check("gurultu olcumu: guvenilir sayilabildi", n["reliable"])
    if not n["reliable"]:
        return
    check("gurultu olcumu: enjekte edilen +/-1 dogru yakalandi",
          n["jitter_p95"] <= 3, f"p95={n['jitter_p95']:.1f}")
    check("gurultu olcumu: onerilen tolerans tonal adimin cok altinda",
          2 <= n["recommended_merge_tol"] <= 10, f"tol={n['recommended_merge_tol']}")

    # onerilen toleransla birlestirme tonal adimi BOZMAMALI
    merged = px.merge_near_colors(rgba.copy(), n["recommended_merge_tol"])
    step = int(np.abs(merged[20, 19, :3].astype(int) - merged[20, 20, :3].astype(int)).max())
    check("gurultu olcumu: onerilen tolerans tonal adimi koruyor", step >= 35, f"{step}")


def test_merge_preserves_edges():
    """Palet birlestirme yuksek kontrastli gecisleri bozmamali."""
    rgba = np.zeros((20, 20, 4), np.uint8)
    rgba[:, :, 3] = 255
    rgba[:, :10, :3] = (30, 30, 35)
    rgba[:, 10:, :3] = (220, 215, 210)          # 190 birimlik kontur benzeri gecis
    merged = px.merge_near_colors(rgba.copy(), 16)
    contrast = int(np.abs(merged[0, 9, :3].astype(int) - merged[0, 10, :3].astype(int)).max())
    check("merge: yuksek kontrastli gecis korunuyor", contrast >= 180, f"{contrast}")


def test_fill_holes_keeps_source_color():
    """Delik doldurma renk UYDURMAMALI. Onceki surum komsularin ortalamasini
    yaziyordu ve olculen bir ornekte beyaz (255,255,255) bir ayakkabi pikselini
    (115,115,117) ile boyuyordu — kaynakta boyle bir renk yok."""
    rgba = np.zeros((7, 7, 4), np.uint8)
    rgba[:, :] = (10, 20, 30, 255)
    rgba[3, 3] = (200, 50, 60, 0)          # ic delik; RGB hala kaynaktaki deger
    filled = px.fill_interior_holes(rgba.copy(), max_size=4)
    check("delik doldurma: alfa geri acildi", filled[3, 3, 3] == 255)
    check("delik doldurma: kaynak rengi korundu",
          tuple(filled[3, 3, :3]) == (200, 50, 60), f"{tuple(filled[3,3,:3])}")


def test_open_enclosed_gaps():
    """Kolla govde arasinda kalan, dama renginde kucuk adaciklar acilabilmeli;
    ama daha buyuk bir acik renkli parcanin ucu olan adaciklar (ayakkabinin beyaz
    tabani gibi) korunmali."""
    small = np.zeros((15, 15, 3), np.uint8)
    small[:, :] = (30, 30, 30)
    small[7:10, 7] = (225, 225, 225)       # yalitik bosluk — acilmali
    small[7:9, 11] = (225, 225, 225)       # ayni renkte capraz komsusu var —
    small[9, 12] = (225, 225, 225)         # ikisi de korunmali
    field = px.BackgroundToneField(small, [(225, 225, 225)])
    rgba = np.dstack([small, np.full((15, 15), 255, np.uint8)])

    opened, silinen = px.open_enclosed_gaps(rgba.copy(), field, tol=3, max_size=4)
    check("bosluk: yalitik adacik acildi", (opened[7:10, 7, 3] == 0).all(),
          f"{opened[7:10,7,3].tolist()}")
    check("bosluk: ayni renkte komsusu olan adacik korundu",
          (opened[7:9, 11, 3] == 255).all() and opened[9, 12, 3] == 255)
    check("bosluk: rapor tek adacik iceriyor", len(silinen) == 1, f"{silinen}")

    kucuk, _ = px.open_enclosed_gaps(rgba.copy(), field, tol=3, max_size=2)
    check("bosluk: boyut siniri asilirsa dokunulmuyor",
          (kucuk[7:10, 7, 3] == 255).all())

    kapali, bos = px.open_enclosed_gaps(rgba.copy(), field, tol=3, max_size=0)
    check("bosluk: duz adacik, boyut siniri yoksa dokunulmuyor",
          (kapali[:, :, 3] == 255).all() and bos == [])


def _yarik_ve_vurgu(tonlar=((225, 225, 225), (255, 255, 255))):
    """Silüetin icinde iki tane iki-tonlu adacik: biri YARIK (uzun/ince), digeri
    KOMPAKT vurgu. Ikisi de ayni renkleri tasir — ayirt eden tek sey bicim."""
    small = np.zeros((30, 24, 3), np.uint8)
    small[:, :] = (30, 30, 30)
    for i in range(16):                       # yarik: 2x16, dama gibi donusumlu
        small[6 + i, 5:7] = tonlar[i % 2]
    for i in range(3):                        # vurgu: 3x3, ayni iki ton
        small[10 + i, 15:18] = tonlar[i % 2]
    field = px.BackgroundToneField(small, list(tonlar))
    rgba = np.dstack([small, np.full((30, 24), 255, np.uint8)])
    return small, field, rgba


def test_patterned_gap_vs_compact_highlight():
    """Kolla govde arasindaki dama YARIGI otomatik acilmali; ayni renkleri tasiyan
    KOMPAKT bir vurgu (goz aki + iris) korunmali.

    Yalnizca renge bakan bir olcut ikisini ayiramaz: olculen bir portrede gozluk
    ardindaki goz akilari da iki dama tonunu birden tasiyordu (beyaz aki + gri
    iris, yayilim 36-41, tol 18) ve dordu birden siliniyordu. Ayiran sey BICIM —
    olculen gercek yariklar uzunluk^2/alan = 4.8 / 5.8 / 14.3, gozler 1.3-1.5."""
    _, field, rgba = _yarik_ve_vurgu()

    acik, silinen = px.open_enclosed_gaps(rgba.copy(), field, tol=6, max_size=0)
    check("yarik: uzun/ince dama cebi otomatik acildi",
          (acik[6:22, 5:7, 3] == 0).all(), f"{acik[6:22,5:7,3].tolist()}")
    check("yarik: kompakt vurgu (goz aki) korundu",
          (acik[10:13, 15:18, 3] == 255).all(), f"{acik[10:13,15:18,3].tolist()}")
    check("yarik: rapor desenli olarak isaretlendi",
          len(silinen) == 1 and silinen[0][4] is True, f"{silinen}")

    kapali, bos = px.open_enclosed_gaps(rgba.copy(), field, tol=6, max_size=0,
                                        auto_patterned=False)
    check("yarik: auto_patterned=False iken hicbir sey yapilmiyor",
          (kapali[:, :, 3] == 255).all() and bos == [])


def test_gap_needs_both_pattern_and_shape():
    """Iki sart da gerekli: DUZ renkli uzun bir serit ve DESENLI kompakt bir leke
    otomatik yolda silinmemeli."""
    small = np.zeros((30, 24, 3), np.uint8)
    small[:, :] = (30, 30, 30)
    small[6:22, 5:7] = (225, 225, 225)        # uzun ama TEK renk
    field = px.BackgroundToneField(small, [(225, 225, 225), (255, 255, 255)])
    rgba = np.dstack([small, np.full((30, 24), 255, np.uint8)])
    acik, _ = px.open_enclosed_gaps(rgba.copy(), field, tol=6, max_size=0)
    check("yarik: duz renkli serit otomatik silinmiyor",
          (acik[6:22, 5:7, 3] == 255).all())

    # kisa (5 pikselin altinda) desenli bir cizgi de otomatik yola girmemeli
    small2 = np.zeros((20, 20, 3), np.uint8)
    small2[:, :] = (30, 30, 30)
    small2[8, 9] = (225, 225, 225)
    small2[9, 9] = (255, 255, 255)
    small2[10, 9] = (225, 225, 225)
    field2 = px.BackgroundToneField(small2, [(225, 225, 225), (255, 255, 255)])
    rgba2 = np.dstack([small2, np.full((20, 20), 255, np.uint8)])
    acik2, _ = px.open_enclosed_gaps(rgba2.copy(), field2, tol=6, max_size=0)
    check("yarik: 5 pikselden kisa desenli cizgi otomatik silinmiyor",
          (acik2[8:11, 9, 3] == 255).all(), f"{acik2[8:11,9,3].tolist()}")


def test_singleton_keeps_supported_detail():
    """Kaynakta karsiligi olan tek piksel korunmali, artefakt temizlenmeli.

    Olcut ("tek piksel + komsularindan farkli renk") tek basina gercek detayi da
    artefakti da ayni sekilde tanimliyor. Olculen bir portrede gozun aki
    (254,245,228) tam da boyle tek bir piksel oldugu icin komsu konturun rengiyle
    (50,21,15) boyaniyor, yuz kapali gozlu cikiyordu."""
    rgba = np.zeros((5, 5, 4), np.uint8)
    rgba[:, :] = (10, 10, 10, 255)
    rgba[2, 1] = (254, 245, 228, 255)        # kaynakta var — goz aki
    rgba[2, 3] = (254, 245, 228, 255)        # kaynakta yok — ornekleme artefakti

    destek = np.ones((5, 5), np.float32)
    destek[2, 1] = 0.97
    destek[2, 3] = 0.21

    ham = px.remove_isolated_singletons(rgba.copy())
    check("singleton: destek verilmezse ikisi de boyaniyor (eski davranis)",
          tuple(ham[2, 1, :3]) == (10, 10, 10) and tuple(ham[2, 3, :3]) == (10, 10, 10))

    korunan = px.remove_isolated_singletons(rgba.copy(), support=destek)
    check("singleton: kaynakta karsiligi olan detay korundu",
          tuple(korunan[2, 1, :3]) == (254, 245, 228), f"{tuple(korunan[2,1,:3])}")
    check("singleton: desteksiz artefakt yine temizlendi",
          tuple(korunan[2, 3, :3]) == (10, 10, 10), f"{tuple(korunan[2,3,:3])}")


def test_cell_support_measures_source():
    """cell_support, secilen rengin KAYNAK hucresindeki payini olcmeli."""
    arr = np.zeros((20, 20, 3), np.uint8)
    arr[:, :] = (10, 10, 10)
    arr[0:10, 0:10] = (200, 50, 60)          # (0,0) hucresi tamamen tek renk
    arr[10:20, 0:5] = (200, 50, 60)          # (1,0) hucresinin yarisi
    g = px.AxisGrid(period=10.0, phase=0.0, count=2, quality=1.0)
    small = np.array([[(200, 50, 60), (10, 10, 10)],
                      [(200, 50, 60), (10, 10, 10)]], dtype=np.uint8)
    destek = px.cell_support(arr, g, g, small)
    check("cell_support: tek renkli hucre 1.0", destek[0, 0] == 1.0, f"{destek[0,0]}")
    check("cell_support: yarisi baska renk olan hucre dusuk",
          destek[1, 0] < 0.7, f"{destek[1,0]}")


def test_single_pixel_highlight_survives_pipeline():
    """UCTAN UCA: kaynakta tek piksellik parlak bir vurgu, tum temizlikten sonra
    hala yerinde ve DOGRU RENKTE olmali."""
    sprite, mask = make_sprite(60, 60, seed=11)
    sprite[30, 30] = (254, 245, 228)         # koyu govdenin ortasinda tek vurgu
    mask[29:32, 29:32] = True
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                sprite[30 + dy, 30 + dx] = (26, 26, 30)

    rendered = render_like_gemini(sprite, mask, 1024)
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "in.png"), os.path.join(tmp, "out.png")
        Image.fromarray(rendered).save(src)
        px.extract(src, dst, no_crop=True, cleanup=True)
        out = np.array(Image.open(dst))
    check("uctan uca: tek piksellik vurgu temizligi atlatti",
          tuple(out[30, 30, :3]) == (254, 245, 228), f"{tuple(out[30,30,:3])}")


def test_helpers():
    """Yardimci fonksiyonlarin birim testleri."""
    mask = np.zeros((5, 5), bool)
    mask[0:2, 0:2] = True
    mask[4, 4] = True
    _, num = px.label_components(mask, connectivity=4)
    check("label_components: 2 bilesen", num == 2, f"{num}")

    # NOT: 8-yonlu baglantida capraz komsuluk da sayilir, bu yuzden leke govdeden
    # en az 2 piksel uzakta olmali — aksi halde ayni bilesenin parcasi olur
    rgba = np.zeros((7, 7, 4), np.uint8)
    rgba[2:5, 2:5] = (10, 20, 30, 255)
    rgba[0, 0] = (99, 99, 99, 255)          # kopuk leke
    cleaned = px.remove_detached_specks(rgba, max_size=4)
    check("remove_detached_specks: leke silindi", cleaned[0, 0, 3] == 0)
    check("remove_detached_specks: govde duruyor", cleaned[3, 3, 3] == 255)

    rgba2 = np.zeros((5, 5, 4), np.uint8)
    rgba2[:, :] = (10, 20, 30, 255)
    rgba2[2, 2] = (0, 0, 0, 0)               # ic delik
    filled = px.fill_interior_holes(rgba2, max_size=4)
    check("fill_interior_holes: delik dolduruldu", filled[2, 2, 3] == 255)

    rgba3 = np.zeros((3, 3, 4), np.uint8)
    rgba3[:, :] = (10, 10, 10, 255)
    rgba3[1, 1] = (200, 0, 0, 255)           # ic azinlik renk
    fixed = px.remove_isolated_singletons(rgba3)
    check("remove_isolated_singletons: azinlik renk duzeltildi",
          tuple(fixed[1, 1, :3]) == (10, 10, 10), f"{tuple(fixed[1,1,:3])}")

    # (100,100,100) daha sik gectigi icin cipa olmali, (103,101,99) ona yaslanmali
    merged = px.merge_near_colors(
        np.array([[[100, 100, 100, 255], [100, 100, 100, 255],
                   [103, 101, 99, 255], [10, 10, 10, 255]]], np.uint8), tol=8)
    check("merge_near_colors: yakin ton baskin cipaya yaslandi",
          tuple(merged[0, 2, :3]) == (100, 100, 100), f"{tuple(merged[0,2,:3])}")
    check("merge_near_colors: uzak renk korundu",
          tuple(merged[0, 3, :3]) == (10, 10, 10), f"{tuple(merged[0,3,:3])}")


def make_high_cardinality(w: int = 768, h: int = 768, seed: int = 99,
                          cell: int = 4, amp: int = 5, drift: int = 26,
                          blobs: int = 1200) -> np.ndarray:
    """Gemini ciktilarindaki RENK KARDINALITESI patlamasini taklit eder.

    Uc bileseni de gercek dosyadan alindi (5632x704, ~171 bin renk):
      - dama deseni + goruntu boyunca YUMUSAK ton kaymasi,
      - her piksele bagimsiz +/-amp yeniden-kodlama gurultusu (asil kardinalite
        kaynagi: tek bir ton yuzlerce ayri renge dagiliyor),
      - ana silüetten KOPUK, karakter renginde bir suru kucuk leke.

    Ucu birlikte olmali: yalniz boyut buyutmek yetmiyor (5632x704 sentetik dama
    ~3 renkle saniyeler icinde bitiyor), patlamayi kardinalite tetikliyor."""
    rng = np.random.default_rng(seed)
    sw, sh = w // 3, h // 2
    sprite, mask = make_sprite(sw, sh, seed=5)

    yy, xx = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    t0 = np.array([254, 0, 246], np.int16)
    t1 = np.array([179, 3, 176], np.int16)
    img = np.where((((yy // cell) + (xx // cell)) % 2)[..., None] == 0, t0, t1)
    img = img + (drift * np.sin(2 * np.pi * yy / h)
                 * np.cos(3 * np.pi * xx / w)).astype(np.int16)[..., None]

    oy, ox = (h - sh) // 2, (w - sw) // 2
    govde = img[oy:oy + sh, ox:ox + sw]
    img[oy:oy + sh, ox:ox + sw] = np.where(mask[..., None],
                                           sprite.astype(np.int16), govde)

    palet = np.array([[26, 26, 30], [60, 58, 70], [120, 100, 80], [210, 170, 140],
                      [40, 90, 70], [180, 60, 60], [230, 230, 235], [90, 90, 95]],
                     np.int16)
    for _ in range(blobs):
        by, bx = int(rng.integers(2, h - 10)), int(rng.integers(2, w - 10))
        if oy - 10 < by < oy + sh + 10 and ox - 10 < bx < ox + sw + 10:
            continue                     # govdeye degmesin, KOPUK kalsin
        s = int(rng.integers(5, 9))
        img[by:by + s, bx:bx + s] = palet[rng.integers(len(palet))]

    img = img + rng.integers(-amp, amp + 1, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def test_like_ref_geometriyi_dayatiyor():
    """--like-ref, hedef native olcuyu REFERANSTAN okuyup dayatmali.

    Kazanc arama uzayinda: normal tespit periyot ve fazi birlikte ararken,
    periyot disaridan verilince geriye tek boyutlu bir faz aramasi kaliyor.
    Bu, tespitin kil payi kaldigi render'larda geometrinin en azindan DOGRU
    olmasini garanti ediyor (kaynagin kendi kalitesini duzeltmez)."""
    sprite, mask = make_sprite(40, 40, seed=8)
    ref = render_like_gemini(sprite, mask, 480,
                             checker_colors=((255, 0, 255), (192, 0, 192)))
    hedef = render_like_gemini(sprite, mask, 600,
                               checker_colors=((255, 0, 255), (192, 0, 192)))
    with tempfile.TemporaryDirectory() as tmp:
        rp = os.path.join(tmp, "ref.png")
        hp = os.path.join(tmp, "hedef.png")
        op = os.path.join(tmp, "out.png")
        Image.fromarray(ref).save(rp)
        Image.fromarray(hedef).save(hp)

        nw, nh = px.referans_native_olcu(rp)
        check("like-ref: referansin native olcusu okundu", (nw, nh) == (40, 40),
              f"{nw}x{nh}")

        px.extract(hp, op, no_crop=True, cleanup=False, like_ref=rp)
        out = np.array(Image.open(op).convert("RGBA"))
    check("like-ref: cikti referansin olcusunde", out.shape[:2] == (nh, nw),
          f"{out.shape[1]}x{out.shape[0]}, beklenen {nw}x{nh}")


def test_kare_kare_farkli_olcek():
    """REGRESYON: bir Gemini sheet'inde izgara SATIRLARININ her biri farkli
    piksel olceginde cizilmisti (olculdu: 8.67 / ~8.0 / ~7.3 px blok, yani
    karakter 70 / 77 / 83 native piksel). Tum sheet icin tek kafes olmadigi
    icin global tespit haklı olarak reddediyor; tek periyot zorlaninca da
    satirlarin ikisi yanlis orneklenip karakter bozuluyordu.

    `--per-frame` kareleri once ayirip her birinde AYRI kafes ariyor, sonra
    ortak bir native boya indiriyor."""
    kutu, kare = 24, 4
    tuval_h, tuval_w = 400, 1000
    tuval = np.zeros((tuval_h, tuval_w, 3), np.uint8)
    yy, xx = np.meshgrid(np.arange(tuval_h), np.arange(tuval_w), indexing="ij")
    t0 = np.array([255, 0, 255], np.uint8)
    t1 = np.array([192, 0, 192], np.uint8)
    tuval[:] = np.where((((yy // 40) + (xx // 40)) % 2)[..., None] == 0, t0, t1)

    sprite, mask = make_sprite(kutu, kutu, seed=4)
    # Her kare FARKLI olcekte buyutuluyor — asil kusur bu
    olcekler = (6, 7, 8, 9)
    x = 20
    for i in range(kare):
        k = olcekler[i]
        buyuk = np.repeat(np.repeat(sprite, k, 0), k, 1)
        bm = np.repeat(np.repeat(mask, k, 0), k, 1)
        h, w = bm.shape
        alt = tuval[30:30 + h, x:x + w]
        tuval[30:30 + h, x:x + w] = np.where(bm[..., None], buyuk, alt)
        x += w + 30

    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "s.png"), os.path.join(tmp, "o.png")
        Image.fromarray(tuval).save(src)
        try:
            px.extract(src, dst, no_crop=True, cleanup=False, per_frame=True)
        except Exception as err:            # noqa: BLE001
            check("kare kare: cikarim calisti", False, str(err))
            return
        out = np.array(Image.open(dst).convert("RGBA"))

    kutular, _, _ = ss_detect(out)
    check("kare kare: dort kare de bulundu", len(kutular) == kare,
          f"{len(kutular)} kare")
    if len(kutular) != kare:
        return
    boylar = [y1 - y0 for y0, y1, _, _ in kutular]
    check("kare kare: kareler ortak boya indirildi",
          max(boylar) - min(boylar) <= 2, f"boylar {boylar}")


def test_sheet_kareleri_kalinti_sanilmiyor():
    """REGRESYON: sprite SHEET'te kareler birbirinden kopuk oldugu icin
    `remove_background_remnants` karakterlerin hepsini (en buyugu haric) "kopuk
    parca" sayiyor ve gevsek RENK olcutunu onlara da uyguluyordu.

    Olculen gercek vaka: 3x3 izgarali gurultulu bir Gemini ciktisi tolerans 31
    sectirdi, esik tol*3 = 93'e cikti ve o yaricapta karakterin renkleri de arka
    plan gamutuna girdi — 8 karakterin 5'i silindi. Kalinti ile kare arasindaki
    gercek fark BOYUT: kalintilar ince serit, kareler ana siluetle ayni mertebede.
    """
    h, w = 40, 200
    rgba = np.zeros((h, w, 4), np.uint8)
    # Seffaf pikseller RGB'lerini KORUR (background_to_alpha yalnizca alfayi
    # sifirliyor); onaylanmis arka plan gamutu tam da oradan ogreniliyor.
    yy, xx = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    dama = ((yy // 4) + (xx // 4)) % 2
    rgba[:, :, :3] = np.where(dama[..., None] == 0,
                              np.array([255, 0, 255], np.uint8),
                              np.array([192, 0, 192], np.uint8))
    # Bes esit buyuklukte, birbirinden KOPUK "karakter"; rengi damaya yakin
    # tutuluyor ki eski kod onlari kalinti sansin.
    for i in range(5):
        x = 6 + i * 38
        rgba[8:32, x:x + 24] = (200, 40, 200, 255)
    # tek bir ince kalinti seridi — bunun silinmesi BEKLENIYOR
    rgba[36:38, 6:40] = (205, 20, 205, 255)

    tones = [(255, 0, 255), (192, 0, 192)]
    field = px.BackgroundToneField(rgba[:, :, :3].copy(), tones)
    temiz = px.remove_background_remnants(rgba, field, tol=31)

    _, kalan = px.label_components(temiz[:, :, 3] > 0, connectivity=8)
    check("sheet: bes kare de korundu", kalan >= 5,
          f"{kalan} bilesen kaldi — kareler kalinti sanilmis")
    check("sheet: ince kalinti serisi silindi",
          not (temiz[36:38, 6:40, 3] > 0).any(),
          "boyut siniri kalintiyi da koruyor, olcut ise yaramiyor")


def test_gamut_query_is_exact():
    """within_gamut'un iki yolu (dogrudan yayin / RGB kupu) AYNI sonucu vermeli.

    Kup yolu L∞ toplarinin kutu olmasindan, kutu genisletmenin de eksenlere
    ayrilabilmesinden yararlaniyor; bu esdegerlik bozulursa arka plan kalintisi
    temizligi sessizce yanlis pikselleri siler."""
    rng = np.random.default_rng(3)
    gamut = rng.integers(0, 256, (900, 3)).astype(np.int32)
    query = rng.integers(0, 256, (400, 3)).astype(np.int32)
    kaba = np.abs(query[:, None, :] - gamut[None, :, :]).max(axis=2).min(axis=1)
    for radius in (0, 1, 7, 45, 180):
        kup = px._gamut_cube(gamut, radius)
        check(f"gamut kupu yariçap {radius}: yayinla ayni",
              np.array_equal(kup[query[:, 0], query[:, 1], query[:, 2]], kaba <= radius))
        check(f"gamut sorgusu yariçap {radius}: yol secimi sonucu degistirmiyor",
              np.array_equal(px.within_gamut(query, gamut, radius), kaba <= radius))

    check("gamut sorgusu: bos query", px.within_gamut(np.zeros((0, 3), np.int32),
                                                      gamut, 5).shape == (0,))
    check("gamut sorgusu: bos gamut",
          not px.within_gamut(query, np.zeros((0, 3), np.int32), 5).any())


def test_high_cardinality_bounded():
    """Yuksek renk kardinaliteli girdi MAKUL sure/bellek icinde bitmeli.

    Regresyon: `remove_background_remnants` her kopuk parca icin
    `colors x confirmed x 3` boyutunda tek bir gecici dizi ayiriyordu. `confirmed`
    = seffaflastirilmis piksellerin TUM ayri renkleri; temiz girdide bir kac tane,
    sikistirma gurultulu girdide on binlerce. Olculen gercek dosyada 128567 x 71943
    x 3 int32 = 111 GB'lik tek bir istek cikiyordu: surec 4 GB'a sisip takasa
    giriyor, CPU %0.4'te kaliyor ve HIC bitmiyordu. Bu sentetik girdi ayni yoldan
    gecerek fix oncesi 5.7 GB'a ciktigi olculdu.

    Olcum AYRI SUREC'te: (a) takilma testi askiya almasin diye zaman asimi
    uygulanabilsin, (b) tepe bellek yalnizca arac'a ait olsun."""
    sure_butcesi = 60.0        # olculen: ~2.5 sn
    bellek_butcesi = 1.0       # GB; olculen: ~0.32 GB (fix oncesi 5.7 GB)

    img = make_high_cardinality()
    renk = len(np.unique(px.pack_rgb(img)))
    check("yuksek kardinalite: girdi gercekten gurultulu", renk > 15000,
          f"yalnizca {renk} renk — test artik dogru yolu zorlamiyor olabilir")

    olcum = r"""
import resource, sys, os, contextlib, io
sys.path.insert(0, sys.argv[3])
import pixelart_extract as px
with contextlib.redirect_stdout(io.StringIO()):
    px.extract(sys.argv[1], sys.argv[2], no_crop=True)
tepe = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(tepe if sys.platform == "darwin" else tepe * 1024)   # daima bayt
"""
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "hc.png"), os.path.join(tmp, "out.png")
        Image.fromarray(img).save(src)
        basla = time.monotonic()
        try:
            sonuc = subprocess.run(
                [sys.executable, "-c", olcum, src, dst,
                 os.path.dirname(os.path.abspath(__file__))],
                capture_output=True, text=True, timeout=sure_butcesi)
        except subprocess.TimeoutExpired:
            check(f"yuksek kardinalite: {sure_butcesi:.0f} sn icinde bitiyor", False,
                  "zaman asimi — arac yine takiliyor")
            return
        gecen = time.monotonic() - basla

        if sonuc.returncode != 0:
            check("yuksek kardinalite: arac hatasiz bitti", False,
                  (sonuc.stderr or "").strip()[-300:] or f"cikis kodu {sonuc.returncode}")
            return
        check(f"yuksek kardinalite: {sure_butcesi:.0f} sn icinde bitiyor",
              gecen < sure_butcesi, f"{gecen:.1f} sn surdu")

        tepe_gb = int(sonuc.stdout.strip().splitlines()[-1]) / 1e9
        check(f"yuksek kardinalite: tepe bellek < {bellek_butcesi:.1f} GB",
              tepe_gb < bellek_butcesi, f"{tepe_gb:.2f} GB kullandi")
        check("yuksek kardinalite: cikti uretildi", os.path.exists(dst))


if __name__ == "__main__":
    import io
    import contextlib

    tests = [
        test_grid_detection_precision,
        test_fractional_scale,
        test_integer_scale,
        test_non_square,
        test_colored_checkerboard,
        test_dark_checkerboard,
        test_background_color_collision,
        test_no_crash_on_unstructured_image,
        test_fundamental_period_not_divisor,
        test_phase_offset_grid,
        test_gradient_checkerboard,
        test_tone_band_touching_character,
        test_noisy_checker_tone_detection,
        test_local_tones_not_matched_one_to_one,
        test_lattice_covers_full_canvas,
        test_already_native,
        test_reencoded_still_looks_upscaled,
        test_shape_ratio_separation,
        test_alignment_score_bounded_on_native,
        test_cleanup_removes_specks,
        test_noise_floor_measurement,
        test_merge_preserves_edges,
        test_fill_holes_keeps_source_color,
        test_open_enclosed_gaps,
        test_patterned_gap_vs_compact_highlight,
        test_gap_needs_both_pattern_and_shape,
        test_singleton_keeps_supported_detail,
        test_cell_support_measures_source,
        test_single_pixel_highlight_survives_pipeline,
        test_like_ref_geometriyi_dayatiyor,
        test_kare_kare_farkli_olcek,
        test_sheet_kareleri_kalinti_sanilmiyor,
        test_gamut_query_is_exact,
        test_high_cardinality_bounded,
        test_helpers,
    ]
    for fn in tests:
        print(f"\n{fn.__name__}:")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):   # script'in kendi ciktisi test ciktisini bogmasin
            try:
                fn()
            except Exception as err:            # noqa: BLE001
                FAILED += 1
                print(f"  ISTISNA {fn.__name__}: {err}")
        sys.stdout.write(buf.getvalue().replace("Girdi:", "    (girdi:"))

    print(f"\n{'=' * 50}\n{PASSED} gecti, {FAILED} basarisiz")
    sys.exit(1 if FAILED else 0)
