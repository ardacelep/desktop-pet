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
import sys
import tempfile

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pixelart_extract as px  # noqa: E402


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
    check("bosluk: varsayilan (0) hicbir sey yapmiyor",
          (kapali[:, :, 3] == 255).all() and bos == [])


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
        test_local_tones_not_matched_one_to_one,
        test_lattice_covers_full_canvas,
        test_already_native,
        test_cleanup_removes_specks,
        test_noise_floor_measurement,
        test_merge_preserves_edges,
        test_fill_holes_keeps_source_color,
        test_open_enclosed_gaps,
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
