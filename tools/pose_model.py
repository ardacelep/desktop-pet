#!/usr/bin/env python3
"""
pose_model.py — pixel art icin tek kisilik poz modeli (SimCC basligi).

    python3 tools/pose_model.py train _data/poz --holdout faküs
    python3 tools/pose_model.py eval  _data/poz --ckpt _data/poz/model.pt

TASARIM KARARLARI VE NEDENLERI

  DEDEKTOR YOK. Tuvalde tek karakter var ve ortali. PixelLab'e iki karakter
  yan yana verildiginde tek iskelet donup onu ikisine yaydigi olculdu — yani
  onlarin sistemi de boyle. Dedektor kurmak gereksiz karmasiklik; ustelik
  DWPose'un bizde hic ateslememesinin sebebi tam da dedektor asamasi.

  ISI HARITASI DEGIL, SimCC. Isi haritasi tipik olarak 1/4 cozunurlukte
  uretilir; 128x128 girdide bu 32x32, yani 4 piksel yuvarlama. Biz 2 piksel
  ariyoruz. Olculdu (SimCC, ECCV 2022, Tablo 1): 64x64 girdide isi haritasi
  35.9 AP / SimCC 62.8; 128x128'de 57.6 / 70.4. SimCC x ve y'yi ayri ayri
  bin'lere siniflandirdigi icin alt-piksel cozunurluk veriyor ve son-isleme
  gerektirmiyor. Govdemizin son katmani zaten 8x8 — isi haritasi icin
  umutsuzca kaba.

  GOVDE: ILLUSTRASYON on egitimli ResNet50. Chen WACV2022'nin (AGPL-3.0)
  Danbooru-etiketleyici on egitimli govdesi; makale bunun ImageNet'e gore
  %10-20 PDJ kazandirdigini olcmus, yani ON EGITIM ALANI mimariden daha
  belirleyici. Agirlik dosyasinin icindeki `resnet.*` anahtarlari
  torchvision resnet50'ye SIFIR eslesmeyen anahtarla yukleniyor; Detectron2
  ve Lightning gerekmiyor.

  BOLME KARAKTER BAZINDA. Rastgele bolme ayni karakterin artirilmis
  kopyalarini hem egitime hem teste koyar ve sahte yuksek skor uretir.
  Olcmek istedigimiz sey GORULMEMIS CIZIM TARZINA genelleme, o yuzden bir
  karakter tumuyle disarida birakiliyor.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skeleton as sk  # noqa: E402

BOLME = 2          # SimCC alt-piksel bolme carpani: bin = piksel * BOLME
GOVDE_YOLU = os.path.expanduser(
    "~/ComfyUI/models/pose/bizarre/feat_concat_plusdata.safetensors")


def _torch():
    try:
        import torch
        return torch
    except ImportError:
        raise SystemExit(
            "HATA: torch yok. ComfyUI ortamiyla calistirin:\n"
            "  ~/ComfyUI/venv/bin/python tools/pose_model.py ...")


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

def govde_kur(on_egitimli: bool = True):
    """ResNet50'nin layer1-3'u. layer4 YOK: uzamsal cozunurlugu korumak icin
    Chen de orada kesmis (agirlik dosyasinda layer4 anahtari hic yok)."""
    torch = _torch()
    import torch.nn as nn
    from torchvision.models import resnet50

    net = resnet50(weights=None)
    net.layer4 = nn.Identity()
    net.avgpool = nn.Identity()
    net.fc = nn.Identity()

    if on_egitimli:
        if not os.path.exists(GOVDE_YOLU):
            raise SystemExit(
                f"HATA: on egitimli govde yok: {GOVDE_YOLU}\n"
                "Indirmek icin: huggingface_hub ile dreMaz/bizarre-pose-estimator "
                "deposundan feat_concat_plusdata.safetensors")
        from safetensors.torch import load_file
        sd = load_file(GOVDE_YOLU)
        agirlik = {k[len("resnet."):]: v.contiguous() for k, v in sd.items()
                   if k.startswith("resnet.")}
        eksik, fazla = net.load_state_dict(agirlik, strict=False)
        kritik = [k for k in eksik if not k.startswith(("layer4", "fc"))]
        if kritik:
            raise SystemExit(f"HATA: govde yuklenemedi, eksik: {kritik[:5]}")
    return net


class PozModeli:
    """Govde + SimCC basligi. torch modulu, tembel kuruluyor.

    `derinlik` hangi ResNet katmaninin ciktisinin kullanilacagini secer:
      3 -> layer3, 8x8 oznitelik  (varsayilan)
      2 -> layer2, 16x16          (dort kat daha ince uzamsal cozunurluk)
    SimCC uzamsal cozunurluge isi haritasi kadar bagimli degil, ama 8x8 yine
    de cok kaba olabilir; iki secenek de olculebilsin diye acildi."""

    def __new__(cls, tuval: int = 128, eklem: int = 18, on_egitimli: bool = True,
                derinlik: int = 3):
        torch = _torch()
        import torch.nn as nn

        govde = govde_kur(on_egitimli)
        bin_x = bin_y = tuval * BOLME
        kanal = {2: 512, 3: 1024}[derinlik]
        izgara = {2: 16, 3: 8}[derinlik]

        class _Model(nn.Module):
            def __init__(self):
                super().__init__()
                self.govde = govde
                # 1024 kanal -> eklem basina bir oznitelik haritasi
                self.azalt = nn.Sequential(
                    nn.Conv2d(kanal, 256, 1), nn.BatchNorm2d(256), nn.ReLU(inplace=True),
                    nn.Conv2d(256, eklem, 1))
                # SimCC: her eklemin uzamsal haritasi -> iki 1B dagilim
                self.x_bas = nn.Linear(izgara * izgara, bin_x)
                self.y_bas = nn.Linear(izgara * izgara, bin_y)
                self.eklem, self.derinlik = eklem, derinlik

            def forward(self, x):
                h = self.govde.conv1(x); h = self.govde.bn1(h)
                h = self.govde.relu(h); h = self.govde.maxpool(h)
                h = self.govde.layer1(h); h = self.govde.layer2(h)
                if self.derinlik == 3:
                    h = self.govde.layer3(h)                # (B,1024,8,8)
                h = self.azalt(h)                           # (B,K,8,8)
                # flatten DEGIL reshape: govde ciktisi bitisik olmayabiliyor
                # ve view geri gecisde patliyor (MPS'te olculdu).
                d = h.reshape(h.shape[0], h.shape[1], -1)   # (B,K,64)
                return self.x_bas(d), self.y_bas(d)         # (B,K,bin)

        m = _Model()
        m.tuval, m.bin_x, m.bin_y = tuval, bin_x, bin_y
        m.derinlik_secimi = derinlik
        return m


def koordinat_coz(x_log, y_log, tuval: int):
    """Bin dagilimlarindan alt-piksel koordinat (beklenen deger).

    argmax yerine SOFT-ARGMAX: argmax bin cozunurlugune (0.5 piksel)
    yuvarlar, beklenen deger ise dagilimin agirlik merkezini verir ve
    alt-piksel kalir. Zaten SimCC'yi secmemizin sebebi bu cozunurluktu."""
    torch = _torch()
    px = torch.softmax(x_log, dim=-1)
    py = torch.softmax(y_log, dim=-1)
    ix = torch.arange(px.shape[-1], device=px.device, dtype=px.dtype)
    iy = torch.arange(py.shape[-1], device=py.device, dtype=py.dtype)
    return ((px * ix).sum(-1) / BOLME), ((py * iy).sum(-1) / BOLME)


