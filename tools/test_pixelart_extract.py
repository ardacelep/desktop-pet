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
        Image.fromarray(rendered, "RGB").save(src)
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
        Image.fromarray(rendered, "RGB").save(src)
        px.extract(src, dst, no_crop=True, cleanup=False, bg_tol=12)
        eaten = np.array(Image.open(dst))
    eaten_ratio = 1.0 - (eaten[:, :, 3] > 0)[risky].mean()
    check("renk cakismasi: tol=12'de beklendigi gibi yeniyor", eaten_ratio > 0,
          "tol buyutuldugunde bile korunmus — sinir belgelendigi gibi degil")


def test_already_native():
    """Zaten native bir dosya verilirse izgara uydurmamali."""
    sprite, mask = make_sprite(60, 60, seed=6)
    rgb = np.where(mask[..., None], sprite, np.array([255, 255, 255], np.uint8))
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "n.png"), os.path.join(tmp, "o.png")
        Image.fromarray(rgb.astype(np.uint8), "RGB").save(src)
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
        Image.fromarray(rendered, "RGB").save(src)
        px.extract(src, dst, no_crop=True, cleanup=False)
        raw = np.array(Image.open(dst))
        px.extract(src, dst, no_crop=True, cleanup=True)
        cleaned = np.array(Image.open(dst))
    red_raw = ((raw[:, :, 0] > 200) & (raw[:, :, 1] < 60) & (raw[:, :, 3] > 0)).sum()
    red_clean = ((cleaned[:, :, 0] > 200) & (cleaned[:, :, 1] < 60) & (cleaned[:, :, 3] > 0)).sum()
    check("temizlik: leke ham cikarimda var", red_raw > 0, f"{red_raw} piksel")
    check("temizlik: leke temizlikte silindi", red_clean == 0, f"{red_clean} piksel kaldi")


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
        test_already_native,
        test_cleanup_removes_specks,
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
