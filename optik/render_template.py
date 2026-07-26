#!/usr/bin/env python3
"""Çıkarılan soru metnini HTML şablonuna döküp yazdırılabilir PDF üretir.

Kırpılmış ekran görüntüsü yerine METİN kullanıldığı için sayfa düzeni
tamamen bizim kontrolümüzde: punto, sütun, başlık, boşluk hepsi
değiştirilebilir. Şablonu değiştirmek için yalnızca CSS'e dokunmak yeterli.

    python3 render_template.py cikti.pdf soru1.json [soru2.json ...]

Matematik gösterimi tarayıcı eklentisi olmadan, salt CSS ile çizilir
(kök işareti + üst çizgi, üst/alt simge). Böylece internet ya da KaTeX
gibi bir kütüphane gerekmez.
"""
import html
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CHROME_CANDIDATES = [
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
]

SQRT_RE = re.compile(r"\\sqrt\{([^{}]*)\}")
SUP_RE = re.compile(r"\^\{([^{}]*)\}")
SUB_RE = re.compile(r"_\{([^{}]*)\}")

CSS = """
@page { size: A4; margin: 18mm 15mm; }
* { box-sizing: border-box; }
body {
  font: 10.5pt/1.55 "DejaVu Serif", Georgia, serif;
  color: #16181d; margin: 0;
}
header {
  display: flex; justify-content: space-between; align-items: flex-end;
  border-bottom: 2.5px solid #16181d; padding-bottom: 8px; margin-bottom: 20px;
}
header .title { font-size: 15pt; font-weight: 700; letter-spacing: -.2px; }
header .sub { font-size: 8.5pt; color: #5b6270; margin-top: 3px; }
header .meta { font-size: 8.5pt; color: #5b6270; text-align: right; line-height: 1.9; }
header .meta .line { display: inline-block; border-bottom: 1px dotted #9aa1ad; width: 120px; }

.q { break-inside: avoid; margin-bottom: 17px; display: flex; gap: 10px; }
.q .num {
  flex: 0 0 22px; height: 22px; border-radius: 50%;
  background: #16181d; color: #fff;
  font: 700 9.5pt/22px "DejaVu Sans", sans-serif; text-align: center;
}
.q .body { flex: 1; }
.stem { margin: 2px 0 8px; text-align: justify; }
.opts { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 18px; }
.opt { display: flex; gap: 6px; font-size: 10pt; }
.opt .k { font-weight: 700; color: #3f4652; flex: 0 0 15px; }
.opts.wide { grid-template-columns: 1fr; }

/* Kök işareti: √ + payın üstüne çizgi. Salt CSS, kütüphane yok. */
.sqrt { white-space: nowrap; }
.sqrt::before { content: "\\221A"; }
.sqrt > span { border-top: 1.1px solid currentColor; padding: 0 1px 0 1px; }
sup, sub { font-size: .72em; line-height: 0; }

footer { margin-top: 22px; border-top: 1px solid #ccd1d9; padding-top: 6px;
         font-size: 8pt; color: #79808d; display: flex; justify-content: space-between; }
"""


def to_html(text: str) -> str:
    """LaTeX benzeri işaretlemeyi HTML'e çevirir (önce kaçış, sonra
    biçimlendirme; böylece soru metnindeki < > karakterleri bozulmaz)."""
    out = html.escape(text)
    out = SQRT_RE.sub(lambda m: f'<span class="sqrt"><span>{m.group(1)}</span></span>', out)
    out = SUP_RE.sub(lambda m: f"<sup>{m.group(1)}</sup>", out)
    out = SUB_RE.sub(lambda m: f"<sub>{m.group(1)}</sub>", out)
    return out


def build_html(questions: list[dict], title: str, subtitle: str) -> str:
    blocks = []
    for i, q in enumerate(questions, start=1):
        opts = q.get("siklar") or {}
        longest = max((len(v) for v in opts.values()), default=0)
        wide = " wide" if longest > 38 else ""
        opt_html = "".join(
            f'<div class="opt"><span class="k">{k})</span>'
            f"<span>{to_html(v)}</span></div>"
            for k, v in sorted(opts.items())
        )
        blocks.append(
            f'<div class="q"><div class="num">{i}</div><div class="body">'
            f'<div class="stem">{to_html(q.get("govde", ""))}</div>'
            f'<div class="opts{wide}">{opt_html}</div></div></div>'
        )
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<title>{html.escape(title)}</title><style>{CSS}</style></head><body>
<header>
  <div><div class="title">{html.escape(title)}</div>
       <div class="sub">{html.escape(subtitle)}</div></div>
  <div class="meta">Ad Soyad: <span class="line"></span><br>
                    Tarih: <span class="line"></span></div>
</header>
{''.join(blocks)}
<footer><span>{len(questions)} soru</span><span>ykates</span></footer>
</body></html>"""


def render_pdf(html_text: str, out_pdf: Path) -> None:
    chrome = next((c for c in CHROME_CANDIDATES if Path(c).exists()), None)
    if chrome is None:
        raise RuntimeError("Chromium bulunamadı; PDF üretilemiyor.")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "sayfa.html"
        src.write_text(html_text, encoding="utf-8")
        subprocess.run(
            [chrome, "--headless", "--disable-gpu", "--no-sandbox",
             f"--user-data-dir={tmp}/profile",
             "--no-pdf-header-footer",
             f"--print-to-pdf={out_pdf}", src.as_uri()],
            check=True, capture_output=True, timeout=180,
        )


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    out_pdf = Path(sys.argv[1])
    questions: list[dict] = []
    for path in sys.argv[2:]:
        questions.extend(json.loads(Path(path).read_text(encoding="utf-8")))
    page = build_html(questions, "Özel Deneme", "Yanlış yapılan sorulardan derlenmiştir")
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    render_pdf(page, out_pdf)
    print(f"{len(questions)} soru -> {out_pdf}")
