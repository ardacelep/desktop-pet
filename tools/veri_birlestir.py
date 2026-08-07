#!/usr/bin/env python3
"""
veri_birlestir.py — birden fazla veri setini tek egitim kumesinde birlestirir.

    python3 tools/veri_birlestir.py -o _data/karisik _data/poz _data/uretim

NEDEN ARAC

    Egitim kumesi (`_data/karisik`) elle birlestirilmisti ve her yeni uretim
    partisinde tekrar birlestirmek gerekiyor. Elle yapmak iki sessiz hataya
    acik:

    KIMLIK CAKISMASI. Bolme KARAKTER BAZINDA yapiliyor — ayni karakterin
    artirilmis kopyalari hem egitime hem teste dusmesin diye. Iki kaynakta
    ayni `kaynak` kimligi varsa bu bolme sessizce bozulur ve sahte yuksek
    skor uretir. Arac bunu HATA olarak durduruyor, uyari olarak degil.

    ESKI SATIRIN KALMASI. Cikti dizini her kosuda bastan yaziliyor; artik
    kaynakta olmayan bir satir birlesikte kalamaz.

    Gorseller sabit bagla (hard link) baglaniyor, kopyalanmiyor: ayni dosya
    hem kaynakta hem birlesikte duruyor ama disk bir kez doluyor.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys


def satirlari_oku(dizin: str) -> list[dict]:
    yol = os.path.join(dizin, "etiketler.jsonl")
    if not os.path.exists(yol):
        raise SystemExit(f"HATA: {yol} yok.")
    satirlar = []
    with open(yol) as f:
        for ham in f:
            ham = ham.strip()
            if ham:
                satirlar.append(json.loads(ham))
    return satirlar


def cakisan_kimlikler(kaynaklar: dict[str, list[dict]]) -> dict[str, list[str]]:
    """Ayni `kaynak` kimligi birden fazla dizinde geciyor mu?"""
    nerede: dict[str, set[str]] = collections.defaultdict(set)
    for dizin, satirlar in kaynaklar.items():
        for s in satirlar:
            nerede[s["kaynak"]].add(dizin)
    return {k: sorted(v) for k, v in nerede.items() if len(v) > 1}


def birlestir(dizinler: list[str], cikti: str) -> int:
    kaynaklar = {d: satirlari_oku(d) for d in dizinler}

    cakisan = cakisan_kimlikler(kaynaklar)
    if cakisan:
        print(f"HATA: {len(cakisan)} kimlik birden fazla kaynakta geciyor. "
              f"Karakter bazinda bolme bozulur.", file=sys.stderr)
        for k, nerede in list(cakisan.items())[:5]:
            print(f"  {k}: {', '.join(nerede)}", file=sys.stderr)
        return 1

    gorseller = os.path.join(cikti, "gorseller")
    os.makedirs(gorseller, exist_ok=True)

    # Dizin SILINIP yeniden kurulmuyor, FARK uygulanıyor. Silip kurmak, o
    # sirada ayni kumeyi okuyan bir egitim kosusunu ortasindan vuruyordu.
    # Gorseller icerik hash'iyle adlandirildigi icin ayni ad = ayni icerik:
    # duran dosyaya dokunmadan sadece eksikler ekleniyor, artanlar siliniyor.
    hedefler: set[str] = set()
    toplam = 0
    with open(os.path.join(cikti, "etiketler.jsonl"), "w") as f:
        for dizin, satirlar in kaynaklar.items():
            for s in satirlar:
                ad = os.path.basename(s["gorsel"])
                hedefler.add(ad)
                hedef = os.path.join(gorseller, ad)
                if not os.path.exists(hedef):
                    os.link(os.path.join(dizin, s["gorsel"]), hedef)
                y = dict(s, gorsel=f"gorseller/{ad}")
                f.write(json.dumps(y, ensure_ascii=False) + "\n")
                toplam += 1

    artan = [a for a in os.listdir(gorseller) if a not in hedefler]
    for a in artan:
        os.remove(os.path.join(gorseller, a))

    hepsi = [s for v in kaynaklar.values() for s in v]
    ust = collections.Counter(s["kaynak"].split("/")[0] for s in hepsi)
    print(f"{toplam} ornek -> {cikti}" + (f"  ({len(artan)} eski gorsel silindi)"
                                          if artan else ""))
    for ad, n in sorted(ust.items()):
        kim = len({s["kaynak"] for s in hepsi if s["kaynak"].split("/")[0] == ad})
        print(f"  {ad:12s} {n:5d} ornek  {kim:4d} karakter")
    print(f"  {'TOPLAM':12s} {toplam:5d} ornek  "
          f"{len({s['kaynak'] for s in hepsi}):4d} karakter")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Veri setlerini tek egitim kumesinde birlestirir.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Ornek:\n"
               "  python3 tools/veri_birlestir.py -o _data/karisik "
               "_data/poz _data/uretim")
    p.add_argument("kaynak", nargs="+", help="Birlestirilecek veri seti dizinleri")
    p.add_argument("-o", "--out", required=True, help="Cikti dizini")
    args = p.parse_args(argv)
    if os.path.abspath(args.out) in {os.path.abspath(d) for d in args.kaynak}:
        raise SystemExit("HATA: cikti dizini kaynaklardan biri olamaz "
                         "(cikti her kosuda bastan yaziliyor).")
    return birlestir(args.kaynak, args.out)


if __name__ == "__main__":
    sys.exit(main())
