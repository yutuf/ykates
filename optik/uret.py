#!/usr/bin/env python3
"""Kazanımdan yeni soru üretir — kaynak kitapçıktan kopyalamadan.

Neden şablon, neden dil modeli değil: üretilen sorunun cevabı DOĞRU
olmak zorunda. Bir dil modeline soru yazdırmak, her soruyu tek tek insana
doğrulatmayı gerektirir; yanlış cevap anahtarıyla satılan bir deneme
ürünü bitirir. Burada cevap üretilmiyor, HESAPLANIYOR — parametreler
rastgele seçilir, doğru şık aritmetikle bulunur, dolayısıyla her zaman
doğrudur.

Çeldiriciler de rastgele değil: her şablon, o kazanımda öğrencilerin
yaptığı TİPİK HATALARDAN türetir (üslü ifadede çarpma yerine toplama,
kökte katsayıyı kök içine alma gibi). Rastgele sayı üretmek soruyu
kolaylaştırır; tipik hatayı üretmek soruyu ölçer hâle getirir.

Hukuki not: şablonlar MEB kazanım listesinden yazıldı, taranmış
kitapçıktan değil. Bir yayınevinin sorusunun sayılarını değiştirmek FSEK
anlamında işlemedir ve izin gerektirir; kazanımdan sıfırdan yazmak özgün
eserdir.

    python3 uret.py --kazanim "Üslü ifadeler" --adet 5 > yeni.json
    python3 uret.py --adet 12 | python3 -c "..."   # tüm kazanımlardan
"""
import argparse
import json
import math
import random
from dataclasses import dataclass, field


@dataclass
class Uretilen:
    kazanim: str
    govde: str
    dogru_metin: str
    celdiriciler: list

    def as_question(self, number: int, subject: str = "matematik") -> dict:
        """Şıkları karıştırıp mevcut soru sözlüğü biçimine çevirir."""
        secenekler = [self.dogru_metin] + [c for c in self.celdiriciler]
        random.shuffle(secenekler)
        harfler = "ABCD"
        siklar = {harfler[i]: s for i, s in enumerate(secenekler)}
        dogru = harfler[secenekler.index(self.dogru_metin)]
        return {
            "soru": number,
            "ders": subject,
            "govde": self.govde,
            "siklar": siklar,
            "gorseller": [],
            "uyarilar": [],
            "mod": "metin",
            "tam_kirpim": None,
            "dogru": dogru,
            "kazanim": self.kazanim,
            "uretilmis": True,
        }


def _benzersiz(dogru, adaylar, bicim) -> list:
    """Çeldiriciler birbirinden ve doğru cevaptan farklı olmalı; tipik
    hatalar bazen aynı sonuca çıkıyor, o zaman yedek üretilir."""
    out: list = []
    for a in adaylar:
        m = bicim(a)
        if m != bicim(dogru) and m not in out:
            out.append(m)
    return out[:3]


# ─────────────────────────────── Şablonlar ────────────────────────────────
#
# Her şablon: (kazanım adı, üretici fonksiyon). Üretici, rastgele
# parametrelerle bir Uretilen döndürür.

SABLONLAR: dict = {}


def sablon(kazanim: str):
    def kaydet(fn):
        SABLONLAR.setdefault(kazanim, []).append(fn)
        return fn
    return kaydet


@sablon("Üslü ifadeler")
def uslu_carpma(rnd: random.Random) -> Uretilen:
    taban = rnd.choice([2, 3, 5, 7])
    a, b = rnd.randint(2, 7), rnd.randint(2, 6)
    dogru = a + b
    yanlis = [a * b,        # üsleri çarpmak
              abs(a - b),   # üsleri çıkarmak
              a + b + 1]    # sayma hatası
    bicim = lambda u: f"{taban}^{{{u}}}"
    return Uretilen(
        "Üslü ifadeler",
        f"{taban}^{{{a}}} · {taban}^{{{b}}} işleminin sonucu "
        f"aşağıdakilerden hangisine eşittir?",
        bicim(dogru), _benzersiz(dogru, yanlis, bicim),
    )


