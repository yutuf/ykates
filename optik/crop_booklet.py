#!/usr/bin/env python3
"""
Soru kitapçığı kırpıcı — çekirdek motor + yayınevi profili.

Yöntem: PDF native metin katmanına sahipse (taranmış görüntü değil),
Vision/OCR gerekmez. `pdftotext -bbox` ile her kelimenin koordinatını okuyup
soru numaralarını tespit ediyoruz, sonra pdftoppm ile yüksek çözünürlüklü
sayfa görselleri üretip bu koordinatlara göre kırpıyoruz.

Mimari: bu dosyadaki mantığın çoğu YAYINEVİNDEN BAĞIMSIZDIR (soru numarası
dizisi doğrulama, sütun sayısı/genişliği otomatik tespiti, sıkı kırpma).
Yayınevine özel olan kısımlar (filigran kelimeleri, ders başlığı anahtar
kelimeleri, soru numarası deseni, cevap anahtarı sayfası imzası) bir
`Profile` nesnesinde toplanır. Yeni bir yayınevi eklemek için sadece yeni
bir Profile tanımlamak yeterli olmalı, çekirdek motoru değiştirmeden.

Taranmış (scan) PDF'ler bu yöntemle ÇALIŞMAZ — native metin katmanı yoksa
(pdftotext boş döner) OCR/vision tabanlı ayrı bir motor gerekir.

Soru numarası tespiti: "N." (veya profile'a göre "N)" vb.) biçimindeki her
aday, sayfa okuma sırasında (sütunlar soldan sağa, her sütun üstten alta,
sayfa sayfa ilerleyerek) 1'den başlayıp artan bir dizi oluşturuyor mu diye
kontrol edilir. Çoğu kitapçığın başındaki talimat metni de aynı numara
kalıbını kullandığından önce 1,2 diye görünüp sonra tekrar 1'e resetlenir —
gerçek ders/bölüm değişimiyle çakışan bu reset gerçek soru dizisinin
başlangıcı kabul edilir.
"""
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

WORD_RE = re.compile(
    r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>'
)
PAGE_RE = re.compile(r'<page width="([\d.]+)" height="([\d.]+)">')


@dataclass
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str


@dataclass
class Page:
    index: int  # 1-based, matches PDF page number
    width: float
    height: float
    words: list = field(default_factory=list)


def parse_bbox(bbox_path: Path) -> list[Page]:
    pages: list[Page] = []
    current: Page | None = None
    for line in bbox_path.read_text(encoding="utf-8").splitlines():
        pm = PAGE_RE.search(line)
        if pm:
            current = Page(index=len(pages) + 1, width=float(pm.group(1)), height=float(pm.group(2)))
            pages.append(current)
            continue
        wm = WORD_RE.search(line)
        if wm and current is not None:
            x0, y0, x1, y1, text = wm.groups()
            text = (
                text.replace("&amp;", "&")
                .replace("&lt;", "<")
                .replace("&gt;", ">")
                .replace("&quot;", '"')
                .replace("&#39;", "'")
            )
            current.words.append(Word(float(x0), float(y0), float(x1), float(y1), text))
    return pages


# ─────────────────────────── Yayınevi profili ───────────────────────────

@dataclass
class Profile:
    name: str
    # Soru numarası kalıbı: group(1) = numara. Farklı yayınevleri "1)" ya da
    # "1-" da kullanabilir.
    qnum_pattern: re.Pattern = field(default_factory=lambda: re.compile(r"^(\d{1,2})\.$"))
    # Sayfa başlığında (header_y_max altında) geçen BÜYÜK HARF -> ders id eşlemesi.
    subject_keywords: dict = field(default_factory=dict)
    header_y_max: float = 115.0
    # Cevap anahtarı sayfasını tanımak için birlikte geçmesi gereken iki alt metin.
    answer_key_markers: tuple = ("CEVAP", "ANAHTARI")
    # Filigran/mühür kelimeleri — sıkı kırpmada içerik sınırı hesabından çıkarılır.
    watermark_words: frozenset = frozenset()
    # "1. Bu testte..." gibi talimat satırlarını eleyen, numaradan hemen
    # sonra gelen kelimeler.
    preamble_next_words: frozenset = frozenset()
    # Soru numaraları noktaya göre sağa yaslı dizilir ("1." ile "10." aynı
    # hizada bitmez); marj tek taraflı üst sınır: [en_küçük_x0, +SLACK].
    margin_slack: float = 13.0
    # Sayfa altındaki sayfa-numarası şeridi (bu bant sıkı kırpmada içerik
    # sayılmaz).
    footer_band: float = 60.0


