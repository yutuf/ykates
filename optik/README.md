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

- `MEB_LGS_PROFILE` — resmi MEB LGS kitapçıkları (Sayısal + Sözel, 90/90
  soru doğru tespit edildi). Ağır filigran mührü var, ders adı her sayfada
  tekrar eder.
- `SIVAS_KOPRU_PROFILE` — Sivas Köprü Yayınları matematik denemeleri.
  Filigran yok, ders adı sadece ilk sayfada yazıyor (sonraki sayfalarda
  genel "SAYISAL BÖLÜM"/"İZLEME SINAVI" şeridi tekrarlıyor —
  `content_markers` ile ders bilgisi sayfalar arası taşınıyor). 3 farklı
  yıl şablonunda test edildi (2019-20, 2020-21, 2021-22 — üçü de farklı
  görsel tasarım, aynı profil hepsinde 20/20 doğru çalıştı). Bazı sayfalar
  tam genişlik + yarım genişlik soruları karışık kullanıyor, motor bunu
  soru bazında (sayfa bazında değil) otomatik ayırt ediyor.

Yeni bir yayınevi eklemek için:

1. O yayınevinin bir kitapçığını örnek olarak al.
2. `Profile(...)` ile yeni bir profil tanımla — ders başlıkları, filigran
   varsa kelimeleri, cevap anahtarı sayfası imzası, gerekirse
   `content_markers` (ders adı her sayfada tekrar etmiyorsa).
3. Sütun sayısı/genişliği ELLE ayarlanmaz — `detect_columns()` dokümandan
   otomatik öğrenir (1, 2, 3+ sütun, hatta aynı sayfada karışık düzen bile
   fark etmez).

## Bilinen sınırlar

- Sadece native metin PDF (taranmış kitapçıklar için ayrı bir OCR/vision
  motoru gerekir — NIM üzerinden bir layout/OCR modeli değerlendirilecek).
- **Bozuk font kodlaması:** Bazı PDF'ler (özellikle ilovepdf.com gibi
  üçüncü parti sıkıştırma/birleştirme araçlarından geçmiş olanlar) metin
  katmanının ToUnicode eşlemesini bozuyor — harfler okunaksız çıkıyor
  (rakamlar genelde etkilenmiyor). Bu durumda ders/filigran kelime
  eşleştirmesi çalışmaz; tespit edildi (Fikri Bilim örneği), henüz
  çözülmedi.
- **Rozet tarzı soru numaraları:** Bazı yayınevleri (ör. KerimHoca) soru
  numarasını "1." gibi düz metin yerine renkli rozet/kutu grafiği içinde
  gösteriyor; bu durumda pdftotext numarayı parçalanmış/tutarsız glif
  dizileri olarak çıkarabiliyor. Henüz çözülmedi, araştırma sürüyor.
- Sıkı kırpma (soru içeriğinin gerçek bittiği yerde durma) filigran
  kelime listesine dayanıyor; filigranı olmayan/farklı filigranlı
  yayınevlerinde bu liste boş bırakılabilir (güvenli tarafta kalır,
  sadece biraz fazla boşluk bırakır — içerik asla kesilmez).
