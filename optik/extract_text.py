#!/usr/bin/env python3
"""Soru metnini konumlu kelimelerden yeniden kurar (kırpılmış görsel
yerine düzenlenebilir metin).

Şu an kapsanan:
  - üst/alt simge: geometriden (küçük punto + kaymış taban çizgisi)
    -> LaTeX `^{...}` / `_{...}`
  - gömülü fontun yanlış eşlediği operatörler (ör. '#' aslında '×')
  - satır sonu tirelemesi ("sağladı-" + "ğından" -> "sağladığından")
  - A) B) C) D) şıklarının ayrıştırılması

Henüz kapsanmayan: kök işareti (√) ve kesirler. Bunlar gömülü fontta
Unicode eşlemesi olmadan (pdffonts: "uni no") çizildiği için metin
katmanında hiç görünmez; o sorular `eksik_kok` ile işaretlenir.
"""
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Gömülü fontun Unicode'a yanlış/eksik eşlediği işaretler. Kaynak PDF'te
# görülen karakter -> gerçek anlamı.
OPERATOR_MAP = {
    "#": "×",
    "$": "≥",
    "!": "≠",
}

OPTION_RE = re.compile(r"^([A-D])\)$")


@dataclass
class Piece:
    text: str
    x0: float
    x1: float = 0.0
    y0: float = 0.0
    kind: str = "base"  # base | sup | sub
    radical: int | None = None  # altında bulunduğu kök çizgisinin sırası


# Kök işareti gömülü fontta bir karakter DEĞİL, vektör çizimidir; bu
# yüzden metin katmanında hiç görünmez. Ama çizim olarak bulunabilir:
# ince, yatayda geniş bir "stroke" ve altında kalan rakamlar. Aşağıdaki
# sınırlar o çizgiyi kutu/tablo kenarlarından ayırır.
RADICAL_MAX_HEIGHT = 14.0
RADICAL_MIN_WIDTH = 6.0
RADICAL_TICK_MAX_WIDTH = 6.0   # kökün sol ucundaki küçük çentik
RADICAL_TICK_MAX_HEIGHT = 7.0  # çentik kısadır; tablo dikey ayracı satır boyu uzar
RADICAL_TICK_GAP = 2.5         # çentik ile üst çizgi bitişik sayılır


def radical_spans(page) -> list[tuple]:
    """Sayfadaki kök çizgilerini (vinculum) döndürür: (x0, x1, y_alt).

    Ayırt edici imza GENİŞLİK DEĞİL, kökün sol ucundaki küçük çentiktir:
    √ işareti iki parça çizilir — önce kısa diyagonal çentik, hemen
    ardından sayının üstünü örten yatay çizgi. Tablo ve kutu kenarları da
    ince yatay çizgidir (bu kitapçıkta hücre kenarları 37pt, yani kök
    çizgisiyle aynı boyda) ama solunda çentik yoktur."""
    strokes = [d["rect"] for d in page.get_drawings() if d["type"] == "s"]
    ticks = [r for r in strokes
             if r.width <= RADICAL_TICK_MAX_WIDTH
             and r.height <= RADICAL_TICK_MAX_HEIGHT]
    spans = []
    for r in strokes:
        if not (r.height <= RADICAL_MAX_HEIGHT and r.width >= RADICAL_MIN_WIDTH):
            continue
        has_tick = any(
            abs(t.x1 - r.x0) <= RADICAL_TICK_GAP and t.y1 >= r.y1 - RADICAL_MAX_HEIGHT
            and t.y0 <= r.y1 + 2
            for t in ticks
        )
        if has_tick:
            spans.append((r.x0, r.x1, r.y1))
    return spans


def under_radical(x0: float, x1: float, y0: float, spans: list[tuple]) -> int | None:
    """Terimin altında bulunduğu kök çizgisinin sırası (yoksa None).
    Hangi çizgi olduğunu döndürmek gerekir: yan yana iki kök
    (\\sqrt{2}\\sqrt{3}) tek köke birleştirilmemeli."""
    for i, (sx0, sx1, sy1) in enumerate(spans):
        if sx0 - 2 <= x0 and x1 <= sx1 + 2 and -2 <= y0 - (sy1 - 10.0) <= 12.0:
            return i
    return None


@dataclass
class QuestionText:
    number: int
    subject: str
    stem: str = ""
    options: dict = field(default_factory=dict)
    flags: list = field(default_factory=list)
    figures: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"soru": self.number, "ders": self.subject,
                "govde": self.stem, "siklar": self.options,
                "gorseller": self.figures, "uyarilar": self.flags}