MEB_LGS_PROFILE = Profile(
    name="meb_lgs",
    qnum_pattern=re.compile(r"^(\d{1,2})\.$"),
    subject_keywords={
        "MATEMATİK": "matematik", "FEN BİLİMLERİ": "fen_bilimleri",
        "TÜRKÇE": "turkce", "İNKILAP": "inkilap",
        "DİN KÜLTÜRÜ": "din_kulturu", "İNGİLİZCE": "ingilizce",
    },
    answer_key_markers=("CEVAP", "ANAHTARI"),
    watermark_words=frozenset({
        "T.C.", "CUMHURİYETİ", "MİLLÎ", "MİLLİ", "EĞİTİM", "BAKANLIĞI",
        "ÖLÇME,", "ÖLÇME", "DEĞERLENDİRME", "VE", "SINAV", "HİZMETLERİ",
        "GENEL", "MÜDÜRLÜĞÜ", "MÜDÜRLÜĞÜ,", "(ÖDSGM)", "ÖDSGM", "TÜRKİYE",
    }),
    preamble_next_words=frozenset({"Bu", "Cevaplarınızı"}),
    margin_slack=13.0,
    footer_band=60.0,
)

SINGLE_LETTER_RE = re.compile(r"^[A-ZÇĞİÖŞÜ]$")


def is_answer_key_page(page: Page, profile: Profile) -> bool:
    text = " ".join(w.text for w in page.words)
    return all(marker in text for marker in profile.answer_key_markers)


def subject_for_page(page: Page, profile: Profile) -> str | None:
    """Ders adı sayfa başlığında (üstte) büyük harfle geçer."""
    if is_answer_key_page(page, profile):
        return None
    header_words = [w for w in page.words if w.y0 < profile.header_y_max]
    text = " ".join(w.text for w in header_words)
    for keyword, subject_id in profile.subject_keywords.items():
        if keyword in text:
            return subject_id
    return None


def is_boilerplate_word(w: Word, page_height: float, profile: Profile) -> bool:
    """Filigran/mühür metni gerçek (siyah) mürekkeple basılı olduğundan
    renkten ayırt edilemez; sabit kelime dağarcığı + izole tek harf rozetler
    + sayfa altındaki sayfa-numarası ile eleniyor."""
    if w.text in profile.watermark_words:
        return True
    if SINGLE_LETTER_RE.match(w.text):
        return True
    if w.text.isdigit() and w.y0 > page_height - profile.footer_band:
        return True
    return False


# ─────────────────────────── Sütun tespiti (otomatik) ───────────────────

def detect_columns(pages: list[Page], profile: Profile) -> list[float]:
    """Sütun sayısını VE konumunu sabit varsaymak yerine dokümandan öğrenir:
    tüm soru-numarası adaylarının x0'larını kümeler (sağa-yaslı numaralama
    yüzünden tek/çift haneli sayılar ~margin_slack kadar kayar, bu yüzden
    kümeleme eşiği margin_slack tabanlıdır). En az 3 kez görülen kümeler
    gerçek bir sütun başlangıcı kabul edilir; soru içi gürültü (alt madde
    numaraları vb.) çoğunlukla tek seferlik olduğundan elenir."""
    xs = []
    for page in pages:
        if subject_for_page(page, profile) is None:
            continue
        for w in page.words:
            if profile.qnum_pattern.match(w.text):
                xs.append(w.x0)
    if not xs:
        return [0.0]

    xs.sort()
    clusters: list[list[float]] = [[xs[0]]]
    for x in xs[1:]:
        if x - clusters[-1][-1] <= profile.margin_slack + 5:
            clusters[-1].append(x)
        else:
            clusters.append([x])

    starts = [min(c) for c in clusters if len(c) >= 3]
    return sorted(starts) if starts else [min(xs)]


