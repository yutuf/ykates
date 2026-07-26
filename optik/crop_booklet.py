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
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

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
    # OCR kaynaklı kelimelerde tanıma güveni (0-100). PDF metin katmanından
    # gelenler kesin kabul edilir.
    conf: float = 100.0


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
    # Ders adı her sayfada tekrar etmeyen yayınevlerinde (yalnızca ilk
    # sayfada "MATEMATİK" yazıp sonrasında sadece "SAYISAL BÖLÜM" gibi genel
    # bir şerit tekrarlayanlar), bir sayfanın "ders adı yok ama yine de
    # içerik sayfası" olduğunu anlamak için bu genel işaretler kullanılır.
    # Boş bırakılırsa (varsayılan) sadece açık ders adı olan sayfalar
    # içerik sayılır — ders devam ettirilmez (MEB gibi her sayfada ders adı
    # tekrar eden yayınevleri için doğru davranış).
    content_markers: frozenset = frozenset()


# LGS'nin ders adları yayınevinden yayınevine sadece süsleme farkıyla
# yazılıyor ("MATEMATİK" / "MATEMATİK TESTİ" / "Matematik"), bu yüzden
# ayırt edici kök parçalar tüm profillerde ortak kullanılabiliyor.
# Eşleştirme tr_upper ile harf büyüklüğünden bağımsız yapılır.
LGS_SUBJECT_KEYWORDS = {
    "MATEMATİK": "matematik",
    "FEN BİLİMLERİ": "fen_bilimleri",
    "TÜRKÇE": "turkce",
    "İNKILAP": "inkilap",
    "DİN KÜLTÜRÜ": "din_kulturu",
    "İNGİLİZCE": "ingilizce",
    "YABANCI DİL": "ingilizce",
}

