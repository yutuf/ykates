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
(`"1."` / `"1)"` vb.) gibi yayınevine özel ayarlar `Profile` sınıfında
toplanır (`crop_booklet.py` içinde). Şu an `MEB_LGS_PROFILE` hazır (resmi
MEB LGS kitapçıkları için, hem Sayısal hem Sözel bölümde test edildi).

Yeni bir yayınevi eklemek için:

1. O yayınevinin bir kitapçığını örnek olarak al.
2. `Profile(...)` ile yeni bir profil tanımla — ders başlıkları, filigran
   varsa kelimeleri, cevap anahtarı sayfası imzası.
3. Sütun sayısı/genişliği ELLE ayarlanmaz — `detect_columns()` dokümandan
   otomatik öğrenir (1, 2, 3+ sütun fark etmez).

## Bilinen sınırlar

- Sadece native metin PDF (taranmış kitapçıklar için ayrı bir OCR/vision
  motoru gerekir — NIM üzerinden bir layout/OCR modeli değerlendirilecek).
- Sıkı kırpma (soru içeriğinin gerçek bittiği yerde durma) filigran
  kelime listesine dayanıyor; filigranı olmayan/farklı filigranlı
  yayınevlerinde bu liste boş bırakılabilir (güvenli tarafta kalır,
  sadece biraz fazla boşluk bırakır — içerik asla kesilmez).