def column_index(x0: float, starts: list[float], profile: Profile) -> int | None:
    """x0'ı en yakın sütun başlangıcına eşler; hiçbirine (marj toleransı
    içinde) uymuyorsa None döner (gerçek soru numarası değildir)."""
    for i, start in enumerate(starts):
        if start - 1.0 <= x0 <= start + profile.margin_slack:
            return i
    return None


def find_question_candidates(page: Page, starts: list[float], profile: Profile):
    """Sayfadaki numara kalıbındaki kelimeleri okuma sırasına (sütun sırası,
    her sütun içinde üstten alta) göre döndürür."""
    cands = []
    for w in page.words:
        m = profile.qnum_pattern.match(w.text)
        if not m:
            continue
        col = column_index(w.x0, starts, profile)
        if col is None:
            continue
        cands.append((col, w.y0, int(m.group(1)), w))
    cands.sort(key=lambda t: (t[0], t[1]))
    return cands


@dataclass
class Question:
    number: int
    subject: str
    page: int
    x0: float
    y0: float
    x1: float
    y1: float


def next_word_on_line(page: Page, cand: Word) -> Word | None:
    same_line = [
        w for w in page.words
        if w is not cand and abs(w.y0 - cand.y0) < 3 and w.x0 > cand.x1
    ]
    if not same_line:
        return None
    return min(same_line, key=lambda w: w.x0)


def extract_questions(pages: list[Page], profile: Profile) -> list[Question]:
    """Tüm doküman boyunca okuma sırasıyla ilerleyip, 1'den başlayan artan
    dizi kuran adayları gerçek soru kabul eder (resetler yeni ders demektir).
    Ders başlığı olmayan sayfalar (kapak, cevap anahtarı, kurallar) ve
    talimat satırları baştan elenir."""
    starts = detect_columns(pages, profile)

    raw = []  # (page_index, col, y0, number, word, subject)
    for page in pages:
        subject = subject_for_page(page, profile)
        if subject is None:
            continue
        for col, y0, number, w in find_question_candidates(page, starts, profile):
            nxt = next_word_on_line(page, w)
            if nxt is not None and nxt.text in profile.preamble_next_words:
                continue
            raw.append((page.index, col, y0, number, w, subject))

    accepted = []
    expected = 1
    last_subject = None
    for page_index, col, y0, number, w, subject in raw:
        if number == expected:
            accepted.append((page_index, col, y0, number, w, subject))
            expected += 1
            last_subject = subject
        elif number == 1 and expected != 1 and subject != last_subject:
            # gerçek ders değişimi (ör. Matematik -> Fen Bilimleri) resetlendi.
            # Aynı ders içinde beliren sahte "1." (soru içi madde vb.) burada
            # elenir, çünkü last_subject ile subject aynı kalır.
            accepted.append((page_index, col, y0, number, w, subject))
            expected = 2
            last_subject = subject
        # else: dizinin dışında (talimat metni, soru içi madde vb.) -> atla

    # Bir sayfada sadece TEK sütun dolu ise (diğer sütunlarda kabul edilmiş
    # soru yoksa), o sayfa tam genişlik düzenindedir (grafik/tablo içeren
    # sorularda sıkça görülür) -> sütunlara bölmeden tüm sayfa genişliğini
    # kullan. Birden fazla sütun doluysa tespit edilen sütun sınırları
    # arasında böl.
    cols_per_page: dict[int, set] = {}
    for p, col, *_ in accepted:
        cols_per_page.setdefault(p, set()).add(col)

    CONTENT_PAD = 10.0  # son satırın altına bırakılan küçük nefes payı

    questions: list[Question] = []
    pages_by_index = {p.index: p for p in pages}
    for i, (page_index, col, y0, number, w, subject) in enumerate(accepted):
        page = pages_by_index[page_index]
        full_width_page = len(cols_per_page[page_index]) <= 1
        if full_width_page:
            x0, x1 = 0.0, page.width
        else:
            x0 = max(starts[col] - 6, 0.0)
            # bir sonraki sütunun başlangıcının hemen öncesine kadar kırp
            x1 = starts[col + 1] - 4 if col + 1 < len(starts) else page.width

        # dikey üst sınır: aynı sayfa+sütunda bir sonraki soru var mı?
        upper_bound = page.height - 20  # alt kenar boşluğu (sayfa no. şeridi)
        for j in range(i + 1, len(accepted)):
            n_page, n_col, n_y0, *_ = accepted[j]
            if n_page == page_index and n_col == col:
                upper_bound = n_y0 - 2
                break
            if n_page != page_index:
                break

        top = max(y0 - 14, 30)
        content_bottom = top
        for cw in page.words:
            if is_boilerplate_word(cw, page.height, profile):
                continue
            if x0 - 1 <= cw.x0 < x1 and top <= cw.y0 < upper_bound:
                content_bottom = max(content_bottom, cw.y1)
        y1 = min(content_bottom + CONTENT_PAD, upper_bound)

        questions.append(
            Question(number=number, subject=subject or "bilinmiyor", page=page_index,
                     x0=x0, y0=top, x1=x1, y1=y1)
        )
    return questions