# ---------------------------------------------------------------------------
# Veri
# ---------------------------------------------------------------------------

def veri_oku(kok: str):
    satirlar = []
    with open(os.path.join(kok, "etiketler.jsonl")) as f:
        for s in f:
            satirlar.append(json.loads(s))
    return satirlar


def hedef_dagilim(deger: float, bin_say: int, sigma: float = 2.0):
    """Gauss yumusatilmis hedef. Tek-sicak (one-hot) yerine yumusak hedef,
    cunku komsu bin'ler de neredeyse dogru ve bunu cezalandirmak ogrenmeyi
    yavaslatiyor (SimCC makalesi de etiket yumusatma kullaniyor)."""
    i = np.arange(bin_say, dtype=np.float32)
    g = np.exp(-((i - deger) ** 2) / (2 * sigma ** 2))
    t = g.sum()
    return g / t if t > 0 else g


class Kume:
    def __init__(self, kok, satirlar, tuval=128, siluet=False):
        self.kok, self.satirlar, self.tuval = kok, satirlar, tuval
        # SILUET modu: renk atiliyor, yalnizca alfa maskesi kaliyor.
        # Hipotez, iskeletin zaten siluetten okunabilecegi ve renkten
        # bagimsiz olmanin cizim tarzina genellemeyi kolaylastiracagi.
        # Olculdu (renkle egitilmis modele siluet verildiginde): 0.84 ->
        # 11.99px, yani mevcut model renge cok yasliyor — ama bu siluetin
        # bilgi tasimadigini DEGIL, modelin siluet gormedigini gosterir.
        self.siluet = siluet

    def __len__(self):
        return len(self.satirlar)

    def __getitem__(self, i):
        from PIL import Image
        s = self.satirlar[i]
        im = np.array(Image.open(os.path.join(self.kok, s["gorsel"])).convert("RGBA"))
        if self.siluet:
            # Opak = koyu, seffaf = beyaz. Tek kanal yerine ucu de ayni:
            # govde ImageNet istatistikleriyle normalize edilmis 3 kanal
            # bekliyor ve on egitimli agirliklar oyle ogrenildi.
            m = (im[:, :, 3:4] > 0)
            rgb = np.where(m, 40.0, 255.0).repeat(3, axis=2).astype(np.float32) / 255.0
        else:
            rgb = np.where(im[:, :, 3:4] > 0, im[:, :, :3], 255).astype(np.float32) / 255.0
        x = rgb.transpose(2, 0, 1)
        ort = np.array([0.485, 0.456, 0.406], np.float32).reshape(3, 1, 1)
        std = np.array([0.229, 0.224, 0.225], np.float32).reshape(3, 1, 1)
        # ascontiguousarray SART. numpy'nin ufunc'lari girdinin bellek duzenini
        # koruyor, yani transpose'dan sonraki aritmetik de bitisik OLMAYAN bir
        # dizi uretiyor ve bu np.stack'ten sonra da devam ediyor. Bitisik
        # olmayan girdi grafige yayilip GERI gecisi "view size is not
        # compatible" hatasiyla dusuruyor — hata ileri geciste degil
        # backward'da ciktigi icin kaynagi son derece yaniltici.
        x = np.ascontiguousarray((x - ort) / std, dtype=np.float32)

        b = self.tuval * BOLME
        hx = np.zeros((len(sk.LABELS), b), np.float32)
        hy = np.zeros((len(sk.LABELS), b), np.float32)
        gercek = np.zeros((len(sk.LABELS), 2), np.float32)
        for j, l in enumerate(sk.LABELS):
            kx, ky = s["keypoints"][l]
            gercek[j] = (kx * self.tuval, ky * self.tuval)
            hx[j] = hedef_dagilim(kx * b, b)
            hy[j] = hedef_dagilim(ky * b, b)
        return x, hx, hy, gercek


