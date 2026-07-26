"""Sayı saymak yeterli değil: kırpılan her sorunun GERÇEKTEN o soru
olduğunu metninden doğrular. Kapak talimatları, cevap anahtarı satırları
ve benzeri sahte 'sorular' burada yakalanır."""
import re, sys
from pathlib import Path
from crop_booklet import parse_bbox, extract_questions

# Soru olmadığı kesin olan metinler (kapak talimatları, kural sayfası)
BAD = ["salon yoklama", "cevap kâğıdındaki kimlik", "kitapçık türünü",
       "cevap kâğıdı üzerindeki", "sınav başladıktan sonra",
       "öğrenciler, sınav kurallarına", "bu testte", "cevaplarınızı"]

def check(name, bbox, profile):
    pages = parse_bbox(Path(bbox))
    by_index = {p.index: p for p in pages}
    qs = extract_questions(pages, profile)
    bad = []
    for q in qs:
        page = by_index[q.page]
        txt = " ".join(
            w.text for w in page.words
            if q.x0 - 1 <= w.x0 < q.x1 and q.y0 <= w.y0 < min(q.y1, q.y0 + 60)
        ).lower()
        if any(b in txt for b in BAD):
            bad.append((q.subject, q.number, txt[:70]))
    print(f"{name}: {len(qs)} soru | sahte: {len(bad)}")
    for s, n, t in bad[:5]:
        print(f"   ! {s} {n}: {t}")
    return bad