MEB_LGS_PROFILE = Profile(
    name="meb_lgs",
    qnum_pattern=re.compile(r"^(\d{1,2})\.$"),
    subject_keywords=LGS_SUBJECT_KEYWORDS,
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

# Sivas Köprü Yayınları — hem tek ders (Matematik) hem tam LGS kitapçığı
# şablonları. Bazı şablonlarda ders adı yalnızca ilk sayfada yazıp sonraki
# sayfalarda sadece "SAYISAL BÖLÜM"/"İZLEME SINAVI" şeridi tekrarlanıyor ->
# content_markers ile ders devam ettiriliyor. Filigran yok; üstbilgideki
# "8. SINIF" otomatik mobilya tespitiyle eleniyor (profilde ayar gerekmez).
SIVAS_KOPRU_PROFILE = Profile(
    name="sivas_kopru",
    qnum_pattern=re.compile(r"^(\d{1,2})\.$"),
    subject_keywords=LGS_SUBJECT_KEYWORDS,
    content_markers=frozenset({"BÖLÜM", "İZLEME"}),
    answer_key_markers=("CEVAP", "ANAHTARI"),
    watermark_words=frozenset(),
    preamble_next_words=frozenset(),
    margin_slack=13.0,
    footer_band=60.0,
)

# Yarış Ortaokulu deneme kitapçıkları — ders adı "... TESTİ" ekiyle yazılıyor
# ve bazı sayfalarda üstbilgide ders adı hiç geçmiyor, sadece
# "... 4. DENEME SINAVI" şeridi kalıyor -> content_markers ile devam.
# Üstbilgideki "8. SINIFLAR" / "4. DENEME" ifadeleri soru numarası desenine
# uyuyor ama otomatik mobilya tespitiyle eleniyor.
YARIS_PROFILE = Profile(
    name="yaris",
    qnum_pattern=re.compile(r"^(\d{1,2})\.$"),
    subject_keywords=LGS_SUBJECT_KEYWORDS,
    content_markers=frozenset({"DENEME SINAVI"}),
    answer_key_markers=("CEVAP", "ANAHTARI"),
    watermark_words=frozenset(),
    preamble_next_words=frozenset(),
    margin_slack=13.0,
    footer_band=60.0,
)

SINGLE_LETTER_RE = re.compile(r"^[A-ZÇĞİÖŞÜ]$")


def tr_upper(s: str) -> str:
    """Python'un varsayılan .upper()'ı Türkçe I/İ ayrımını bozar (baskısız
    'i' -> 'I' olur, 'İ' değil). Bazı yayınevleri başlıkları büyük harfle
    ('MATEMATİK'), bazıları normal harfle ('Matematik') yazıyor — bu ayrımı
    önceden düzeltip karşılaştırmayı harf büyüklüğünden bağımsız yapar."""
    return s.replace("i", "İ").replace("ı", "I").upper()


def is_answer_key_page(page: Page, profile: Profile) -> bool:
    text = tr_upper(" ".join(w.text for w in page.words))
    return all(tr_upper(marker) in text for marker in profile.answer_key_markers)


def next_word_on_line(page: Page, cand: Word) -> Word | None:
    same_line = [
        w for w in page.words
        if w is not cand and abs(w.y0 - cand.y0) < 3 and w.x0 > cand.x1
    ]
    if not same_line:
        return None
    return min(same_line, key=lambda w: w.x0)


def starts_a_question(page: Page, w: Word) -> bool:
    """'12.' benzeri bir belirtecin gerçekten soru başlatıp başlatmadığı.
    Üstbilgi etiketleri de aynı kalıbı kullanır ("8. SINIF", "4. DENEME
    SINAVI") ama devamı BÜYÜK HARF bir etikettir; soru metni ise normal
    cümledir ("1. Aşağıda ...")."""
    nxt = next_word_on_line(page, w)
    if nxt is None:
        return True
    letters = [c for c in nxt.text if c.isalpha()]
    return not (len(letters) >= 2 and all(c.isupper() for c in letters))


def header_cutoff(page: Page, profile: Profile, furniture: set) -> float:
    """Başlık bandının bittiği y. Sabit bir değer kullanmak güvenilmez:
    bazı düzenlerde soru gövdesi 115pt'nin üstünde başlar ve gövdede geçen
    bir ders adı ("...125.988 TÜRKÇE sözcük derlendi...") sayfanın dersini
    yanlış belirler. Başlık, tanım gereği sayfadaki İLK SORUNUN üstünde
    kalan kısımdır; soru bulunamazsa profildeki üst sınıra düşülür."""
    tops = [
        w.y0 for w in page.words
        if profile.qnum_pattern.match(w.text)
        and not is_furniture(w, furniture)
        and starts_a_question(page, w)
    ]
    # İlk soru bandı DARALTIR, asla genişletmez. Genişletmesine izin
    # verilirse kapak sayfası tuzağa düşer: kapaktaki sınav talimatları
    # ("1. Salon yoklama listesinde...") soru gibi göründüğü için band
    # sayfanın ortasına kadar açılır, oradaki "DERS ADI / MATEMATİK"
    # tablosu başlık sanılır ve kapak bir Matematik sayfasına dönüşür.
    return min(min(tops), profile.header_y_max) if tops else profile.header_y_max


def header_text(page: Page, profile: Profile, furniture: set) -> str:
    limit = header_cutoff(page, profile, furniture)
    return tr_upper(" ".join(w.text for w in page.words if w.y0 < limit))


def explicit_subject_for_page(page: Page, profile: Profile, furniture: set) -> str | None:
    """Sayfa başlığında geçen ders adını arar (harf büyüklüğünden bağımsız)
    — sadece BU sayfada açıkça yazılıysa döner."""
    text = header_text(page, profile, furniture)
    for keyword, subject_id in profile.subject_keywords.items():
        if tr_upper(keyword) in text:
            return subject_id
    return None


def is_generic_content_page(page: Page, profile: Profile, furniture: set) -> bool:
    """content_markers boşsa hiçbir sayfa 'genel içerik' sayılmaz (ders adı
    her sayfada açıkça tekrar etmeli). Doluysa, o genel şeritlerden biri
    başlıkta geçen her sayfa içerik sayılır (ama hangi ders olduğu bir
    önceki açık eşleşmeden miras alınır)."""
    if not profile.content_markers:
        return False
    text = header_text(page, profile, furniture)
    return any(tr_upper(marker) in text for marker in profile.content_markers)


def page_subjects(pages: list[Page], profile: Profile, furniture: set) -> dict:
    """Her sayfanın dersini belirler. Birçok yayınevi ders adını SADECE o
    dersin ilk sayfasında yazar, sonraki sayfalarda sadece genel bir bölüm
    şeridi ("SAYISAL BÖLÜM" gibi) tekrar eder — bu yüzden başlıkta açık ders
    adı yoksa ama sayfa yine de `content_markers`'tan biriyle "bu içerik
    sayfası" diye işaretliyse bir önceki sayfanın dersi devam ettirilir.
    Ne açık ders adı ne genel işaret olan sayfalar (kapak, cevap anahtarı,
    kural sayfası vb.) HARİÇ TUTULUR — miras alınmaz, çünkü bu tür sayfalar
    kendi içinde soru numarasına benzeyen numaralı listeler (kurallar,
    talimatlar) içerebilir ve yanlışlıkla soru sanılabilir."""
    result: dict = {}
    last: str | None = None
    for page in pages:
        if is_answer_key_page(page, profile):
            result[page.index] = None
            last = None
            continue
        explicit = explicit_subject_for_page(page, profile, furniture)
        if explicit is not None:
            result[page.index] = explicit
            last = explicit
        elif page.index > 1 and last is not None and is_generic_content_page(page, profile, furniture):
            result[page.index] = last
        else:
            result[page.index] = None
    return result


def in_footer_band(w: Word, page_height: float, profile: Profile) -> bool:
    """Sayfa altındaki sabit şerit (sayfa no., '8. SINIF' gibi tekrarlayan
    etiketler) — buradaki kelimeler ne soru numarası adayı ne de içerik
    sınırı hesabına dahil edilir."""
    return w.y0 > page_height - profile.footer_band


def is_boilerplate_word(w: Word, page_height: float, profile: Profile) -> bool:
    """Filigran/mühür metni gerçek (siyah) mürekkeple basılı olduğundan
    renkten ayırt edilemez; sabit kelime dağarcığı + izole tek harf rozetler
    + sayfa altındaki sabit şerit ile eleniyor."""
    if w.text in profile.watermark_words:
        return True
    if SINGLE_LETTER_RE.match(w.text):
        return True
    if in_footer_band(w, page_height, profile):
        return True
    return False


# Sayfa mobilyası (running header/footer) eşiği: aynı metnin TAM AYNI
# konumda kaç farklı sayfada tekrar etmesi gerektiği. Gerçek bir soru
# numarası en fazla ders sayısı kadar tekrar edebilir (her dersin "1."i
# aynı yerde başlayabilir; LGS'de en çok 6 ders), bu yüzden 7 güvenli bir
# alt sınır. Uzun kitapçıklarda oran da devreye girer.
def furniture_min_pages(n_content_pages: int) -> int:
    return max(7, n_content_pages // 4)


def find_repeating_furniture(pages: list[Page]) -> set:
    """Üstbilgi/altbilgi şeritlerini (ör. "8. SINIF", "4. DENEME SINAVI")
    yayınevine özel kelime listesi yazmadan, verinin kendisinden bulur:
    bu şeritler her sayfada TAM AYNI (metin, x, y) konumunda tekrar eder.
    Gerçek soru metni ise sayfadan sayfaya kayar.

    Bu, üstbilgide geçen "8." gibi ifadelerin soru numarası sanılmasını
    engeller — hangi bandın üstbilgi olduğunu elle ayarlamaya gerek
    kalmadan. Ders tespitinden ÖNCE çalışır (ders tespiti başlık bandını
    bulmak için mobilyayı kullanır), bu yüzden tüm sayfalara bakar."""
    if not pages:
        return set()
    threshold = furniture_min_pages(len(pages))
    seen: dict = {}
    for page in pages:
        for w in page.words:
            seen.setdefault((w.text, round(w.x0), round(w.y0)), set()).add(page.index)
    return {key for key, pgs in seen.items() if len(pgs) >= threshold}


def is_furniture(w: Word, furniture: set) -> bool:
    return (w.text, round(w.x0), round(w.y0)) in furniture


# ─────────────────────────── Sütun tespiti (otomatik) ───────────────────

# OCR şerit taramasında toplanacak numara biçimi. Tesseract noktayı bazen
# virgül/parantez okuduğu ya da hiç okumadığı için kalıp gevşek tutulur;
# gerçek soru olup olmadığına yine sıra doğrulaması karar verir.
QNUM_LOOSE_RE = re.compile(r"^\d{1,2}[.,)]?$")

SAME_MARGIN_TOL = 3.0  # pt: aynı marj sayılacak x0 salınımı
MAX_NUMBER_SKIP = 3  # metin katmanından hiç çıkmayan soru numarası için ileri bakma sınırı


def merge_margins(sorted_margins: list[float], slack: float) -> list[float]:
    """Birbirine slack'ten yakın marjları tek sütunda toplar. Numaralar
    noktaya göre sağa yaslı dizildiği için aynı sütun iki mod üretir
    ("1." tek haneli, "10." çift haneli ~7pt daha solda başlar); grubun
    en solu sütunun marjıdır. Karşılaştırma her zaman grubun İLK üyesine
    yapılır, böylece art arda gelen marjlar zincirleme birleşip sayfa
    genişliğinde sahte bir sütun oluşturamaz."""
    if not sorted_margins:
        return []
    groups = [sorted_margins[0]]
    for m in sorted_margins[1:]:
        if m - groups[-1] > slack:
            groups.append(m)
    return groups


def detect_columns(pages: list[Page], profile: Profile, subjects: dict,
                   furniture: set) -> list[tuple]:
    """Soru numarası ADAYLARININ kabul edileceği x pencerelerini belirler.

    Burada bilerek CÖMERT davranılır: bir sütun kitapçık boyunca yalnızca
    iki kez kullanılıyor olabilir (ör. sayfanın çoğu tam genişlik soruyken
    birkaç sayfada yan yana iki soru), bu yüzden "az görüldü" diye eleme
    yapılmaz — gerçek/sahte ayrımını sonraki aşamadaki 1,2,3... sıra
    doğrulaması yapar. Kırpma sınırları ise bu cömert listeden değil,
    doğrulamayı GEÇEN sorulardan türetilir (bkz. true_columns)."""
    xs = []
    for page in pages:
        if subjects.get(page.index) is None:
            continue
        for w in page.words:
            if in_footer_band(w, page.height, profile) or is_furniture(w, furniture):
                continue
            if profile.qnum_pattern.match(w.text):
                xs.append(w.x0)
    if not xs:
        return [(0.0, 0.0)]

    xs.sort()
    clusters: list[list[float]] = [[xs[0]]]
    for x in xs[1:]:
        if x - clusters[-1][0] <= SAME_MARGIN_TOL:
            clusters[-1].append(x)
        else:
            clusters.append([x])

    margins = merge_margins(sorted(min(c) for c in clusters), profile.margin_slack)
    return [(m, m + profile.margin_slack) for m in margins]


def column_index(x0: float, ranges: list[tuple], profile: Profile) -> int | None:
    """x0'ı en yakın sütun aralığına eşler; hiçbirine uymuyorsa None döner
    (gerçek soru numarası değildir)."""
    for i, (lo, hi) in enumerate(ranges):
        if lo - 1.0 <= x0 <= hi + 2.0:
            return i
    return None


def find_question_candidates(page: Page, ranges: list[tuple], profile: Profile,
                             furniture: set):
    """Sayfadaki numara kalıbındaki kelimeleri okuma sırasına (sütun sırası,
    her sütun içinde üstten alta) göre döndürür."""
    cands = []
    for w in page.words:
        if in_footer_band(w, page.height, profile) or is_furniture(w, furniture):
            continue
        m = profile.qnum_pattern.match(w.text)
        if not m:
            continue
        col = column_index(w.x0, ranges, profile)
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


def extract_questions(pages: list[Page], profile: Profile,
                      tight_bottom: bool = True) -> list[Question]:
    """Sayfa sayfa ilerleyip 1'den başlayan artan diziyi kuran adayları
    gerçek soru kabul eder; ders değişiminde numaralandırma 1'e döner.
    Ders başlığı olmayan sayfalar (kapak, cevap anahtarı, kurallar) ve
    talimat satırları baştan elenir.

    Sayfa İÇİNDE sabit bir okuma sırası VARSAYILMAZ: bazı yayınevleri iki
    sütunu sütun-öncelikli numaralar (sol sütunun tamamı, sonra sağ),
    bazıları satır-öncelikli (sol üst, sağ üst, sonra alt satır). Bu yüzden
    sayfadaki adaylar arasından her adımda "sıradaki beklenen numara"
    aranır; sıralama yalnızca eşit adaylar arasında karar vermek için
    kullanılır."""
    furniture = find_repeating_furniture(pages)
    subjects = page_subjects(pages, profile, furniture)
    starts = detect_columns(pages, profile, subjects, furniture)

    # Aynı numara sayfada birden çok yerde geçebilir (soru içi alt madde).
    # Gerçek soru numarası, kitapçık boyunca sık kullanılan bir sol marja
    # oturur; bu yüzden eşitlikte marj frekansı yüksek olan tercih edilir.
    margin_freq: dict = {}
    per_page: dict = {}
    for page in pages:
        if subjects.get(page.index) is None:
            continue
        cands = []
        for col, y0, number, w in find_question_candidates(page, starts, profile, furniture):
            nxt = next_word_on_line(page, w)
            # Sondaki noktalama ayıklanır: talimat satırı "2. Cevaplarınızı,"
            # biçiminde de gelebiliyor.
            if nxt is not None and nxt.text.rstrip(",.;:") in profile.preamble_next_words:
                continue
            cands.append((col, y0, number, w))
            margin_freq[round(w.x0)] = margin_freq.get(round(w.x0), 0) + 1
        per_page[page.index] = cands

    def preference(cand):
        col, y0, number, w = cand
        return (-margin_freq.get(round(w.x0), 0), col, y0)

    # Sık kullanılan sol marjlar = gerçek sütun başlangıçları. Atlamalı
    # eşleşmede yalnızca bu marjlara oturan adaylar kabul edilir, böylece
    # soru içi alt madde numaraları diziyi kaçırmaz.
    total_cands = sum(len(v) for v in per_page.values())
    strong_margins = {
        m for m, f in margin_freq.items()
        if f >= max(3, int(total_cands * 0.08))
    }

    def find_next(remaining, target):
        """Sıradaki soruyu ara. Bir numara hiç çıkarılamamış olabilir
        (ör. o soru bozuk gömülü fontla ya da görsel olarak basılmış);
        bu durumda dizinin geri kalanını kaybetmemek için birkaç numara
        ileriye bakılır — ama atlanarak varılan aday, gerçek bir sütun
        marjına oturmuyorsa kabul edilmez."""
        exact = [c for c in remaining if c[2] == target]
        if exact:
            return min(exact, key=preference), target
        for ahead in range(1, MAX_NUMBER_SKIP + 1):
            nxt = [
                c for c in remaining
                if c[2] == target + ahead and round(c[3].x0) in strong_margins
            ]
            if nxt:
                return min(nxt, key=preference), target + ahead
        return None, target

    def run_sequence(allowed_margins: list[float] | None) -> list:
        """Dizi doğrulamasını bir kez çalıştırır. allowed_margins verilirse
        yalnızca o marjlara oturan adaylar değerlendirilir."""
        def usable(cand):
            if allowed_margins is None:
                return True
            x = cand[3].x0
            return any(m - 1.0 <= x <= m + profile.margin_slack for m in allowed_margins)

        out, expected, last_subject = [], 1, None
        for page in pages:
            subject = subjects.get(page.index)
            if subject is None:
                continue
            remaining = [c for c in per_page.get(page.index, []) if usable(c)]
            while True:
                # Yeni ders başlıyorsa numaralandırma 1'den yeniden başlar.
                target = 1 if subject != last_subject else expected
                best, target = find_next(remaining, target)
                if best is None:
                    break
                remaining.remove(best)
                col, y0, number, w = best
                out.append((page.index, col, y0, number, w, subject))
                expected = target + 1
                last_subject = subject
        return out

    # 1. geçiş: kısıtsız. Bu geçiş sütun marjlarının NEREDE olduğunu öğrenir.
    first_pass = run_sequence(None)

    # Öğrenilen marjlardan yalnızca birden çok soruyla desteklenenler gerçek
    # sütundur. Soru gövdesi içindeki numaralı alt madde listeleri ("1. 2.
    # 3.") sütun marjından içeride durur ve yalnızca birkaç kez denk gelir;
    # bu eleme onları dışarıda bırakır.
    groups: dict = {}
    for m in merge_margins(sorted(w.x0 for *_, w, _ in first_pass), profile.margin_slack):
        groups[m] = sum(
            1 for *_, w, _ in first_pass if m - 1.0 <= w.x0 <= m + profile.margin_slack
        )
    min_support = max(2, int(len(first_pass) * 0.05))
    allowed = [m for m, c in groups.items() if c >= min_support]

    # 2. geçiş: yalnızca gerçek sütun marjlarındaki adaylarla.
    accepted = run_sequence(allowed) if allowed else first_pass

    CONTENT_PAD = 10.0  # son satırın altına bırakılan küçük nefes payı

    # Kırpma sınırları, aday penceresinden değil DOĞRULANMIŞ sorulardan
    # türetilir; böylece soru içi alt madde numaraları kırpmayı daraltamaz.
    # Sütunlar SAYFA BAZINDA hesaplanır: uzun kitapçıklarda bölümler
    # (Türkçe / Matematik / İngilizce) farklı sayfa marjları kullanabiliyor,
    # tek bir doküman geneli sütun listesi bunları yanlış böler.
    page_margins: dict = {}
    for p, _c, _y, _n, wd, _s in accepted:
        page_margins.setdefault(p, []).append(wd.x0)
    page_cols = {
        p: merge_margins(sorted(xs), profile.margin_slack)
        for p, xs in page_margins.items()
    }

    def column_of(page_index: int, word: Word) -> int:
        idx = 0
        for i, m in enumerate(page_cols[page_index]):
            if word.x0 >= m - 1.0:
                idx = i
        return idx

    questions: list[Question] = []
    pages_by_index = {p.index: p for p in pages}
    placed = [(p, column_of(p, wd), y, wd) for p, _c, y, _n, wd, _s in accepted]

    # Bir sayfada hangi soruların tam genişlik olduğunu ÖNCE belirle: bir
    # soru, dikey bandında başka bir sütunda soru yoksa tam genişliktedir.
    # (Bazı yayınevleri aynı sayfada tam genişlik bir soruyla yan yana iki
    # soruyu birlikte kullanıyor.)
    def band_end(page_index, tcol, y0, page_height):
        below = [
            n_y0 for n_page, n_col, n_y0, _ in placed
            if n_page == page_index and n_col == tcol and n_y0 > y0 + 1
        ]
        return min(below) - 2 if below else page_height - 20

    is_full = []
    for (page_index, tcol, y0, _wd) in placed:
        page = pages_by_index[page_index]
        pre_end = band_end(page_index, tcol, y0, page.height)
        shares_band = any(
            n_page == page_index and n_col != tcol and y0 - 20 <= n_y0 < pre_end
            for n_page, n_col, n_y0, _ in placed
        )
        is_full.append(not shares_band)

    for i, (page_index, col, y0, number, w, subject) in enumerate(accepted):
        page = pages_by_index[page_index]
        cols = page_cols[page_index]
        tcol = placed[i][1]

        if is_full[i]:
            x0, x1 = 0.0, page.width
        else:
            x0 = max(cols[tcol] - 6, 0.0)
            x1 = cols[tcol + 1] - 4 if tcol + 1 < len(cols) else page.width

        # Dikey üst sınır: BU sorunun altındaki, yatayda ÖRTÜŞEN en yakın
        # soru. Aynı sütundaki sorular her zaman örtüşür; tam genişlik bir
        # soru ise sayfanın tamamını kapladığı için hangi sütunda olursa
        # olsun üstündeki soruyu keser. Numaralandırma sırası sayfadaki
        # dikey sıradan farklı olabildiği için (satır-öncelikli düzenler)
        # listedeki sıraya değil konuma bakılır.
        below = [
            n_y0
            for j, (n_page, n_col, n_y0, _) in enumerate(placed)
            if n_page == page_index and n_y0 > y0 + 1
            and (n_col == tcol or is_full[j] or is_full[i])
        ]
        upper_bound = min(below) - 2 if below else page.height - 20

        top = max(y0 - 14, 30)
        if tight_bottom:
            # Metin katmanı eksiksiz olduğunda içeriğin gerçekten bittiği
            # yere kadar kırpılır (aradaki boş alan atılır).
            content_bottom = top
            for cw in page.words:
                if is_boilerplate_word(cw, page.height, profile):
                    continue
                if x0 - 1 <= cw.x0 < x1 and top <= cw.y0 < upper_bound:
                    content_bottom = max(content_bottom, cw.y1)
            y1 = min(content_bottom + CONTENT_PAD, upper_bound)
        else:
            # OCR'da kelime kapsamı eksiksiz değildir; son satır (çoğu kez
            # şıklar) hiç okunmamış olabilir. Böyle bir durumda "içerik
            # burada bitti" demek şıkları kesmek demek olur — bu yüzden
            # bandın tamamı alınır. Fazla boşluk zararsız, eksik şık değil.
            y1 = upper_bound

        questions.append(
            Question(number=number, subject=subject or "bilinmiyor", page=page_index,
                     x0=x0, y0=top, x1=x1, y1=y1)
        )
    return questions


UNRELIABLE_MISSING_RATIO = 0.5  # bu orandan fazlası eksikse çıktı güvenilmez sayılır


def extraction_report(questions: list[Question]) -> dict:
    """Ders bazında hangi soruların yakalandığını ve dizide hangi
    numaraların eksik kaldığını çıkarır. Eksikler, o sorunun numarasının
    metin katmanından hiç okunamadığı anlamına gelir (bozuk gömülü font
    ya da eğriye çevrilmiş/görsel olarak basılmış metin)."""
    by_subject: dict = {}
    for q in questions:
        by_subject.setdefault(q.subject, set()).add(q.number)
    report = {}
    for subject, nums in by_subject.items():
        highest = max(nums)
        missing = sorted(set(range(1, highest + 1)) - nums)
        report[subject] = {
            "bulunan": len(nums),
            "en_yuksek_numara": highest,
            "eksik": missing,
        }
    return report


def render_pages(pdf_path: Path, out_dir: Path, dpi: int = 300) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(dpi), str(pdf_path), str(out_dir / "page")],
        check=True,
    )
    return sorted(out_dir.glob("page-*.png"))