def classify(words, baseline_h: float, radicals: list[tuple] = ()):
    """Her kelimeyi taban / üst simge / alt simge diye ayırır.

    Üst simge imzası: puntonun küçülmesi TEK BAŞINA yetmez — çarpım
    işareti de küçük gelir ama dikeyde ortalanmıştır. Ayırt edici olan,
    küçük punto ile birlikte taban çizgisinin YUKARI kaymasıdır."""
    base_top = statistics.median(w.y0 for w in words)
    out = []
    for w in words:
        h = w.y1 - w.y0
        small = h < baseline_h * 0.9
        raised = w.y0 < base_top - baseline_h * 0.12
        lowered = w.y0 > base_top + baseline_h * 0.25
        kind = "sup" if (small and raised) else ("sub" if (small and lowered) else "base")
        out.append(Piece(w.text, w.x0, w.x1, w.y0, kind,
                         under_radical(w.x0, w.x1, w.y0, radicals)))
    return out


def render_line(pieces: list[Piece]) -> str:
    """Bir satırı soldan sağa metne çevirir; üst/alt simgeler kendinden
    önceki terime LaTeX olarak iliştirilir, kök altındaki terimler
    \\sqrt{} ile sarılır.

    AYNI kök çizgisinin altındaki ardışık parçalar tek bir köke toplanır:
    "1", ",", "44" ayrı kelimeler olarak gelir ama hepsi tek bir çizginin
    altındadır -> \\sqrt{1,44}, üç ayrı kök değil."""
    parts: list[str] = []
    pending: list[str] = []  # aynı kökün altında biriken parçalar
    pending_id: int | None = None

    def flush():
        nonlocal pending_id
        if pending:
            parts.append("\\sqrt{" + "".join(pending) + "}")
            pending.clear()
        pending_id = None

    for p in sorted(pieces, key=lambda p: p.x0):
        text = OPERATOR_MAP.get(p.text, p.text)
        if p.radical is not None:
            if pending and p.radical != pending_id:
                flush()
            pending.append(text)
            pending_id = p.radical
            continue
        flush()
        if p.kind == "sup" and parts:
            parts[-1] = parts[-1] + "^{" + text + "}"
        elif p.kind == "sub" and parts:
            parts[-1] = parts[-1] + "_{" + text + "}"
        else:
            parts.append(text)
    flush()
    return " ".join(parts)


def join_hyphenation(lines: list[str]) -> str:
    """Dizgi kaynaklı satır sonu tirelemesini birleştirir: 'sağladı-' +
    'ğından' -> 'sağladığından'. Gerçek tireli sözcükler ("Covid-19")
    satır sonunda bölünmediği için etkilenmez."""
    out = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if out.endswith("-"):
            out = out[:-1] + line
        else:
            out = (out + " " + line) if out else line
    return out


MIN_FIGURE_SIDE = 38.0   # pt: bundan küçük çizim kümesi şekil sayılmaz
FIGURE_MERGE_GAP = 12.0  # pt: bu kadar yakın çizimler tek şekle toplanır
DECOR_MIN_PAGES = 5      # aynı yerde bu kadar sayfada tekrar eden çizim = süsleme