def toplu(parcalar):
    torch = _torch()
    x = torch.from_numpy(np.stack([p[0] for p in parcalar]))
    hx = torch.from_numpy(np.stack([p[1] for p in parcalar]))
    hy = torch.from_numpy(np.stack([p[2] for p in parcalar]))
    g = torch.from_numpy(np.stack([p[3] for p in parcalar]))
    return x, hx, hy, g


# ---------------------------------------------------------------------------
# Egitim / degerlendirme
# ---------------------------------------------------------------------------

def aygit():
    torch = _torch()
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def hata_px(model, kume, dev, tuval, parti=16):
    torch = _torch()
    model.eval()
    toplam, n = 0.0, 0
    with torch.no_grad():
        for i in range(0, len(kume), parti):
            p = [kume[j] for j in range(i, min(i + parti, len(kume)))]
            x, _, _, g = toplu(p)
            xl, yl = model(x.to(dev))
            px, py = koordinat_coz(xl, yl, tuval)
            tah = torch.stack([px, py], dim=-1).cpu()
            toplam += float(torch.linalg.norm(tah - g, dim=-1).sum())
            n += g.shape[0] * g.shape[1]
    return toplam / max(n, 1)


def egit(kok, holdout, epok, parti, lr, cikti, on_egitimli=True, tuval=128,
         derinlik=3, tohum=0, siluet=False):
    torch = _torch()
    import torch.nn.functional as F

    # SimCC basliklari rastgele ilklendiriliyor; tohumsuz kosuda ayni ayarin
    # iki kosusu farkli sonuc verir ve iki AYARI karsilastirmak imkansizlasir.
    torch.manual_seed(tohum)

    satirlar = veri_oku(kok)
    # holdout="yok" -> URETIM modeli: hicbir sey disarida birakilmiyor.
    # Olcum icin holdout sart (genellemeyi ancak gorulmemis karakter olcer),
    # ama KULLANIM icin tam tersi: bir karakteri disarida birakmak, elimizdeki
    # veriyi bilerek eksik kullanmak demek. GUI'nin ihtiyaci olan sey budur.
    uretim = holdout in ("yok", "none", "")
    if uretim:
        egitim, test = satirlar, []
        print(f"Egitim {len(egitim)} ornek | URETIM MODU — holdout yok, "
              f"genelleme olcumu YAPILAMAZ")
    else:
        egitim = [s for s in satirlar if s["kaynak"].split("/")[0] != holdout]
        test = [s for s in satirlar if s["kaynak"].split("/")[0] == holdout]
        if not test:
            raise SystemExit(
                f"HATA: '{holdout}' veri setinde yok. Mevcut: "
                f"{sorted({s['kaynak'].split('/')[0] for s in satirlar})}. "
                f"Tum veriyle egitmek icin --holdout yok.")
        print(f"Egitim {len(egitim)} ornek | Test (holdout={holdout}) {len(test)} ornek")

    ke, kt = Kume(kok, egitim, tuval, siluet), Kume(kok, test, tuval, siluet)
    dev = aygit()
    model = PozModeli(tuval, len(sk.LABELS), on_egitimli, derinlik).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    plan = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epok)
    print(f"Aygit: {dev}   parametre: {sum(p.numel() for p in model.parameters())/1e6:.1f}M")

    rng = np.random.default_rng(tohum)
    en_iyi, son = float("inf"), float("nan")
    for e in range(epok):
        model.train()
        sira = rng.permutation(len(ke))
        kayip_top, adim, t0 = 0.0, 0, time.time()
        for i in range(0, len(sira), parti):
            p = [ke[int(j)] for j in sira[i:i + parti]]
            x, hx, hy, _ = toplu(p)
            xl, yl = model(x.to(dev))
            kayip = (F.kl_div(F.log_softmax(xl, -1), hx.to(dev), reduction="batchmean")
                     + F.kl_div(F.log_softmax(yl, -1), hy.to(dev), reduction="batchmean"))
            opt.zero_grad(); kayip.backward(); opt.step()
            kayip_top += float(kayip); adim += 1
        plan.step()
        # Uretim modunda holdout yok: olcecek bir sey olmadigi icin her epok
        # kaydediliyor, yani dosyada SON epok kaliyor. Kosinus plani bitiste
        # sifira indigi icin dogru durak orasi.
        eh = son = float("nan") if uretim else hata_px(model, kt, dev, tuval)
        th = hata_px(model, ke, dev, tuval) if e == epok - 1 else None
        isaret = ""
        if uretim or eh < en_iyi:
            en_iyi = eh
            # KUNYE checkpoint'in ICINE yaziliyor. Onceden yalnizca
            # holdout/tuval/derinlik vardi ve dosyalar birbirinden ayirt
            # edilemiyordu: "_data/poz/model.pt hangi veriyle egitildi, ne
            # skor aldi?" sorusunun cevabi hicbir yerde durmuyordu. Bir
            # checkpoint kendi kendini anlatmali, cunku dosya adi tasinir,
            # degisir, unutulur.
            torch.save({"model": model.state_dict(), "tuval": tuval,
                        "holdout": holdout, "derinlik": derinlik,
                        "kunye": {
                            "veri": os.path.abspath(kok),
                            "egitim_ornek": len(egitim), "test_ornek": len(test),
                            "egitim_karakter": len({s["kaynak"].split("/")[0]
                                                    for s in egitim}),
                            "epok": e + 1, "epok_toplam": epok,
                            "parti": parti, "lr": lr, "tohum": tohum,
                            "on_egitimli": on_egitimli,
                            "siluet": siluet,
                            "holdout_hatasi": None if uretim else round(float(eh), 3),
                            "uretim": uretim,
                            "tarih": time.strftime("%Y-%m-%d %H:%M"),
                        }}, cikti)
            isaret = "  <- kaydedildi"
        print(f"  epok {e+1:3d}/{epok}  kayip {kayip_top/max(adim,1):.4f}  "
              + ("" if uretim else f"holdout hatasi {eh:6.2f}px") + (f"  egitim {th:.2f}px" if th else "")
              + f"  {time.time()-t0:.0f}s{isaret}")
    # IKISI DE basiliyor. "En iyi" holdout uzerinde epok seciyor, yani test
    # kumesine bakarak karar veriyor — iyimser tarafli. Iki AYARI
    # karsilastirirken SON epogun hatasini kullan: kosinüs planı 16 epokta
    # sifira indigi icin son epok yakinsamis bir noktadir ve tarafsizdir.
    if uretim:
        print(f"\nURETIM modeli yazildi (holdout yok, olcum yapilmadi): {cikti}")
    else:
        print(f"\nEn iyi holdout hatasi: {en_iyi:.2f}px   "
              f"Son epok: {son:.2f}px   model: {cikti}")
    return en_iyi, son


