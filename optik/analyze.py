#!/usr/bin/env python3
"""Optik sonuçlarını çözümler, yanlışları öğrenci bazında dosyalar ve
zayıf konulardan özel deneme üretir.

Girdi olarak iki CSV bekler (varsayılan biçim; sütun adları sabittir,
sıra önemsizdir):

  cevap_anahtari.csv
      ders,soru,dogru[,kazanim]
      matematik,1,D,Cebirsel ifadeler

  ogrenci_cevaplari.csv
      ogrenci_no,ders,soru,isaret[,ogrenci_ad]
      1234,matematik,1,B,Ali Yılmaz
      # isaret boş bırakılırsa soru BOŞ sayılır

Soru görselleri, crop_booklet.py çıktısındaki `crops/` klasöründen
`<ders>_soru<NN>.png` adıyla okunur; ayrıca manifest gerekmez.

Kullanım:
    python3 analyze.py crops/ cevap_anahtari.csv ogrenci_cevaplari.csv ./analiz

Üretilenler:
    analiz/ozet.csv                     ders bazında doğru/yanlış/boş/net
    analiz/kazanim_sinif.csv            sınıfça en çok yanlışlanan kazanımlar
    analiz/<ogrenci_no>/rapor.json      öğrencinin ayrıntılı dökümü
    analiz/<ogrenci_no>/yanlislar/      yanlış yaptığı soruların görselleri
    analiz/<ogrenci_no>/ozel_deneme.pdf zayıf olduğu sorulardan deneme

Not: LGS'de yanlış doğruyu götürmez, bu yüzden net = doğru sayısıdır.
Farklı bir kurala geçilecekse `net()` tek noktadan değiştirilir.
"""
import csv
import json
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

# A4, 150 dpi — yazdırılabilir özel deneme sayfası
PAGE_W, PAGE_H = 1240, 1754
PAGE_MARGIN = 50
GAP = 30


@dataclass
class Result:
    subject: str
    number: int
    marked: str
    correct: str
    topic: str = ""

    @property
    def state(self) -> str:
        if not self.marked:
            return "bos"
        return "dogru" if self.marked == self.correct else "yanlis"


@dataclass
class Student:
    no: str
    name: str = ""
    results: list = field(default_factory=list)


def _norm(s: str) -> str:
    return (s or "").strip()


def read_key(path: Path) -> dict:
    """(ders, soru) -> (dogru_sik, kazanim)"""
    key = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            subject = _norm(row.get("ders")).lower()
            number = _norm(row.get("soru"))
            if not subject or not number.isdigit():
                continue
            key[(subject, int(number))] = (
                _norm(row.get("dogru")).upper(),
                _norm(row.get("kazanim")),
            )
    return key


def read_answers(path: Path, key: dict) -> list[Student]:
    students: dict = {}
    unknown = set()
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            no = _norm(row.get("ogrenci_no"))
            subject = _norm(row.get("ders")).lower()
            number = _norm(row.get("soru"))
            if not no or not subject or not number.isdigit():
                continue
            number = int(number)
            if (subject, number) not in key:
                unknown.add((subject, number))
                continue
            correct, topic = key[(subject, number)]
            student = students.setdefault(no, Student(no=no))
            name = _norm(row.get("ogrenci_ad"))
            if name and not student.name:
                student.name = name
            student.results.append(
                Result(subject, number, _norm(row.get("isaret")).upper(),
                       correct, topic)
            )
    for subject, number in sorted(unknown):
        print(f"UYARI: cevap anahtarında yok, atlandı: {subject} soru {number}",
              file=sys.stderr)
    return list(students.values())


def net(counts: dict) -> float:
    """LGS'de yanlış doğruyu götürmez."""
    return float(counts["dogru"])


def crop_path(crops_dir: Path, subject: str, number: int) -> Path | None:
    p = crops_dir / f"{subject}_soru{number:02d}.png"
    return p if p.exists() else None


WATERMARK_MIN_LIGHT = 180  # filigran açık tonludur; koyu metin bu eşiğin altında
WATERMARK_MIN_RED_BIAS = 8  # kırmızıya kayış; nötr griler ve mavi/yeşil grafikler elenmez


