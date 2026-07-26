# Netçe

Kazanım düzeyinde ölçme ve kişiye özel deneme üretimi.

Bir öğrenci deneme çözer → optik okunur → **hangi kazanımda** düştüğü
çıkarılır → yalnızca ona özel, yanlışlarından derlenmiş yeni bir deneme
baskıya hazır üretilir.

---

## Boru hattı

```
kitapçık PDF ──► optik/crop_booklet.py ──► soru görselleri + manifest
                 optik/extract_text.py ──► soru metni + LaTeX + şekil kutuları
                                                    │
optik form ──► (Ateş'in modülü) ──► ogrenci_cevaplari.csv
                                                    │
cevap anahtarı ──► cevap_anahtari.csv ─────────────►│
                                                    ▼
                                        optik/analyze.py
                                                    │
                          ┌─────────────────────────┼─────────────────┐
                          ▼                         ▼                 ▼
                     ozet.csv            <ogrenci>/yanlislar/   kazanim_sinif.csv
                                         <ogrenci>/rapor.json
                                                    │
                                                    ▼
                                      optik/render_template.py
                                                    │
                                                    ▼
                                          özel deneme PDF (markalı)
```

---

## ⚠️ Modüller arası sözleşme (Ateş ↔ YK)

İki modülü birbirine bağlayan **tek şey** bu iki CSV'dir. Sütun **adları**
sabittir, sırası önemsiz. Örnek dosyalar: `ornek/` klasöründe.

### `ogrenci_cevaplari.csv` — optik okuyucunun ÜRETECEĞİ dosya

| sütun | zorunlu | açıklama |
|---|---|---|
| `ogrenci_no` | evet | öğrenciyi ayırt eden numara |
| `ders` | evet | `matematik`, `fen_bilimleri`, `turkce`, `inkilap`, `din_kulturu`, `ingilizce` |
| `soru` | evet | soru numarası (1'den başlar, her ders kendi içinde) |
| `isaret` | evet | `A`/`B`/`C`/`D` — **boş bırakılırsa soru BOŞ sayılır** |
| `ogrenci_ad` | hayır | raporlarda görünür |

```csv
ogrenci_no,ogrenci_ad,ders,soru,isaret
101,Ali Yılmaz,matematik,1,B
101,Ali Yılmaz,matematik,2,
101,Ali Yılmaz,fen_bilimleri,1,D
```

### `cevap_anahtari.csv` — denemenin cevap anahtarı

| sütun | zorunlu | açıklama |
|---|---|---|
| `ders` | evet | yukarıdaki ders adlarıyla aynı |
| `soru` | evet | soru numarası |
| `dogru` | evet | doğru şık |
| `kazanim` | hayır | girilirse kazanım bazlı analiz açılır, girilmezse ders bazında kalır |

```csv
ders,soru,dogru,kazanim
matematik,1,D,Cebirsel ifadeler
matematik,2,A,Üslü ifadeler
```

**Not:** `ders` değerleri bu listeden olmalı, aksi hâlde eşleşme tutmaz.
Format değişirse tek dokunulacak yer `analyze.py` içindeki
`read_answers()` / `read_key()`.

---

## Çalıştırma

```bash
# 0) bağımlılıklar
apt-get install -y poppler-utils tesseract-ocr tesseract-ocr-tur
pip install Pillow pymupdf

# 1) kitapçıktan soruları kırp
python3 optik/crop_booklet.py kitapcik.pdf ./cikti

# 2) (isteğe bağlı) soruları metne + LaTeX'e çevir
python3 optik/extract_text.py cikti/bbox.html kitapcik.pdf matematik > sorular.json

# 3) optik sonuçlarını çözümle, yanlışları ayıkla, özel deneme üret
python3 optik/analyze.py cikti/crops cevap_anahtari.csv ogrenci_cevaplari.csv ./analiz

# 4) markalı PDF şablonuna dök
python3 optik/render_template.py deneme.pdf sorular.json --pages cikti/_pages
```

---

## Durum

| Parça | Durum |
|---|---|
| Kitapçıktan soru kırpma (5 yayınevi test edildi) | ✅ |
| Metin katmanı bozuksa OCR'a düşme | ✅ |
| Metin + LaTeX çıkarma (üst simge, kök, şık) | ✅ Matematik 18/20 · Türkçe 20/20 |
| Görsel ağırlıklı soruyu tek parça taşıma | ✅ |
| Cevap anahtarı eşleştirme, yanlış listesi | ✅ |
| Özel deneme üretimi + markalı şablon | ✅ |
| **Optik form okuma** | ⛔ **Ateş** |

Ayrıntılı teknik notlar ve bilinen sınırlar: [`optik/README.md`](optik/README.md)
