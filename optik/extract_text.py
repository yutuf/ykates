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
    kind: str = "base"  # base | sup | sub


@dataclass
class QuestionText:
    number: int
    subject: str
    stem: str = ""
    options: dict = field(default_factory=dict)
    flags: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"soru": self.number, "ders": self.subject,
                "govde": self.stem, "siklar": self.options,
                "uyarilar": self.flags}


def classify(words, baseline_h: float):
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
        out.append(Piece(w.text, w.x0, kind))
    return out


def render_line(pieces: list[Piece]) -> str:
    """Bir satırı soldan sağa metne çevirir; üst/alt simgeler kendinden
    önceki terime LaTeX olarak iliştirilir."""
    parts: list[str] = []
    for p in sorted(pieces, key=lambda p: p.x0):
        text = OPERATOR_MAP.get(p.text, p.text)
        if p.kind == "sup" and parts:
            parts[-1] = parts[-1] + "^{" + text + "}"
        elif p.kind == "sub" and parts:
            parts[-1] = parts[-1] + "_{" + text + "}"
        else:
            parts.append(text)
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


def question_text(page, q, prof, is_boilerplate) -> QuestionText:
    words = [
        w for w in page.words
        if q.x0 - 1 <= w.x0 < q.x1 and q.y0 <= w.y0 < q.y1
        and not is_boilerplate(w, page.height, prof)
    ]
    # soru numarasının kendisi gövdeye girmesin
    words = [w for w in words if not prof.qnum_pattern.match(w.text)]
    if not words:
        return QuestionText(q.number, q.subject, flags=["metin_yok"])

    baseline_h = statistics.median(w.y1 - w.y0 for w in words)
    rows: dict = {}
    for w in words:
        rows.setdefault(round(w.y0 / max(baseline_h * 0.6, 1.0)), []).append(w)

    lines: list[str] = []
    for key in sorted(rows):
        group = rows[key]
        lines.append(render_line(classify(group, baseline_h)))

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
    subject = sys.argv[2] if len(sys.argv) > 2 else None
    pages = parse_bbox(bbox)
    by_index = {p.index: p for p in pages}
    out = []
    for q in extract_questions(pages, MEB_LGS_PROFILE):
        if subject and q.subject != subject:
            continue
        page = by_index[q.page]
        qt = question_text(page, q, MEB_LGS_PROFILE, is_boilerplate_word)
        if find_missing_radicals(page, q):
            qt.flags.append("eksik_kok")
        out.append(qt.as_dict())
    print(json.dumps(out, ensure_ascii=False, indent=2))
