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

BRAND = "Netçe"
BRAND_TAGLINE = "Kazanım düzeyinde ölçme ve kişiye özel deneme"
BRAND_COLOR = "#1F6FEB"

CSS = """
@page { size: A4; margin: 16mm 14mm 14mm; }
* { box-sizing: border-box; }
body {
  font: 10.5pt/1.55 "DejaVu Serif", Georgia, serif;
  color: #16181d; margin: 0;
}
header {
  display: flex; justify-content: space-between; align-items: flex-start;
  border-bottom: 2.5px solid ACCENT; padding-bottom: 9px; margin-bottom: 18px;
}
.brand { display: flex; gap: 9px; align-items: center; }
.mark {
  width: 27px; height: 27px; border-radius: 7px; background: ACCENT; color: #fff;
  font: 700 14pt/27px "DejaVu Sans", sans-serif; text-align: center;
}
.brand .name { font: 700 14pt/1.1 "DejaVu Sans", sans-serif; letter-spacing: -.3px; }
.brand .tag { font: 7.5pt/1.3 "DejaVu Sans", sans-serif; color: #6b7280; margin-top: 2px; }
header .doc { text-align: right; }
header .doc .kind {
  display: inline-block; background: ACCENT; color: #fff; border-radius: 3px;
  font: 700 7.5pt/1 "DejaVu Sans", sans-serif; padding: 4px 7px; letter-spacing: .4px;
}
header .meta { font: 8pt/1.95 "DejaVu Sans", sans-serif; color: #5b6270; margin-top: 6px; }
header .meta .line { display: inline-block; border-bottom: 1px dotted #9aa1ad; width: 108px; }

.q { break-inside: avoid; margin-bottom: 17px; display: flex; gap: 10px; }
.q .num {
  flex: 0 0 22px; height: 22px; border-radius: 50%;
  background: ACCENT; color: #fff;
  font: 700 9.5pt/22px "DejaVu Sans", sans-serif; text-align: center;
}
.q .body { flex: 1; }
.stem { margin: 2px 0 8px; text-align: justify; }
.opts { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 18px; }
.opt { display: flex; gap: 6px; font-size: 10pt; }
.opt .k { font-weight: 700; color: #3f4652; flex: 0 0 15px; }
.opts.wide { grid-template-columns: 1fr; }

.tag-cap {
  display: inline-block; background: #eef4ff; color: ACCENT;
  border: 1px solid #cddffb; border-radius: 3px;
  font: 700 6.8pt/1 "DejaVu Sans", sans-serif; letter-spacing: .3px;
  padding: 3px 6px; margin-bottom: 5px; text-transform: uppercase;
}
.fig { margin: 7px 0 9px; text-align: center; }
.fig img { max-width: 78%; max-height: 62mm; height: auto; }
.fig.whole { text-align: left; margin: 2px 0 4px; }
.fig.whole img { max-width: 100%; max-height: 210mm; }

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


def figure_data_uri(fig: dict, pages_dir: Path, dpi: int = 300,
                    pad: float = 12.0, clean: bool = True) -> str | None:
    """Şekli, kırpılmış sayfa görüntüsünden kesip base64 olarak gömer.
    Gömmek, HTML'in tek dosya olarak taşınabilmesini sağlar."""
    import base64
    from io import BytesIO

    from PIL import Image

    page_png = pages_dir / f"page-{fig['sayfa']:02d}.png"
    if not page_png.exists():
        page_png = pages_dir / f"page-{fig['sayfa']}.png"
    if not page_png.exists():
        return None
    scale = dpi / 72.0
    with Image.open(page_png) as im:
        box = (max(int((fig["x0"] - pad) * scale), 0),
               max(int((fig["y0"] - pad) * scale), 0),
               min(int((fig["x1"] + pad) * scale), im.width),
               min(int((fig["y1"] + pad) * scale), im.height))
        crop = im.crop(box).convert("RGB")
    if clean:
        from analyze import remove_watermark
        crop = remove_watermark(crop)
    buf = BytesIO()
    crop.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def build_html(questions: list[dict], title: str, subtitle: str,
               pages_dir: Path | None = None) -> str:
    blocks = []
    for i, q in enumerate(questions, start=1):
        opts = q.get("siklar") or {}
        figs_html = ""
        if pages_dir:
            uris = [figure_data_uri(f, pages_dir) for f in q.get("gorseller", [])]
            figs_html = "".join(
                f'<div class="fig"><img src="{u}" alt=""></div>'
                for u in uris if u
            )
        longest = max((len(v) for v in opts.values()), default=0)
        wide = " wide" if longest > 38 else ""
        opt_html = "".join(
            f'<div class="opt"><span class="k">{k})</span>'
            f"<span>{to_html(v)}</span></div>"
            for k, v in sorted(opts.items())
        )
        # Demo/sunum için isteğe bağlı yetenek etiketi
        tag = q.get("etiket")
        tag_html = f'<div class="tag-cap">{html.escape(tag)}</div>' if tag else ""
        if q.get("mod") == "gorsel" and q.get("tam_kirpim") and pages_dir:
            # Görsel ağırlıklı soru: metne ayrıştırmak yerine tek parça
            # taşınır. Şekil ile etiketleri birbirinden ayırmaya çalışmak
            # her ikisini de bozuyordu; bütün hâlinde alınca soru
            # basıldığı gibi doğru kalıyor, sayfa düzeni yine bizde.
            uri = figure_data_uri(q["tam_kirpim"], pages_dir, pad=2.0)
            body = (f'<div class="fig whole"><img src="{uri}" alt=""></div>'
                    if uri else "")
            blocks.append(
                f'<div class="q"><div class="num">{i}</div>'
                f'<div class="body">{tag_html}{body}</div></div>'
            )
            continue
        blocks.append(
            f'<div class="q"><div class="num">{i}</div><div class="body">'
            f'{tag_html}'
            f'<div class="stem">{to_html(q.get("govde", ""))}</div>'
            f'{figs_html}'
            f'<div class="opts{wide}">{opt_html}</div></div></div>'
        )
    css = CSS.replace("ACCENT", BRAND_COLOR)
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<title>{html.escape(title)}</title><style>{css}</style></head><body>
<header>
  <div class="brand">
    <div class="mark">{html.escape(BRAND[0])}</div>
    <div><div class="name">{html.escape(BRAND)}</div>
         <div class="tag">{html.escape(BRAND_TAGLINE)}</div></div>
  </div>
  <div class="doc">
    <span class="kind">{html.escape(title.upper())}</span>
    <div class="meta">Ad Soyad <span class="line"></span><br>
                      Sınıf / Tarih <span class="line"></span></div>
  </div>
</header>
{''.join(blocks)}
<footer><span>{html.escape(subtitle)} · {len(questions)} soru</span>
        <span>{html.escape(BRAND)}</span></footer>
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
    args = sys.argv[2:]
    pages_dir = None
    if "--pages" in args:
        i = args.index("--pages")
        pages_dir = Path(args[i + 1])
        args = args[:i] + args[i + 2:]
    questions: list[dict] = []
    for path in args:
        questions.extend(json.loads(Path(path).read_text(encoding="utf-8")))
    page = build_html(questions, "Özel Deneme",
                      "Yanlış yapılan sorulardan derlenmiştir", pages_dir)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    render_pdf(page, out_pdf)
    print(f"{len(questions)} soru -> {out_pdf}")
