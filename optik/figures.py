#!/usr/bin/env python3
"""Şekil bölgelerini SAYFA GÖRÜNTÜSÜNDEN bulur.

Vektör katmanından bulmayı denemek şu duvara tosladı: filigran mührü de
vektör çizimdir ve rengi doygun kırmızıdır; onu renkten elemek, kırmızı
öğe İÇEREN gerçek şekilleri de siliyordu (ör. fen sorusundaki enzim
figürü kırmızı). Saydamlık da ayırt edici değil — PyMuPDF hepsini
opaklık 1.0 raporluyor.

Buradaki yöntem renkten bağımsız: sayfa görüntüsünden filigran piksel
düzeyinde temizlenir (bu zaten çalışıyor), paragraf satırlarının mürekkebi
maskelenir, geriye kalan mürekkep bağlantılı bileşenlere ayrılır. Kalan
her büyük bileşen bir şekildir — çok parçalı diyagramlar, kırmızı içerik
ve kenarda kalan etiketler dahil.
"""
import re
from dataclasses import dataclass

from PIL import Image

INK_THRESHOLD = 205      # bu tonun altı mürekkep sayılır
DOWNSCALE = 8            # bağlantılı bileşen taraması için küçültme
MIN_FIGURE_PT = 34.0     # pt: bundan küçük bileşen şekil değil
MERGE_GAP_PT = 26.0      # pt: bu kadar yakın bileşenler tek şekle toplanır
PROSE_ROW_WORDS = 6      # bu kadar çok kelimeli satır = paragraf, şekil değil


@dataclass
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    def merged(self, other: "Box") -> "Box":
        return Box(min(self.x0, other.x0), min(self.y0, other.y0),
                   max(self.x1, other.x1), max(self.y1, other.y1))

    def near(self, other: "Box", gap: float) -> bool:
        return not (self.x1 + gap < other.x0 or other.x1 + gap < self.x0
                    or self.y1 + gap < other.y0 or other.y1 + gap < self.y0)


OPTION_TOKEN = re.compile(r"^[A-D]\)$")


def option_bands(words) -> list[tuple]:
    """Yalnızca şık satırlarının dikey aralıkları."""
    rows: dict = {}
    for w in words:
        rows.setdefault(round(w.y0 / 6), []).append(w)
    return [(min(g.y0 for g in group), max(g.y1 for g in group))
            for group in rows.values()
            if any(OPTION_TOKEN.match(g.text) for g in group)]


def prose_bands(words, min_words: int = PROSE_ROW_WORDS) -> list[tuple]:
    """Paragraf ve şık satırlarının dikey aralıkları — bunlar şekil
    değildir, mürekkepleri maskelenir.

    Şık satırları kelime sayısına bakılmaksızın korunur: "A) 2√3  B) 3√3"
    gibi kısa bir satır seyrek göründüğü için şekil sanılıp kutuya
    yutuluyordu ve soru şıklarını kaybediyordu."""
    rows: dict = {}
    for w in words:
        rows.setdefault(round(w.y0 / 6), []).append(w)
    bands = []
    for group in rows.values():
        has_option = any(OPTION_TOKEN.match(g.text) for g in group)
        if len(group) >= min_words or has_option:
            bands.append((min(g.y0 for g in group), max(g.y1 for g in group)))
    return bands


def find_figures(page_png, question, words, dpi: int = 300) -> list[Box]:
    """Sorunun içindeki şekil kutularını (pt) döndürür."""
    from analyze import remove_watermark

    px = dpi / 72.0
    with Image.open(page_png) as im:
        crop = im.crop((int(question.x0 * px), int(question.y0 * px),
                        int(min(question.x1 * px, im.width)),
                        int(min(question.y1 * px, im.height)))).convert("RGB")
    crop = remove_watermark(crop)

    small = crop.convert("L").resize(
        (max(crop.width // DOWNSCALE, 1), max(crop.height // DOWNSCALE, 1)),
        Image.LANCZOS)
    w, h = small.size
    data = small.load()

    # Metnin mürekkebini haritadan çıkar. Satır bandı yerine KELİME
    # KUTULARI maskelenir: satır bandını "kaç kelime var" gibi bir eşikle
    # ayırmak dar sütunlarda çöküyordu (satır başına az kelime düşünce
    # paragraf, şekil sanılıp sorunun kendi metni "şekil" olarak
    # kırpılıyordu). Kelime kutuları maskelenince geriye yalnızca metin
    # OLMAYAN mürekkep kalır; bu tanım gereği çizim/görseldir.
    cell = DOWNSCALE / px
    masked: set = set()
    for word in words:
        a = int((word.x0 - question.x0) / cell)
        b = int((word.x1 - question.x0) / cell) + 1
        c = int((word.y0 - question.y0) / cell)
        d = int((word.y1 - question.y0) / cell) + 1
        for yy in range(max(c, 0), min(d, h)):
            for xx in range(max(a, 0), min(b, w)):
                masked.add((xx, yy))

    ink = set()
    for yy in range(h):
        for xx in range(w):
            if (xx, yy) not in masked and data[xx, yy] < INK_THRESHOLD:
                ink.add((xx, yy))

    # bağlantılı bileşenler (8 komşu)
    seen: set = set()
    boxes: list[Box] = []
    scale_back = DOWNSCALE / px
    for cell in ink:
        if cell in seen:
            continue
        stack = [cell]
        seen.add(cell)
        comp = []
        while stack:
            cx, cy = stack.pop()
            comp.append((cx, cy))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nxt = (cx + dx, cy + dy)
                    if nxt in ink and nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
        xs = [c[0] for c in comp]
        ys = [c[1] for c in comp]
        boxes.append(Box(
            question.x0 + min(xs) * scale_back,
            question.y0 + min(ys) * scale_back,
            question.x0 + (max(xs) + 1) * scale_back,
            question.y0 + (max(ys) + 1) * scale_back,
        ))

    # yakın bileşenleri birleştir (çok parçalı diyagramlar tek şekildir)
    merged: list[Box] = []
    for b in sorted(boxes, key=lambda b: (b.y0, b.x0)):
        for i, m in enumerate(merged):
            if m.near(b, MERGE_GAP_PT):
                merged[i] = m.merged(b)
                break
        else:
            merged.append(b)
    # birleşme zinciri: ikinci geçiş
    changed = True
    while changed:
        changed = False
        out: list[Box] = []
        for b in merged:
            for i, m in enumerate(out):
                if m.near(b, MERGE_GAP_PT):
                    out[i] = m.merged(b)
                    changed = True
                    break
            else:
                out.append(b)
        merged = out

    # Kutu, altındaki ilk paragraf/şık satırına taşmasın. Birleştirme
    # adımı iki ayrı diyagramı toplarken araya giren metin satırlarını da
    # kapsayabiliyor; bu kırpma, şıkların şekle yutulmasını engeller.
    # Yalnızca ŞIK satırlarında kırp. Paragraf satırlarında kırpmak yanlış
    # olurdu: şeklin altında açıklama cümlesi bulunması olağan ve o cümle
    # şekli sonlandırmaz — orada kırpınca şekiller tümden kayboluyordu.
    clipped: list[Box] = []
    for b in merged:
        below = [y0 for y0, _ in option_bands(words) if y0 > b.y0 + 4]
        limit = min(below) - 2 if below else b.y1
        clipped.append(Box(b.x0, b.y0, b.x1, min(b.y1, limit)))

    return [b for b in clipped
            if b.x1 - b.x0 >= MIN_FIGURE_PT and b.y1 - b.y0 >= MIN_FIGURE_PT]