def decoration_rects(doc) -> set:
    """Filigran/mühür çizimlerini konumundan tanır: her sayfada TAM AYNI
    yerde tekrar ederler. Renge göre elemek yayınevine bağımlı olurdu
    (MEB'inki şeffaflıkla soluk görünen doygun kırmızı), tekrar konumu
    ise yayınevinden bağımsız bir imzadır."""
    seen: dict = {}
    for pno in range(doc.page_count):
        for d in doc[pno].get_drawings():
            r = d["rect"]
            key = (round(r.x0), round(r.y0), round(r.x1), round(r.y1))
            seen.setdefault(key, set()).add(pno)
    threshold = max(DECOR_MIN_PAGES, doc.page_count // 5)
    return {k for k, pages in seen.items() if len(pages) >= threshold}


def is_decorative_color(drawing) -> bool:
    """Filigran/mühür çizimleri doygun kırmızıyla çizilip saydamlıkla
    soluklaştırılıyor; sayfada dolaştıkları için konum tekrarına da
    takılmıyorlar. Bu yüzden renkten de elenirler — aksi hâlde cümlenin
    ortasındaki bir mühür yıldızı "şekil" sanılıp içine düşen kelimeleri
    gövdeden siliyor."""
    col = drawing.get("fill") or drawing.get("color")
    if not col or len(col) < 3:
        return False
    r, g, b = col[0], col[1], col[2]
    return r > 0.55 and r - max(g, b) > 0.35


def figure_boxes(pdf_page, q, decorations: set) -> list:
    """Sorunun içindeki görsel bölgeleri döndürür (çizim kümeleri +
    gömülü resimler). Şeklin İÇİNDEKİ etiketler ("3x cm", "Yukarı") böylece
    gövde metninden ayıklanabilir; aksi hâlde cümlenin ortasına karışıyor."""
    import fitz

    boxes = []
    for d in pdf_page.get_drawings():
        r = d["rect"]
        key = (round(r.x0), round(r.y0), round(r.x1), round(r.y1))
        if key in decorations or is_decorative_color(d):
            continue
        # kök çizgisi / alt çizgi gibi ince çizgiler şekil değildir
        if r.height < 15 and r.width < 60:
            continue
        boxes.append(fitz.Rect(r))
    for im in pdf_page.get_image_info():
        boxes.append(fitz.Rect(im["bbox"]))

    inside = [b for b in boxes
              if b.y0 >= q.y0 - 4 and b.y1 <= q.y1 + 4
              and b.x0 >= q.x0 - 4 and b.x1 <= q.x1 + 4]

    merged: list = []
    for b in sorted(inside, key=lambda r: (r.y0, r.x0)):
        placed = False
        for i, m in enumerate(merged):
            grown = fitz.Rect(m) + (-FIGURE_MERGE_GAP, -FIGURE_MERGE_GAP,
                                    FIGURE_MERGE_GAP, FIGURE_MERGE_GAP)
            if grown.intersects(b):
                merged[i] = fitz.Rect(m) | b
                placed = True
                break
        if not placed:
            merged.append(fitz.Rect(b))

    return [m for m in merged
            if m.width >= MIN_FIGURE_SIDE and m.height >= MIN_FIGURE_SIDE]


LABEL_GAP = 11.0          # pt: şekle bu kadar yakın yazı, şeklin etiketi sayılır
MAX_LABEL_ROW_WORDS = 5   # bu kadar az kelimeli satır = etiket, değilse paragraf


def grow_to_labels(boxes: list, words, passes: int = 2) -> list:
    """Şekil kutusunu, kendi etiketlerini içine alacak biçimde büyütür.

    Kutu yalnızca ÇİZİMLERDEN kurulduğu için ("3x cm", "Beyaz", eksen
    adları) yazılar dışarıda kalıyordu; sonuç olarak etiket hem
    kırpılan görselden düşüyor hem de gövde cümlesinin ortasında
    kalıyordu. Bir kelime kutuya yeterince yakınsa ve yatayda kutunun
    hizasındaysa şekle dahil edilir — paragraf satırları sütun marjından
    başladığı için bu koşula takılmaz."""
    import fitz

    # Şekil etiketleri seyrek satırlardır ("Yukarı", "Sol", "3x cm");
    # paragraf satırları ise satır boyunca çok sayıda kelime taşır. Kutuyu
    # yalnızca seyrek satırlarla büyütmek, şeklin çevresindeki yön
    # etiketlerini içeri alırken gövde metnini dışarıda bırakır.
    row_size: dict = {}
    for w in words:
        row_size[round(w.y0 / 6)] = row_size.get(round(w.y0 / 6), 0) + 1
    sparse = [w for w in words if row_size.get(round(w.y0 / 6), 0) <= MAX_LABEL_ROW_WORDS]

    grown = [fitz.Rect(b) for b in boxes]
    for _ in range(passes):
        for i, b in enumerate(grown):
            near = fitz.Rect(b) + (-LABEL_GAP, -LABEL_GAP, LABEL_GAP, LABEL_GAP)
            for w in sparse:
                if near.intersects(fitz.Rect(w.x0, w.y0, w.x1, w.y1)):
                    grown[i] = fitz.Rect(grown[i]) | fitz.Rect(w.x0, w.y0, w.x1, w.y1)
    return grown


def in_any_box(w, boxes) -> bool:
    return any(b.x0 - 2 <= w.x0 and w.x1 <= b.x1 + 2
               and b.y0 - 2 <= w.y0 and w.y1 <= b.y1 + 2 for b in boxes)


def question_text(page, q, prof, is_boilerplate, radicals: list[tuple] = (),
                  figures: list = ()) -> QuestionText:
    words = [
        w for w in page.words
        if q.x0 - 1 <= w.x0 < q.x1 and q.y0 <= w.y0 < q.y1
        and not is_boilerplate(w, page.height, prof)
    ]
    # soru numarasının kendisi gövdeye girmesin
    words = [w for w in words if not prof.qnum_pattern.match(w.text)]
    # şeklin içindeki etiketler gövde cümlesine karışmasın; onlar
    # kırpılacak görselin parçası
    words = [w for w in words if not in_any_box(w, figures)]
    if not words:
        return QuestionText(q.number, q.subject, flags=["metin_yok"])

    baseline_h = statistics.median(w.y1 - w.y0 for w in words)

    # Satırları sabit bir ızgaraya yuvarlayarak gruplamak hatalıydı: aynı
    # satırdaki küçük punto öğeler (eksi işareti, çarpım) taban çizgisinden
    # 1-2pt kayık durduğu için komşu kutuya düşüp ayrı satır sayılıyordu.
    # Bunun yerine art arda gelen kelimeler, satır yüksekliğinin yarısı
    # kadar tolerans içinde aynı satıra toplanır.
    rows: list[list] = []
    for w in sorted(words, key=lambda w: w.y0):
        if rows and w.y0 - rows[-1][0].y0 <= baseline_h * 0.5:
            rows[-1].append(w)
        else:
            rows.append([w])

    lines: list[str] = [
        render_line(classify(group, baseline_h, radicals)) for group in rows
    ]

    # Şıkları gövdeden ayır
    stem_lines: list[str] = []
    options: dict = {}
    current: str | None = None
    for line in lines:
        tokens = line.split()
        if any(OPTION_RE.match(t) for t in tokens):
            current = None
            buf: list[str] = []
            for t in tokens:
                m = OPTION_RE.match(t)
                if m:
                    if current:
                        options[current] = " ".join(buf).strip()
                    current, buf = m.group(1), []
                elif current:
                    buf.append(t)
            if current:
                options[current] = " ".join(buf).strip()
        elif current:
            options[current] = (options.get(current, "") + " " + line).strip()
        else:
            stem_lines.append(line)

    qt = QuestionText(q.number, q.subject, join_hyphenation(stem_lines), options)
    qt.figures = [
        {"x0": b.x0, "y0": b.y0, "x1": b.x1, "y1": b.y1, "sayfa": q.page}
        for b in figures
    ]
    if len(options) != 4:
        qt.flags.append(f"sik_sayisi={len(options)}")
    return qt


def find_missing_radicals(page, q) -> bool:
    """Kök işareti metin katmanında yok; varlığını dolaylı anlarız:
    sayıların hemen solunda kelime bulunmayan belirgin boşluk + üstte
    çizgi. Kesin değil, bu yüzden yalnızca UYARI olarak işaretlenir."""
    nums = [w for w in page.words
            if q.x0 - 1 <= w.x0 < q.x1 and q.y0 <= w.y0 < q.y1
            and w.text.replace(",", "").isdigit()]
    for w in nums:
        left = [o for o in page.words
                if abs(o.y0 - w.y0) < 4 and o.x1 <= w.x0 and w.x0 - o.x1 < 14]
        if not left and w.x0 - q.x0 > 12:
            return True
    return False


if __name__ == "__main__":
    import json

    from crop_booklet import (MEB_LGS_PROFILE, extract_questions,
                              is_boilerplate_word, parse_bbox)

    bbox = Path(sys.argv[1])
    pdf = Path(sys.argv[2])
    subject = sys.argv[3] if len(sys.argv) > 3 else None

    import fitz  # PyMuPDF: kök çizgileri yalnızca vektör katmanında var

    pages = parse_bbox(bbox)
    by_index = {p.index: p for p in pages}
    doc = fitz.open(pdf)
    radicals_by_page = {i + 1: radical_spans(doc[i]) for i in range(doc.page_count)}
    decorations = decoration_rects(doc)

    out = []
    for q in extract_questions(pages, MEB_LGS_PROFILE):
        if subject and q.subject != subject:
            continue
        page = by_index[q.page]
        figures = figure_boxes(doc[q.page - 1], q, decorations)
        in_q = [w for w in page.words
                if q.x0 - 1 <= w.x0 < q.x1 and q.y0 <= w.y0 < q.y1]
        figures = grow_to_labels(figures, in_q)
        qt = question_text(page, q, MEB_LGS_PROFILE, is_boilerplate_word,
                           radicals_by_page.get(q.page, []), figures)
        out.append(qt.as_dict())
    print(json.dumps(out, ensure_ascii=False, indent=2))
