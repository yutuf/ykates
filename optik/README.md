# Optik — soru kitapçığı kırpıcı

Native metin katmanlı (taranmamış) LGS/deneme kitapçığı PDF'lerini soru
soru kırpar. Vision/OCR kullanmaz — `pdftotext -bbox` ile PDF'in kendi
metin koordinatlarını okur, bu yüzden ücretsiz ve hızlıdır.

Taranmış (fotokopi/scan) PDF'lerde çalışmaz — native metin katmanı gerekir.

## Kurulum

```
apt-get install -y poppler-utils
pip install Pillow
```

## Kullanım

```
python3 crop_booklet.py kitapcik.pdf ./cikti
```

Çıktı: `./cikti/crops/<ders>_soru<no>.png` + `./cikti/manifest.json`
(her sorunun numarası, dersi, kaynak sayfası, bbox koordinatları).

## Yayınevi profilleri

Filigran kelimeleri, ders başlığı anahtar kelimeleri, soru numarası deseni
(`"1."` / `"1)"` vb.), cevap anahtarı sayfası imzası gibi yayınevine özel
ayarlar `Profile` sınıfında toplanır (`crop_booklet.py` içinde). Çekirdek
motor (sütun sayısı/genişliği tespiti, soru sırası doğrulama, tam
genişlik/yarım genişlik ayrımı, sıkı kırpma) yayınevinden bağımsızdır.

Hazır profiller:

- `MEB_LGS_PROFILE` — resmi MEB LGS kitapçıkları. Ağır filigran mührü var,
  ders adı her sayfada tekrar eder, numaralandırma sütun-önceliklidir.
- `SIVAS_KOPRU_PROFILE` — Sivas Köprü Yayınları. Hem tek ders (Matematik)
  hem tam LGS kitapçığı şablonları. Ders adı bazen yalnızca ilk sayfada
  yazıyor (`content_markers` ile taşınıyor), numaralandırma satır-önceliklidir.
- `YARIS_PROFILE` — Yarış Ortaokulu denemeleri. Tanımlı, ama bu örnekte
  metin eğriye çevrilmiş olduğu için motor dosyayı reddediyor (aşağıya bkz.).

Yeni bir yayınevi eklemek için:

1. O yayınevinin bir kitapçığını örnek olarak al.
2. `Profile(...)` ile yeni bir profil tanımla — ders başlıkları, filigran
   varsa kelimeleri, cevap anahtarı sayfası imzası, gerekirse
   `content_markers` (ders adı her sayfada tekrar etmiyorsa).
3. Şunları ELLE ayarlamak gerekmez, motor dokümandan otomatik öğrenir:
   sütun sayısı/konumu, sayfa içi numaralandırma yönü (sütun- ya da
   satır-öncelikli), üstbilgi/altbilgi şeritleri, tam genişlik ve yarım
   genişlik soruların aynı sayfada karışık kullanımı.

## Doğrulama durumu

| Kitapçık | Sonuç |
|---|---|
| MEB 2024 Sayısal | 40/40 |
| MEB 2024 Sözel | 50/50 |
| Sivas Köprü Mat. 2019-20 / 2020-21 / 2021-22 | 20/20 (her biri) |
| Sivas Köprü tam LGS Deneme 7 (45 sayfa, 6 ders) | 88/90 |
| Yarış Deneme 4 | reddedildi (metin katmanı yetersiz) |
| Fikri Bilim, KerimHoca | işlenemiyor (aşağıya bkz.) |

Sivas Köprü Deneme 7'deki 2 eksik soru İngilizce bölümünde: o sayfalarda
gömülü fontun karakter eşlemesi bozuk olduğu için soru numaraları metin
katmanından hiç okunamıyor. Motor bunları sessizce atlamaz, `rapor.json`'a
ve `stderr`'e hangi soruların çıkarılamadığını yazar.

## Bilinen sınırlar

Aşağıdaki üç durumda metin tabanlı yöntem yapısal olarak çalışmaz; ortak
çözüm OCR/vision tabanlı ikinci bir motordur (NIM üzerinden bir layout/OCR
modeli değerlendirilecek):

- **Taranmış PDF** — metin katmanı hiç yok.
- **Eğriye çevrilmiş (outline) metin** — yayınevi fontları vektör çizime
  dönüştürmüş; `pdftotext` yalnızca birkaç kırıntı görür. Yarış örneği
  böyle: 50 soru numarasının 33'ü okunamıyor.
- **Bozuk font kodlaması** — gömülü fontun ToUnicode eşlemesi kırık,
  harfler okunaksız çıkıyor (ör. ilovepdf.com'dan geçmiş Fikri Bilim
  dosyası; Sivas Deneme 7'nin İngilizce bölümü kısmen).
- **Rozet tarzı soru numaraları** — KerimHoca numarayı düz metin yerine
  renkli rozet grafiği içinde basıyor, numara parçalanmış glif dizileri
  olarak çıkıyor.

Motor bu dosyalarda **kısmi/yanlış kırpma üretmek yerine hata verip
durur** (`UNRELIABLE_MISSING_RATIO` eşiği): sessizce bozuk veri üretmek,
açıkça reddetmekten daha kötüdür.

Ayrıca sıkı kırpma (soru içeriğinin gerçek bittiği yerde durma) filigran
kelime listesine dayanır; filigranı olmayan yayınevlerinde bu liste boş
bırakılabilir — güvenli tarafta kalır, sadece biraz fazla boşluk bırakır,
içerik asla kesilmez.
