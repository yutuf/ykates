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


def compose_test(images: list[Path], out_pdf: Path, title: str) -> int:
    """Soru görsellerini A4 sayfalara dizip tek PDF yapar. Sayfa başına
    kaç soru sığdığı görsellerin yüksekliğine göre değişir; bir soru
    bölünmez, sığmıyorsa sonraki sayfaya geçer."""
    if not images:
        return 0
    pages: list[Image.Image] = []
    canvas = Image.new("RGB", (PAGE_W, PAGE_H), "white")
    y = PAGE_MARGIN
    usable = PAGE_W - 2 * PAGE_MARGIN

    for img_path in images:
        with Image.open(img_path) as im:
            im = im.convert("RGB")
            scale = min(1.0, usable / im.width)
            w, h = int(im.width * scale), int(im.height * scale)
            # tek başına sayfaya sığmayan çok uzun soruyu sayfaya sığdır
            if h > PAGE_H - 2 * PAGE_MARGIN:
                scale = (PAGE_H - 2 * PAGE_MARGIN) / im.height
                w, h = int(im.width * scale), int(im.height * scale)
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


def analyse(crops_dir: Path, key_csv: Path, answers_csv: Path, out_dir: Path):
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
            if r.state == "yanlis":
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

        page_count = compose_test(images, student_dir / "ozel_deneme.pdf",
                                  f"{st.name or st.no} — Özel Deneme")

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
    if len(sys.argv) < 5:
        print(__doc__)
        raise SystemExit(2)
    n_students, n_rows = analyse(Path(sys.argv[1]), Path(sys.argv[2]),
                                 Path(sys.argv[3]), Path(sys.argv[4]))
    print(f"{n_students} öğrenci çözümlendi, {n_rows} ders satırı -> {sys.argv[4]}/")