# ───────────────────────── Metin kaynakları (backend) ─────────────────────
#
# Motorun tamamı (sütun tespiti, sıra doğrulama, kırpma) yalnızca
# "konumlu kelime" listesi üzerinde çalışır. Bu yüzden kelimelerin NEREDEN
# geldiği değiştirilebilir: PDF'in kendi metin katmanı ya da sayfa
# görüntüsü üzerinde OCR. Eğriye çevrilmiş / bozuk fontlu kitapçıklar
# yalnızca bu kaynağı değiştirerek işlenebilir hale gelir.


def words_from_pdf(pdf_path: Path, out_dir: Path) -> list[Page]:
    """PDF'in gömülü metin katmanı (hızlı, ücretsiz, birebir doğru)."""
    bbox_path = out_dir / "bbox.html"
    subprocess.run(["pdftotext", "-bbox", str(pdf_path), str(bbox_path)], check=True)
    return parse_bbox(bbox_path)


MIN_OCR_CONF = 45.0        # gövde metni için asgari güven
MIN_OCR_NUMBER_CONF = 70.0  # soru numarası için: yanlış numara diziyi bozar


def _tesseract_tsv(image: Path, lang: str, psm: str, scale: float,
                   dx: float = 0.0, dy: float = 0.0,
                   min_conf: float = MIN_OCR_CONF) -> list[Word]:
    proc = subprocess.run(
        ["tesseract", str(image), "stdout", "-l", lang, "--psm", psm, "tsv"],
        check=True, capture_output=True, text=True,
    )
    words: list[Word] = []
    for line in proc.stdout.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 12:
            continue
        left, top, w, h = (float(parts[6]), float(parts[7]),
                           float(parts[8]), float(parts[9]))
        conf, text = parts[10], parts[11].strip()
        if not text or conf in ("-1", ""):
            continue
        try:
            if float(conf) < min_conf:
                continue
        except ValueError:
            continue
        words.append(Word(left * scale + dx, top * scale + dy,
                          (left + w) * scale + dx, (top + h) * scale + dy,
                          text, float(conf)))
    return words