def main(argv=None):
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = argparse.ArgumentParser(description="Pixel art poz modeli (SimCC).")
    p.add_argument("komut", choices=("train", "eval"))
    p.add_argument("veri", nargs="?", default=os.path.join(kok, "_data", "poz"))
    p.add_argument("--holdout", default="faküs",
                   help="Disarida birakilacak karakter (genelleme olcumu). "
                        "'yok' = URETIM modeli: tum veriyle egitir, genelleme "
                        "olcumu yapmaz. GUI'nin kullandigi model bu olmali.")
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--ckpt", default=None)
    p.add_argument("--depth", type=int, default=3, choices=(2, 3),
                   help="Hangi ResNet katmani: 3=layer3 (8x8), 2=layer2 (16x16)")
    p.add_argument("--scratch", action="store_true",
                   help="On egitimli govde KULLANMA (karsilastirma icin)")
    p.add_argument("--siluet", action="store_true",
                   help="Girdiyi SILUETE cevir (renk atilir). Cizim tarzindan "
                        "bagimsiz olmayi hedefler.")
    p.add_argument("--seed", type=int, default=0,
                   help="Rastgelelik tohumu; ayni ayarin kosu-arasi "
                        "dagilimini olcmek icin degistir")
    args = p.parse_args(argv)

    ckpt = args.ckpt or os.path.join(args.veri, "model.pt")
    if args.komut == "train":
        egit(args.veri, args.holdout, args.epochs, args.batch, args.lr,
             ckpt, on_egitimli=not args.scratch, derinlik=args.depth,
             tohum=args.seed, siluet=args.siluet)
    else:
        torch = _torch()
        d = torch.load(ckpt, map_location="cpu")
        k = d.get("kunye")
        if k:
            # Alanlar TOLERANSLI okunuyor: bu klasordeki eski checkpoint'lerin
            # kunyesi sonradan, elle yazildi ve tam degil.
            parca = [f"veri={os.path.basename(str(k.get('veri', '?')))}"]
            if k.get("tarih"):
                parca.insert(0, k["tarih"])
            if k.get("egitim_ornek"):
                parca.append(f"{k['egitim_ornek']} ornek / "
                             f"{k.get('egitim_karakter', '?')} kaynak")
            if k.get("epok"):
                parca.append(f"epok {k['epok']}/{k.get('epok_toplam', '?')}")
            if k.get("holdout_hatasi") is not None:
                parca.append(f"kayitli hata {k['holdout_hatasi']}px")
            if k.get("not"):
                parca.append(f"({k['not']})")
            print("Kunye: " + "  ".join(parca))
        else:
            print("Kunye YOK — bu checkpoint kunye alani eklenmeden once "
                  "uretilmis; hangi veriyle egitildigi bilinmiyor.")
        satirlar = veri_oku(args.veri)
        test = [s for s in satirlar if s["kaynak"].split("/")[0] == d["holdout"]]
        model = PozModeli(d["tuval"], len(sk.LABELS), on_egitimli=False)
        model.load_state_dict(d["model"])
        dev = aygit(); model.to(dev)
        print(f"holdout={d['holdout']}  {len(test)} ornek  "
              f"hata {hata_px(model, Kume(args.veri, test, d['tuval']), dev, d['tuval']):.2f}px")
    return 0


if __name__ == "__main__":
    sys.exit(main())