def remove_watermark(im: Image.Image) -> Image.Image:
    """Arka plandaki soluk kırmızı filigranı (MEB mührü) beyaza çeker.
    Filigran gerçek siyah metinle aynı katmanda basılı olduğu için
    renkten ayrılır: açık tonlu VE kırmızıya kaymış pikseller silinir.
    Siyah metin (koyu), mavi/yeşil grafik öğeleri (kırmızı baskın değil)
    ve beyaz zemin etkilenmez.

    Piksel piksel döngü yerine kanal işlemleri kullanılır; şekil
    kırpmalarının her birinde çalıştığı için hız önemli."""
    from PIL import ImageChops

    r, g, b = im.convert("RGB").split()
    min_gb = ImageChops.darker(g, b)
    min_all = ImageChops.darker(r, min_gb)

    light = min_all.point(lambda v: 255 if v >= WATERMARK_MIN_LIGHT else 0)
    # subtract 0'da kırpar: g-r == 0 ise r >= g demektir
    r_ge_g = ImageChops.subtract(g, r).point(lambda v: 255 if v == 0 else 0)
    r_ge_b = ImageChops.subtract(b, r).point(lambda v: 255 if v == 0 else 0)
    red_bias = ImageChops.subtract(r, min_gb).point(
        lambda v: 255 if v >= WATERMARK_MIN_RED_BIAS else 0)

    mask = light
    for part in (r_ge_g, r_ge_b, red_bias):
        mask = ImageChops.multiply(mask, part)

    out = im.convert("RGB")
    out.paste(Image.new("RGB", out.size, "white"), mask=mask.convert("L"))
    return out


def compose_test(images: list[Path], out_pdf: Path, title: str,
                 clean: bool = True) -> int:
    """Soru görsellerini A4 sayfalara dizip tek PDF yapar.

    Ölçek TÜM sorular için AYNIDIR. Her görseli tek tek sayfa genişliğine
    yaymak, dar kırpılmış (iki sütunlu) sorularla tam sayfa soruları
    farklı punto gösteriyordu; kitapçık gibi durması için tek bir ölçek
    kullanılır. Bir soru bölünmez, sığmıyorsa sonraki sayfaya geçer."""
    if not images:
        return 0
    usable_w = PAGE_W - 2 * PAGE_MARGIN
    usable_h = PAGE_H - 2 * PAGE_MARGIN

    loaded = []
    for p in images:
        with Image.open(p) as im:
            im = im.convert("RGB")
            loaded.append(remove_watermark(im.copy()) if clean else im.copy())

    # Tek ortak ölçek: en geniş soru sayfaya tam otursun, diğerleri de
    # aynı oranda küçülsün -> her soruda punto aynı.
    scale = min(1.0, usable_w / max(im.width for im in loaded))

    pages: list[Image.Image] = []
    canvas = Image.new("RGB", (PAGE_W, PAGE_H), "white")
    y = PAGE_MARGIN
    for im in loaded:
        w, h = int(im.width * scale), int(im.height * scale)
        if h > usable_h:  # tek başına sayfayı aşan çok uzun soru
            shrink = usable_h / h
            w, h = int(w * shrink), int(h * shrink)
        if y + h > PAGE_H - PAGE_MARGIN and y > PAGE_MARGIN:
            pages.append(canvas)
            canvas = Image.new("RGB", (PAGE_W, PAGE_H), "white")
            y = PAGE_MARGIN
        canvas.paste(im.resize((w, h), Image.LANCZOS), (PAGE_MARGIN, y))
        y += h + GAP
    pages.append(canvas)

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    pages[0].save(out_pdf, "PDF", resolution=150.0,
                  save_all=True, append_images=pages[1:], title=title)
    return len(pages)


def build_branded_test(picked: list[dict], out_pdf: Path, title: str,
                       pages_dir: Path) -> int:
    """Özel denemeyi markalı şablonla üretir: metne çevrilebilen sorular
    dizilebilir metin olarak, görsel ağırlıklı sorular tek parça olarak.
    Kırpılmış görselleri alt alta yığmaktan farkı, sayfa düzeninin bizde
    olması."""
    from render_template import build_html, render_pdf

    html_text = build_html(picked, title, "Yanlış yapılan sorulardan derlenmiştir",
                           pages_dir)
    render_pdf(html_text, out_pdf)
    return len(picked)