def render_pages(pdf_path: Path, out_dir: Path, dpi: int = 300):
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(dpi), str(pdf_path), str(out_dir / "page")],
        check=True,
    )


def crop_questions(pdf_path: Path, out_dir: Path, profile: Profile = MEB_LGS_PROFILE, dpi: int = 300):
    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)
    bbox_path = out_dir / "bbox.html"
    subprocess.run(["pdftotext", "-bbox", str(pdf_path), str(bbox_path)], check=True)
    pages = parse_bbox(bbox_path)
    if not any(p.words for p in pages):
        raise RuntimeError(
            "Bu PDF'te metin katmanı yok (muhtemelen taranmış görüntü) — "
            "bu araç sadece native metin PDF'lerde çalışır, taranmış "
            "kitapçıklar için OCR/vision tabanlı ayrı bir motor gerekir."
        )
    questions = extract_questions(pages, profile)

    render_dir = out_dir / "_pages"
    render_pages(pdf_path, render_dir, dpi=dpi)

    scale = dpi / 72.0
    crops_dir = out_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)

    manifest = []
    for q in questions:
        page_png = render_dir / f"page-{q.page:02d}.png"
        if not page_png.exists():
            page_png = render_dir / f"page-{q.page}.png"
        if not page_png.exists():
            print(f"UYARI: sayfa görseli yok: {q.page}", file=sys.stderr)
            continue
        img = Image.open(page_png)
        box = (
            int(q.x0 * scale), int(q.y0 * scale),
            int(q.x1 * scale), int(q.y1 * scale),
        )
        crop = img.crop(box)
        fname = f"{q.subject}_soru{q.number:02d}.png"
        crop.save(crops_dir / fname)
        manifest.append({
            "number": q.number, "subject": q.subject, "page": q.page,
            "file": fname, "bbox_pt": [q.x0, q.y0, q.x1, q.y1],
        })
    return manifest


if __name__ == "__main__":
    import json

    pdf = Path(sys.argv[1])
    out = Path(sys.argv[2])
    manifest = crop_questions(pdf, out, MEB_LGS_PROFILE)
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{len(manifest)} soru kırpıldı -> {out}/crops/")
    by_subject = {}
    for m in manifest:
        by_subject.setdefault(m["subject"], []).append(m["number"])
    for subj, nums in by_subject.items():
        print(f"  {subj}: {len(nums)} soru (min={min(nums)}, max={max(nums)})")