@sablon("Üslü ifadeler")
def uslu_bolme(rnd: random.Random) -> Uretilen:
    taban = rnd.choice([2, 3, 5])
    b = rnd.randint(2, 5)
    a = b + rnd.randint(2, 5)
    dogru = a - b
    # b - a (negatif üs) çeldirici olarak işe yaramıyor: öğrenci bakar
    # bakmaz eliyor. Tipik hatalar toplama, çarpma ve üssü olduğu gibi
    # bırakmaktır.
    yanlis = [a + b, a * b, a]
    bicim = lambda u: f"{taban}^{{{u}}}"
    return Uretilen(
        "Üslü ifadeler",
        f"{taban}^{{{a}}} : {taban}^{{{b}}} işleminin sonucu "
        f"aşağıdakilerden hangisidir?",
        bicim(dogru), _benzersiz(dogru, yanlis, bicim),
    )


@sablon("Kareköklü ifadeler")
def kok_carpma(rnd: random.Random) -> Uretilen:
    # tam kareye inecek biçimde seçilir ki sonuç sadeleşsin
    k = rnd.choice([2, 3, 5, 6, 7])
    kat = rnd.choice([2, 3, 4])
    ic = k * k * kat
    dogru = f"{k} \\sqrt{{{kat}}}"
    yanlis = [f"{kat} \\sqrt{{{k}}}",            # kat ile kökü karıştırmak
              f"\\sqrt{{{ic}}}",                  # sadeleştirmemek
              f"{k * kat} \\sqrt{{{kat}}}"]       # katsayıyı iki kez almak
    return Uretilen(
        "Kareköklü ifadeler",
        f"\\sqrt{{{ic}}} ifadesinin en sade biçimi aşağıdakilerden hangisidir?",
        dogru, _benzersiz(dogru, yanlis, lambda x: x),
    )


@sablon("Kareköklü ifadeler")
def kok_toplama(rnd: random.Random) -> Uretilen:
    kok = rnd.choice([2, 3, 5, 7])
    a, b = rnd.randint(2, 6), rnd.randint(2, 6)
    dogru = f"{a + b} \\sqrt{{{kok}}}"
    yanlis = [f"{a * b} \\sqrt{{{kok}}}",              # katsayıları çarpmak
              f"{a + b} \\sqrt{{{kok + kok}}}",        # kök içini de toplamak
              f"\\sqrt{{{(a + b) * kok}}}"]            # katsayıyı içeri almak
    return Uretilen(
        "Kareköklü ifadeler",
        f"{a}\\sqrt{{{kok}}} + {b}\\sqrt{{{kok}}} işleminin sonucu kaçtır?",
        dogru, _benzersiz(dogru, yanlis, lambda x: x),
    )


@sablon("Cebirsel ifadeler")
def ozdeslik_kare(rnd: random.Random) -> Uretilen:
    a = rnd.randint(2, 9)
    dogru = f"x^{{2}} + {2 * a}x + {a * a}"
    yanlis = [f"x^{{2}} + {a * a}",                    # orta terimi unutmak
              f"x^{{2}} + {a}x + {a * a}",             # orta terimi 2 ile çarpmamak
              f"x^{{2}} + {2 * a}x + {2 * a}"]         # sabit terimi yanlış almak
    return Uretilen(
        "Cebirsel ifadeler",
        f"(x + {a})^{{2}} ifadesinin özdeşi aşağıdakilerden hangisidir?",
        dogru, _benzersiz(dogru, yanlis, lambda x: x),
    )


@sablon("Cebirsel ifadeler")
def carpanlara_ayirma(rnd: random.Random) -> Uretilen:
    a = rnd.randint(2, 9)
    kare = a * a
    dogru = f"(x - {a})(x + {a})"
    yanlis = [f"(x - {a})^{{2}}",
              f"(x + {a})^{{2}}",
              f"(x - {kare})(x + {kare})"]
    return Uretilen(
        "Cebirsel ifadeler",
        f"x^{{2}} - {kare} ifadesinin çarpanlara ayrılmış biçimi "
        f"aşağıdakilerden hangisidir?",
        dogru, _benzersiz(dogru, yanlis, lambda x: x),
    )