def analyse(crops_dir: Path, key_csv: Path, answers_csv: Path, out_dir: Path,
            questions: list[dict] | None = None, pages_dir: Path | None = None,
            include_blank: bool = False):
    key = read_key(key_csv)
    students = read_answers(answers_csv, key)
    if not students:
        raise RuntimeError("Öğrenci cevabı okunamadı — CSV sütun adlarını kontrol et.")

    out_dir.mkdir(parents=True, exist_ok=True)
    summary_rows = []
    topic_misses: dict = defaultdict(int)
    topic_totals: dict = defaultdict(int)
    missing_crops = set()

    for st in students:
        by_subject: dict = defaultdict(lambda: {"dogru": 0, "yanlis": 0, "bos": 0})
        wrong: list = []
        for r in sorted(st.results, key=lambda r: (r.subject, r.number)):
            by_subject[r.subject][r.state] += 1
            topic_key = (r.subject, r.topic or "(kazanım girilmemiş)")
            topic_totals[topic_key] += 1
            if r.state != "dogru":
                topic_misses[topic_key] += 1
            # Boş bırakılan soru da öğrencinin yapamadığı sorudur; tekrar
            # denemesine girmesi isteniyorsa include_blank açılır.
            if r.state == "yanlis" or (include_blank and r.state == "bos"):
                wrong.append(r)

        student_dir = out_dir / st.no
        wrong_dir = student_dir / "yanlislar"
        wrong_dir.mkdir(parents=True, exist_ok=True)
        images: list[Path] = []
        for r in wrong:
            src = crop_path(crops_dir, r.subject, r.number)
            if src is None:
                missing_crops.add((r.subject, r.number))
                continue
            dst = wrong_dir / src.name
            shutil.copyfile(src, dst)
            images.append(dst)

        out_pdf = student_dir / "ozel_deneme.pdf"
        title = f"{st.name or st.no} — Özel Deneme"
        if questions is not None and pages_dir is not None:
            lookup = {(q["ders"], q["soru"]): q for q in questions}
            picked = [lookup[(r.subject, r.number)] for r in wrong
                      if (r.subject, r.number) in lookup]
            page_count = build_branded_test(picked, out_pdf, title, pages_dir)
        else:
            page_count = compose_test(images, out_pdf, title)

        report = {
            "ogrenci_no": st.no,
            "ogrenci_ad": st.name,
            "dersler": {s: dict(c, net=net(c)) for s, c in by_subject.items()},
            "yanlis_sorular": [
                {"ders": r.subject, "soru": r.number, "isaret": r.marked,
                 "dogru": r.correct, "kazanim": r.topic}
                for r in wrong
            ],
            "ozel_deneme_sayfa": page_count,
        }
        (student_dir / "rapor.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        for subject, c in sorted(by_subject.items()):
            summary_rows.append({
                "ogrenci_no": st.no, "ogrenci_ad": st.name, "ders": subject,
                "dogru": c["dogru"], "yanlis": c["yanlis"], "bos": c["bos"],
                "net": net(c),
            })

    with (out_dir / "ozet.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "ogrenci_no", "ogrenci_ad", "ders", "dogru", "yanlis", "bos", "net"])
        writer.writeheader()
        writer.writerows(summary_rows)

    with (out_dir / "kazanim_sinif.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ders", "kazanim", "yanlis_bos", "toplam", "basarisizlik_yuzde"])
        for (subject, topic), miss in sorted(
                topic_misses.items(), key=lambda kv: -kv[1]):
            total = topic_totals[(subject, topic)]
            writer.writerow([subject, topic, miss, total,
                             round(100.0 * miss / total, 1) if total else 0])

    for subject, number in sorted(missing_crops):
        print(f"UYARI: kırpılmış görsel yok: {subject} soru {number}",
              file=sys.stderr)

    return len(students), len(summary_rows)


if __name__ == "__main__":
    args = sys.argv[1:]

    def take(flag):
        if flag in args:
            i = args.index(flag)
            value = args[i + 1]
            del args[i:i + 2]
            return value
        return None

    include_blank = "--bos" in args
    if include_blank:
        args.remove("--bos")
    questions_path = take("--sorular")
    pages_path = take("--pages")

    if len(args) < 4:
        print(__doc__)
        raise SystemExit(2)

    questions = (json.loads(Path(questions_path).read_text(encoding="utf-8"))
                 if questions_path else None)
    pages_dir = Path(pages_path) if pages_path else None
    if questions is not None and pages_dir is None:
        # şablon, görsel ağırlıklı soruları sayfa görüntüsünden kırpar
        pages_dir = Path(args[0]).parent / "_pages"

    n_students, n_rows = analyse(Path(args[0]), Path(args[1]), Path(args[2]),
                                 Path(args[3]), questions, pages_dir,
                                 include_blank)
    print(f"{n_students} öğrenci çözümlendi, {n_rows} ders satırı -> {args[3]}/")