NIM_OCR_URL = "https://ai.api.nvidia.com/v1/cv/nvidia/nemoretriever-ocr-v1"


def words_from_nim(page_images: list[Path], dpi: int, api_key: str,
                   url: str = NIM_OCR_URL, min_conf: float = 0.5) -> list[Page]:
    """NVIDIA NIM OCR (nemoretriever-ocr-v1 / paddleocr) ile kelime + konum.

    Tesseract ile aynı sözleşmeyi döndürür (PDF punto'suna çevrilmiş Word
    listesi), bu yüzden motorun geri kalanı değişmeden çalışır. NIM'in
    tanıma doğruluğu tesseract'tan yüksek olduğu için özellikle eğriye
    çevrilmiş / süslü fontlu kitapçıklarda daha az soru kaçar.

    Kullanım:
        export NVIDIA_API_KEY=nvapi-...
        crop_questions(pdf, out, profile, source="nim")

    NOT: Bu ortamdan NVIDIA uçlarına ağ erişimi kapalı olduğu için istek
    biçimi belgelenen sözleşmeye göre yazıldı, canlı doğrulanamadı. İlk
    çalıştırmada yanıt şeması farklı gelirse `_nim_detections` içindeki
    alan adları tek noktadan güncellenir."""
    import base64
    import urllib.request

    scale = 72.0 / dpi
    pages: list[Page] = []
    for i, img_path in enumerate(page_images, start=1):
        with Image.open(img_path) as im:
            width, height = im.width * scale, im.height * scale
            px_w, px_h = im.width, im.height
        payload = json.dumps({
            "input": [{
                "type": "image_url",
                "url": "data:image/png;base64," +
                       base64.b64encode(img_path.read_bytes()).decode(),
            }]
        }).encode()
        req = urllib.request.Request(
            url, data=payload,
            headers={"Authorization": f"Bearer {api_key}",
                     "Accept": "application/json",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read())

        page = Page(index=i, width=width, height=height)
        page.words = _nim_detections(body, px_w, px_h, scale, min_conf)
        pages.append(page)
    return pages


def _nim_detections(body: dict, px_w: int, px_h: int, scale: float,
                    min_conf: float) -> list[Word]:
    """NIM yanıtındaki metin kutularını Word'e çevirir. Koordinatlar
    belgelenen biçimde [0,1] aralığında normalize gelir; 1'den büyük
    değerler görülürse piksel kabul edilip öyle ölçeklenir."""
    out: list[Word] = []
    data = body.get("data") or body.get("predictions") or []
    for item in data:
        for det in (item.get("text_detections") or item.get("detections") or []):
            text = (det.get("text") or
                    (det.get("text_prediction") or {}).get("text") or "").strip()
            conf = float(det.get("confidence", det.get("score", 1.0)))
            if not text or conf < min_conf:
                continue
            poly = (det.get("bounding_box") or {}).get("points") or det.get("polygon")
            if not poly:
                continue
            xs = [float(p[0] if isinstance(p, (list, tuple)) else p["x"]) for p in poly]
            ys = [float(p[1] if isinstance(p, (list, tuple)) else p["y"]) for p in poly]
            if max(xs) <= 1.0 and max(ys) <= 1.0:      # normalize -> piksel
                xs = [x * px_w for x in xs]
                ys = [y * px_h for y in ys]
            out.append(Word(min(xs) * scale, min(ys) * scale,
                            max(xs) * scale, max(ys) * scale,
                            text, conf * 100.0))
    return out


def column_left_edges(pages: list[Page], max_edges: int = 4) -> list[float]:
    """Gövde metninin sütun sol kenarları. Sütunlarda satırların hemen
    hepsi tam marjdan başladığı için bu konumlar x0 histogramının en güçlü
    tepeleridir."""
    counts: dict = {}
    for p in pages:
        for w in p.words:
            counts[round(w.x0)] = counts.get(round(w.x0), 0) + 1
    if not counts:
        return []
    total = sum(counts.values())
    peaks = sorted(x for x, n in counts.items() if n >= max(5, total * 0.02))
    edges: list[float] = []
    for x in peaks:
        if not edges or x - edges[-1] > 25:
            edges.append(float(x))
    return edges[:max_edges]


# Soru numarası, gövde metninin SOLUNDA asılı girintide durur (gövde
# "54pt"den başlıyorsa numara ~"37pt"dedir). Bu yüzden şerit, tespit edilen
# gövde kenarından belirgin biçimde sola taşar.
STRIP_LEFT_PAD = 34.0
STRIP_RIGHT_PAD = 40.0


def words_from_tesseract(page_images: list[Path], dpi: int, lang: str = "tur") -> list[Page]:
    """Yerel OCR (tesseract). Sayfa görüntülerinden kelime + konum çıkarır;
    koordinatlar piksel'den PDF punto'suna çevrilir, böylece motorun geri
    kalanı PDF metin katmanıyla aynı şekilde çalışır.

    İki geçişlidir. Tam sayfa taraması gövde metnini verir ama soru
    numaralarını sık kaçırır: numara, grafiklerin ortasında tek başına
    duran küçük/renkli bir öğe olduğu için sayfa analizi onu eler. Bu
    yüzden ikinci geçişte sütun marjlarındaki dar şeritler ayrıca taranır
    (dar şeritte rakam, çevresindeki grafiklerle yarışmadığı için güvenle
    okunur)."""
    scale = 72.0 / dpi
    pages: list[Page] = []
    for i, img_path in enumerate(page_images, start=1):
        with Image.open(img_path) as im:
            width, height = im.width * scale, im.height * scale
        page = Page(index=i, width=width, height=height)
        # Numara biçimli belirteçlerde eşik daha yüksek: yanlış okunan tek
        # bir rakam, sıra doğrulamasını yanlış soruya kilitleyebiliyor.
        page.words = [
            w for w in _tesseract_tsv(img_path, lang, "3", scale)
            if not QNUM_LOOSE_RE.match(w.text) or w.conf >= MIN_OCR_NUMBER_CONF
        ]
        pages.append(page)

    edges = column_left_edges(pages)
    if not edges:
        return pages

    px = dpi / 72.0
    strip_dir = page_images[0].parent / "_strips"
    strip_dir.mkdir(exist_ok=True)
    for page, img_path in zip(pages, page_images):
        with Image.open(img_path) as im:
            for k, edge in enumerate(edges):
                left = max(int((edge - STRIP_LEFT_PAD) * px), 0)
                right = min(int((edge + STRIP_RIGHT_PAD) * px), im.width)
                if right - left < 10:
                    continue
                strip_path = strip_dir / f"p{page.index:03d}_c{k}.png"
                im.crop((left, 0, right, im.height)).save(strip_path)
                for w in _tesseract_tsv(strip_path, lang, "6", scale,
                                        dx=left * scale,
                                        min_conf=MIN_OCR_NUMBER_CONF):
                    if not QNUM_LOOSE_RE.match(w.text):
                        continue
                    # Profiller "12." biçimini bekler; OCR noktayı bazen
                    # düşürüyor ya da virgül okuyor -> tek biçime getir.
                    w.text = w.text.rstrip(".,)") + "."
                    already = any(
                        abs(o.x0 - w.x0) < 6 and abs(o.y0 - w.y0) < 6
                        for o in page.words
                    )
                    if not already:
                        page.words.append(w)
    return pages


def missing_ratio(report: dict) -> tuple[int, int]:
    total_expected = sum(r["en_yuksek_numara"] for r in report.values())
    total_missing = sum(len(r["eksik"]) for r in report.values())
    return total_missing, total_expected


def crop_questions(pdf_path: Path, out_dir: Path, profile: Profile = MEB_LGS_PROFILE,
                   dpi: int = 300, source: str = "auto", ocr_lang: str = "tur"):
    """source:
    - "pdf"  : yalnızca gömülü metin katmanı
    - "ocr"  : yalnızca yerel OCR (tesseract)
    - "nim"  : yalnızca NVIDIA NIM OCR (NVIDIA_API_KEY gerekir)
    - "auto" : önce PDF metni; sonuç yetersizse (eğriye çevrilmiş yazı,
               bozuk font, taranmış sayfa) OCR'a düşer. NVIDIA_API_KEY
               tanımlıysa OCR olarak NIM, değilse tesseract kullanılır.
    """
    import os

    api_key = os.environ.get("NVIDIA_API_KEY")
    out_dir.mkdir(parents=True, exist_ok=True)
    render_dir = out_dir / "_pages"
    page_images = render_pages(pdf_path, render_dir, dpi=dpi)

    def attempt(kind):
        if kind == "pdf":
            pages = words_from_pdf(pdf_path, out_dir)
        elif kind == "nim":
            if not api_key:
                raise RuntimeError(
                    "NIM OCR için NVIDIA_API_KEY ortam değişkeni gerekli."
                )
            pages = words_from_nim(page_images, dpi, api_key)
        else:
            pages = words_from_tesseract(page_images, dpi, ocr_lang)
        if not any(p.words for p in pages):
            return None, {}, kind
        qs = extract_questions(pages, profile, tight_bottom=(kind == "pdf"))
        return qs, extraction_report(qs), kind

    fallback = "nim" if api_key else "ocr"
    attempts = {"pdf": ["pdf"], "ocr": ["ocr"], "nim": ["nim"],
                "auto": ["pdf", fallback]}[source]
    questions, report, used = None, {}, None
    for kind in attempts:
        qs, rep, k = attempt(kind)
        miss, exp = missing_ratio(rep) if rep else (1, 1)
        if qs and miss <= exp * UNRELIABLE_MISSING_RATIO:
            questions, report, used = qs, rep, k
            break
        # elde edilen en iyi sonucu sakla (hepsi başarısızsa raporlamak için)
        if questions is None or (rep and miss < missing_ratio(report)[0]):
            questions, report, used = qs, rep, k

    miss, exp = missing_ratio(report) if report else (1, 1)
    if not questions or miss > exp * UNRELIABLE_MISSING_RATIO:
        raise RuntimeError(
            f"Soru çıkarılamadı ({miss}/{exp} soru numarası okunamadı; "
            f"denenen kaynak: {', '.join(attempts)}). Kısmi/yanlış kırpma "
            "üretmemek için işlem durduruldu."
        )
    if used != "pdf":
        engine = "NIM OCR" if used == "nim" else "yerel OCR (tesseract)"
        print(f"BİLGİ: PDF metin katmanı yetersizdi, {engine} ile çıkarıldı.",
              file=sys.stderr)

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

    for subject, r in sorted(report.items()):
        if r["eksik"]:
            print(
                f"UYARI: {subject} — {r['en_yuksek_numara']} sorudan "
                f"{', '.join(map(str, r['eksik']))} numaralı soru(lar) "
                "metin katmanından okunamadı, kırpılmadı.",
                file=sys.stderr,
            )
    (out_dir / "rapor.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
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