@sablon("Olasılık")
def olasilik_torba(rnd: random.Random) -> Uretilen:
    kirmizi = rnd.randint(2, 8)
    mavi = rnd.randint(2, 8)
    sari = rnd.randint(1, 5)
    toplam = kirmizi + mavi + sari
    bol = math.gcd(kirmizi, toplam)
    dogru = f"\\frac{{{kirmizi // bol}}}{{{toplam // bol}}}"
    yanlis = [f"\\frac{{{kirmizi}}}{{{mavi + sari}}}",   # paydayı kalan sayı almak
              f"\\frac{{{mavi}}}{{{toplam}}}",           # yanlış rengi almak
              f"\\frac{{1}}{{{toplam}}}"]                # tek top saymak
    return Uretilen(
        "Olasılık",
        f"Bir torbada {kirmizi} kırmızı, {mavi} mavi ve {sari} sarı top "
        f"vardır. Torbadan rastgele çekilen bir topun kırmızı olma "
        f"olasılığı kaçtır?",
        dogru, _benzersiz(dogru, yanlis, lambda x: x),
    )


@sablon("Üçgende Pisagor")
def pisagor(rnd: random.Random) -> Uretilen:
    k, m = rnd.choice([(3, 4), (6, 8), (5, 12), (8, 15), (9, 12)])
    hip = int(math.isqrt(k * k + m * m))
    dogru = f"{hip} cm"
    yanlis = [f"{k + m} cm",                    # kenarları toplamak
              f"{abs(m - k)} cm",
              f"{k * m // 2} cm"]               # alanla karıştırmak
    return Uretilen(
        "Üçgende Pisagor",
        f"Dik kenar uzunlukları {k} cm ve {m} cm olan bir dik üçgenin "
        f"hipotenüs uzunluğu kaç cm'dir?",
        dogru, _benzersiz(dogru, yanlis, lambda x: x),
    )


@sablon("Oran ve yüzde")
def yuzde_indirim(rnd: random.Random) -> Uretilen:
    fiyat = rnd.choice([200, 250, 400, 500, 800, 1200])
    indirim = rnd.choice([10, 20, 25, 40])
    dogru_deger = fiyat * (100 - indirim) // 100
    yanlis = [fiyat * indirim // 100,                 # indirim tutarını cevap sanmak
              fiyat + fiyat * indirim // 100,         # zam yapmak
              fiyat - indirim]                        # yüzdeyi TL sanmak
    bicim = lambda v: f"{v} TL"
    return Uretilen(
        "Oran ve yüzde",
        f"Etiket fiyatı {fiyat} TL olan bir ürüne %{indirim} indirim "
        f"uygulanıyor. Ürünün indirimli fiyatı kaç TL olur?",
        bicim(dogru_deger), _benzersiz(dogru_deger, yanlis, bicim),
    )


def uret(kazanim: str | None = None, adet: int = 5,
         seed: int | None = None) -> list:
    """Verilen kazanımdan (ya da hepsinden) `adet` soru üretir.

    Aynı şablonun aynı parametrelerle iki kez çıkmaması için üretilenler
    gövdelerine göre tekilleştirilir."""
    rnd = random.Random(seed)
    havuz = (SABLONLAR.get(kazanim, []) if kazanim
             else [f for fns in SABLONLAR.values() for f in fns])
    if not havuz:
        raise SystemExit(f"Kazanım bulunamadı: {kazanim}\n"
                         f"Seçenekler: {', '.join(SABLONLAR)}")
    gorulen: set = set()
    out: list = []
    denemeler = 0
    while len(out) < adet and denemeler < adet * 60:
        denemeler += 1
        u = rnd.choice(havuz)(rnd)
        if u.govde in gorulen or len(u.celdiriciler) < 3:
            continue
        gorulen.add(u.govde)
        out.append(u)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kazanim", help="tek bir kazanımdan üret")
    ap.add_argument("--adet", type=int, default=5)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--liste", action="store_true", help="kazanımları listele")
    args = ap.parse_args()

    if args.liste:
        for k, fns in SABLONLAR.items():
            print(f"{k}  ({len(fns)} şablon)")
        raise SystemExit(0)

    random.seed(args.seed)
    sorular = [u.as_question(i) for i, u in
               enumerate(uret(args.kazanim, args.adet, args.seed), start=1)]
    print(json.dumps(sorular, ensure_ascii=False, indent=2))
