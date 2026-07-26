# Optik — soru kitapçığı kırpıcı

Native metin katmanlı (taranmamış) LGS/deneme kitapçığı PDF'lerini soru
soru kırpar. Vision/OCR kullanmaz — `pdftotext -bbox` ile PDF'in kendi
metin koordinatlarını okur, bu yüzden ücretsiz ve hızlıdır.

Taranmış (fotokopi/scan) PDF'lerde çalışmaz — native metin katmanı gerekir.

## Kurulum

```
apt-get install -y poppler-utils tesseract-ocr tesseract-ocr-tur
pip install Pillow
```

## Kullanım

```
python3 crop_booklet.py kitapcik.pdf ./cikti
```

Çıktı: `./cikti/crops/<ders>_soru<no>.png`, `./cikti/manifest.json`
(numara, ders, kaynak sayfa, bbox) ve `./cikti/rapor.json` (çıkarılamayan
soru numaraları).

## Metin kaynakları

Motorun tamamı yalnızca "konumlu kelime" listesi üzerinde çalışır, bu
yüzden kelimelerin nereden geldiği değiştirilebilir (`source` parametresi):

| source | Kaynak | Ne zaman |
|---|---|---|
| `pdf` | PDF'in gömülü metin katmanı | Hızlı, ücretsiz, birebir doğru |
| `ocr` | Yerel OCR (tesseract) | Metin katmanı yoksa/bozuksa |
| `nim` | NVIDIA NIM OCR | Aynı durum, daha yüksek doğruluk |
| `auto` | Önce `pdf`, yetersizse OCR | **Varsayılan** |

`auto` modunda `NVIDIA_API_KEY` tanımlıysa OCR olarak NIM, değilse
tesseract kullanılır — yani anahtar eklemek dışında bir değişiklik
gerekmez.

### NIM hakkında

`words_from_nim()` NIM OCR'ı (nemoretriever-ocr-v1) tesseract ile aynı
sözleşmeye bağlar. **Bu ortamdan NVIDIA uçlarına ağ erişimi kapalı
olduğu için istek/yanıt biçimi belgelenen sözleşmeye göre yazıldı, canlı
doğrulanamadı.** Yanıt şeması farklı gelirse alan adları tek bir yerden
(`_nim_detections`) güncellenir.

### OCR neden iki geçişli

Tam sayfa taraması gövde metnini iyi okur ama soru numaralarını sık
kaçırır: numara, grafiklerin ortasında tek başına duran küçük/renkli bir
öğedir ve sayfa analizi onu eler. Bu yüzden ikinci geçişte sütun
marjlarındaki dar şeritler ayrıca taranır — dar şeritte rakam çevresindeki
grafiklerle yarışmadığı için güvenle okunur. Yarış kitapçığında bu ikinci
geçiş sonucu 53 → 83 soruya çıkardı.

Ayrıca numara biçimli belirteçlerde OCR güven eşiği daha yüksek tutulur
(yanlış okunan tek bir rakam sıra doğrulamasını yanlış soruya kilitler);
bu da 83 → 88'e taşıdı.

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

| Kitapçık | Kaynak | Sonuç |
|---|---|---|
| MEB 2024 Sayısal | pdf | 40/40 |
| MEB 2024 Sözel | pdf | 50/50 |
| Sivas Köprü Mat. 2019-20 / 2020-21 / 2021-22 | pdf | 20/20 (her biri) |
| Sivas Köprü tam LGS Deneme 7 (45 sayfa, 6 ders) | pdf | 88/90 |
| Yarış Deneme 4 (metin eğriye çevrilmiş) | ocr | 88/90 |
| Fikri Bilim, KerimHoca | — | henüz denenmedi |

Sivas Köprü Deneme 7'deki 2 eksik soru İngilizce bölümünde: o sayfalarda
gömülü fontun karakter eşlemesi bozuk olduğu için soru numaraları metin
katmanından hiç okunamıyor. Motor bunları sessizce atlamaz, `rapor.json`'a
ve `stderr`'e hangi soruların çıkarılamadığını yazar.

## Bilinen sınırlar

Aşağıdaki durumlarda PDF metin katmanı kullanılamaz; hepsinin çözümü OCR
kaynağına geçmektir (`auto` bunu kendiliğinden yapar):

- **Taranmış PDF** — metin katmanı hiç yok.
- **Eğriye çevrilmiş (outline) metin** — yayınevi fontları vektör çizime
  dönüştürmüş; `pdftotext` yalnızca birkaç kırıntı görür. Yarış örneği
  böyle: 50 soru numarasının 33'ü metin katmanında yok, OCR ile 88/90.
- **Bozuk font kodlaması** — gömülü fontun ToUnicode eşlemesi kırık
  (ör. ilovepdf.com'dan geçmiş Fikri Bilim dosyası; Sivas Deneme 7'nin
  İngilizce bölümü kısmen).
- **Rozet tarzı soru numaraları** — KerimHoca numarayı renkli rozet
  grafiği içinde basıyor.

Hiçbir kaynak yeterli sonuç veremezse motor **kısmi/yanlış kırpma üretmek
yerine hata verip durur** (`UNRELIABLE_MISSING_RATIO` eşiği): sessizce
bozuk veri üretmek, açıkça reddetmekten daha kötüdür.

OCR yolunda alt kırpma sınırı bilinçli olarak gevşek tutulur (soru bandının
tamamı alınır). OCR kelime kapsamı eksiksiz olmadığı için "içerik burada
bitti" demek şıkları kesme riski taşır; fazla boşluk zararsız, eksik şık
değil.

Ayrıca sıkı kırpma (soru içeriğinin gerçek bittiği yerde durma) filigran
kelime listesine dayanır; filigranı olmayan yayınevlerinde bu liste boş
bırakılabilir — güvenli tarafta kalır, sadece biraz fazla boşluk bırakır,
içerik asla kesilmez.
