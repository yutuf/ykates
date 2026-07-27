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
.fig.whole img { max-width: 100%; max-height: 215mm; height: auto; }

/* Kök işareti: √ + payın üstüne çizgi. Salt CSS, kütüphane yok. */
.sqrt { white-space: nowrap; }
.sqrt::before { content: "\\221A"; }
.sqrt > span { border-top: 1.1px solid currentColor; padding: 0 1px 0 1px; }
sup, sub { font-size: .72em; line-height: 0; }

footer { margin-top: 22px; border-top: 1px solid #ccd1d9; padding-top: 6px;
         font-size: 8pt; color: #79808d; display: flex; justify-content: space-between; }

/* Öğrenci karnesi — denemenin neden bu sorulardan kurulduğunu gösterir */
.rapor { break-inside: avoid; border: 1px solid #dfe3ea; border-radius: 5px;
         padding: 11px 13px; margin-bottom: 18px; background: #fafbfd; }
.rapor h2 { font: 700 9.5pt/1.2 "DejaVu Sans", sans-serif; margin: 0 0 8px;
            color: ACCENT; letter-spacing: .2px; text-transform: uppercase; }
.rapor table { width: 100%; border-collapse: collapse;
               font: 8.5pt/1.4 "DejaVu Sans", sans-serif; }
.rapor th { text-align: left; color: #6b7280; font-weight: 700;
            border-bottom: 1px solid #e3e7ee; padding: 3px 6px 5px; }
.rapor td { padding: 3px 6px; border-bottom: 1px solid #eef1f5; }
.rapor td.num { text-align: right; font-variant-numeric: tabular-nums; }
.rapor .zayif { margin-top: 9px; font: 8.5pt/1.5 "DejaVu Sans", sans-serif; }
.rapor .zayif b { color: #16181d; }
.rapor .chip { display: inline-block; background: #eef4ff; color: ACCENT;
               border: 1px solid #cddffb; border-radius: 3px;
               padding: 2px 6px; margin: 2px 4px 2px 0; font-size: 8pt; }

/* Cevap anahtarı — öğrenciye giden kopyada YOK, ayrı dosyada basılır */
.key { display: grid; grid-template-columns: repeat(6, 1fr); gap: 5px 10px;
       font: 9pt/1.5 "DejaVu Sans", sans-serif; }
.key .cell { border: 1px solid #e3e7ee; border-radius: 4px; padding: 5px 7px; }
.key .cell .n { color: #6b7280; font-size: 8pt; }
.key .cell .a { font-weight: 700; color: ACCENT; font-size: 11pt; }
.key .cell .k { display: block; color: #79808d; font-size: 6.8pt;
                line-height: 1.25; margin-top: 2px; }
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
    # Kaynaktaki soru numarasını sil: özel denemede sorular yeniden
    # sıralandığı için geçerli numara şablonun bastığı numaradır, ikisi
    # birden görünürse soru çift numaralı okunur.
    # Kaynak numarası ve bölüm sonu duyurusu ("MATEMATİK TESTİ BİTTİ.")
    # kırpma dikdörtgeninin içinde kalabiliyor; ikisi de soruya ait
    # olmadığı için beyazlatılır.
    blanks = [fig["numara_kutusu"]] if fig.get("numara_kutusu") else []
    blanks += fig.get("gizle", [])
    if blanks:
        from PIL import ImageDraw
        draw = ImageDraw.Draw(crop)
        for b in blanks:
            draw.rectangle(
                [int(b["x0"] * scale) - box[0] - 2, int(b["y0"] * scale) - box[1] - 2,
                 int(b["x1"] * scale) - box[0] + 2, int(b["y1"] * scale) - box[1] + 2],
                fill="white")
    buf = BytesIO()
    crop.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


SUBJECT_LABELS = {
    "matematik": "Matematik", "fen_bilimleri": "Fen Bilimleri",
    "turkce": "Türkçe", "inkilap": "T.C. İnkılap Tarihi",
    "din_kulturu": "Din Kültürü", "ingilizce": "Yabancı Dil",
}


def report_block(rapor: dict | None) -> str:
    """Denemenin başındaki karne: hangi derste kaç net, hangi kazanımlar
    zayıf. Bunsuz özel deneme "rastgele sorular" gibi duruyor; asıl
    satılan şey soruların DERLENME GEREKÇESİ."""
    if not rapor:
        return ""
    rows = "".join(
        f"<tr><td>{html.escape(SUBJECT_LABELS.get(s, s))}</td>"
        f'<td class="num">{c["dogru"]}</td><td class="num">{c["yanlis"]}</td>'
        f'<td class="num">{c["bos"]}</td><td class="num"><b>{c["net"]:g}</b></td></tr>'
        for s, c in sorted(rapor.get("dersler", {}).items())
    )
    weak = rapor.get("zayif_kazanimlar") or []
    chips = "".join(f'<span class="chip">{html.escape(k)} · {n}</span>'
                    for k, n in weak)
    weak_html = (f'<div class="zayif"><b>Tekrar gerektiren kazanımlar:</b><br>'
                 f"{chips}</div>") if chips else ""
    return (
        '<div class="rapor"><h2>Deneme sonucu</h2>'
        "<table><tr><th>Ders</th><th>Doğru</th><th>Yanlış</th>"
        "<th>Boş</th><th>Net</th></tr>" + rows + "</table>"
        + weak_html + "</div>"
    )


def answer_key_html(questions: list[dict]) -> str:
    """Öğretmen için cevap anahtarı. Numaralar denemenin SON sırasına göre
    verilir — sayfa doldurma sıralamayı değiştirdiği için anahtar, soru
    listesiyle birlikte üretilmek zorunda."""
    cells = []
    for i, q in enumerate(questions, start=1):
        kazanim = q.get("kazanim") or ""
        cells.append(
            f'<div class="cell"><span class="n">{i}.</span> '
            f'<span class="a">{html.escape(q.get("dogru", "—"))}</span>'
            f'<span class="k">{html.escape(kazanim)}</span></div>'
        )
    return f'<div class="key">{"".join(cells)}</div>'


def build_html(questions: list[dict], title: str, subtitle: str,
               pages_dir: Path | None = None, rapor: dict | None = None) -> str:
    blocks = [report_block(rapor)]
    for i, q in enumerate(questions, start=1):
        opts = q.get("siklar") or {}
        figs_html = ""
        # Soru kendi kitapçığının sayfa klasörünü taşıyorsa o kullanılır:
        # sayısal ve sözel kitapçıkların sayfa numaraları çakışıyor,
        # ortak bir klasör varsayılırsa yanlış sayfadan kırpılır.
        own = q.get("sayfa_klasoru")
        pages = Path(own) if own else pages_dir
        if pages:
            uris = [figure_data_uri(f, pages) for f in q.get("gorseller", [])]
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
        if q.get("mod") == "gorsel" and q.get("tam_kirpim") and pages:
            # Görsel ağırlıklı soru: metne ayrıştırmak yerine tek parça
            # taşınır. Şekil ile etiketleri birbirinden ayırmaya çalışmak
            # her ikisini de bozuyordu; bütün hâlinde alınca soru
            # basıldığı gibi doğru kalıyor, sayfa düzeni yine bizde.
            # pad=0: tam soru kırpımının sınırları içerikten zaten hassas
            # hesaplandı. Buraya pay eklemek üstbilgi ayraç çizgisini geri
            # çağırıyor (çizgi, soru numarasının ~2pt üstünde duruyor).
            uri = figure_data_uri(q["tam_kirpim"], pages, pad=0.0)
            # Gerçek boyutunda bas (pt -> mm), yüzdeyle esnetme. Yüzde
            # kullanılınca her kırpım kabın tamamına yayılıyor; genişliği
            # farklı sorular farklı punto ve farklı sol kenarla çıkıyordu.
            crop = q["tam_kirpim"]
            width_mm = (crop["x1"] - crop["x0"]) * 25.4 / 72.0
            body = (f'<div class="fig whole">'
                    f'<img src="{uri}" style="width:{width_mm:.1f}mm" alt=""></div>'
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


PAGE_H_PX = 297 / 25.4 * 96          # A4 yüksekliği (CSS px)
MARGIN_PX = (16 + 14) / 25.4 * 96    # @page üst + alt kenar boşluğu
PRINT_W_PX = (210 - 14 - 14) / 25.4 * 96   # @page içindeki yazı genişliği

# Ölçüm sayfası, BASKI genişliğine sabitlenir. Tarayıcı penceresi daha
# geniş olduğu için metin orada daha az sarıyor ve sorular olduğundan
# alçak ölçülüyordu; sayfalar bu yüzden taşıp fazladan sayfa açıyordu.
MEASURE_JS = """
<style>body { width: %.2fpx; }</style>
<script>
window.addEventListener('load', function () {
  var out = {header: 0, footer: 0, q: []};
  // Kenar boşlukları da yer kaplar; yalnızca kutu yüksekliğini almak
  // ilk sayfayı 18px, son sayfayı 22px eksik hesaplatıyordu.
  function outer(el, prop) {
    if (!el) return 0;
    return el.getBoundingClientRect().height +
           parseFloat(window.getComputedStyle(el)[prop] || 0);
  }
  out.header = outer(document.querySelector('header'), 'marginBottom');
  out.footer = outer(document.querySelector('footer'), 'marginTop');
  out.rapor = outer(document.querySelector('.rapor'), 'marginBottom');
  document.querySelectorAll('.q').forEach(function (el) {
    var s = window.getComputedStyle(el);
    out.q.push(el.getBoundingClientRect().height + parseFloat(s.marginBottom || 0));
  });
  var d = document.createElement('div');
  d.id = 'olcum';
  d.textContent = JSON.stringify(out);
  document.body.appendChild(d);
});
</script>
""" % PRINT_W_PX

MEASURE_RE = re.compile(r'<div id="olcum">(.*?)</div>', re.S)


def measure_heights(html_text: str) -> dict | None:
    """Soruların GERÇEK yüksekliklerini tarayıcıdan ölçer.

    Metin sorularının yüksekliği önceden kestirilemez (sarma, punto,
    şıkların bir mi iki sütuna sığdığı). Kestirimle sayfalamak, ya soruyu
    taşırır ya da boşluk bırakır; bu yüzden bir kez ölçüm turu atılır.
    Sonuç, sayfanın DOM'una yazılıp --dump-dom ile geri okunur."""
    chrome = next((c for c in CHROME_CANDIDATES if Path(c).exists()), None)
    if chrome is None:
        return None
    probe = html_text.replace("</body>", MEASURE_JS + "</body>")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "olcum.html"
        src.write_text(probe, encoding="utf-8")
        proc = subprocess.run(
            [chrome, "--headless", "--disable-gpu", "--no-sandbox",
             f"--user-data-dir={tmp}/profile", "--virtual-time-budget=8000",
             "--dump-dom", src.as_uri()],
            capture_output=True, text=True, timeout=240,
        )
    match = MEASURE_RE.search(proc.stdout)
    if not match:
        return None
    try:
        return json.loads(html.unescape(match.group(1)))
    except json.JSONDecodeError:
        return None


def _layout(order: list[int], heights: list[float],
            page_h: float, first_page_h: float) -> list[list[int]]:
    """Verilen sıranın hangi soruyu hangi sayfaya düşürdüğü."""
    pages: list[list[int]] = [[]]
    space = first_page_h
    for idx in order:
        if heights[idx] > space and pages[-1]:
            pages.append([])
            space = page_h
        pages[-1].append(idx)
        space -= heights[idx]
    return pages


def _page_count(order: list[int], heights: list[float], page_h: float,
                first_page_h: float, tail_h: float) -> int:
    """Sıranın kaç sayfa tuttuğu — alt bilgi son sayfaya sığmıyorsa +1."""
    pages = _layout(order, heights, page_h, first_page_h)
    cap = first_page_h if len(pages) == 1 else page_h
    slack = cap - sum(heights[i] for i in pages[-1])
    return len(pages) + (1 if slack < tail_h else 0)


def pack_order(heights: list[float], page_h: float, first_page_h: float,
               tail_h: float = 0.0) -> list[int]:
    """Soruları, sayfada boşluk kalmayacak biçimde sıralar.

    Sıradaki soru kalan boşluğa sığmıyorsa sayfayı yarım bırakıp geçmek
    yerine, sığan ilk sonraki soru öne alınır. Soru asla bölünmez; sadece
    sıra değişir ve özel denemede soru sırasının bir anlamı yoktur.

    `tail_h` alt bilgi şerididir: akışın en sonunda durduğu için yalnızca
    SON sayfada yer kaplar. Yer kalmazsa tarayıcı onu yeni bir sayfaya
    atıyor ve deneme boşuna bir sayfa uzuyordu; bu yüzden son sayfada
    yer açılana kadar oradan soru geri çekilir."""
    remaining = list(range(len(heights)))
    order: list[int] = []
    space = first_page_h
    while remaining:
        placed = None
        for idx in remaining:
            if heights[idx] <= space:
                placed = idx
                break
        if placed is None:              # hiçbiri sığmıyor -> yeni sayfa
            if space == page_h:         # boş sayfaya da sığmıyorsa tek başına koy
                placed = remaining[0]
                order.append(placed)
                remaining.remove(placed)
                space = page_h
                continue
            space = page_h
            continue
        order.append(placed)
        remaining.remove(placed)
        space -= heights[placed]

    if tail_h <= 0:
        return order

    # Son sayfada alt bilgiye yer aç: oradaki bir soruyu, önceki
    # sayfalardan birinin artığına taşı. Taşınacak soru bulunamazsa sıra
    # olduğu gibi kalır (o zaman alt bilgi zaten yeni sayfaya düşer).
    for _ in range(len(order)):
        pages = _layout(order, heights, page_h, first_page_h)
        if len(pages) == 1:
            used = sum(heights[i] for i in pages[0])
            if used + tail_h <= first_page_h:
                break
        slack = [page_h - sum(heights[i] for i in p) for p in pages]
        slack[0] = first_page_h - sum(heights[i] for i in pages[0])
        if slack[-1] >= tail_h:
            break
        moved = False
        for idx in sorted(pages[-1], key=lambda i: heights[i]):
            target = next((p for p in range(len(pages) - 1)
                           if slack[p] >= heights[idx]), None)
            if target is None:
                continue
            order.remove(idx)
            order.insert(order.index(pages[target][-1]) + 1, idx)
            moved = True
            break
        if not moved:
            break

    # Açgözlü sıralama nadiren özgün sıradan kötü çıkabiliyor (son sayfaya
    # yer açmak için yapılan taşıma bir sayfa daha açtırabilir). Kazanç
    # yoksa özgün sıra korunur — soru sırası boşuna karışmasın.
    if _page_count(order, heights, page_h, first_page_h, tail_h) >= \
            _page_count(list(range(len(heights))), heights, page_h,
                        first_page_h, tail_h):
        return list(range(len(heights)))
    return order


def build_packed_html(questions, title, subtitle, pages_dir, rapor=None):
    """Önce ölç, sonra boşluk kalmayacak sırayla diz. Ölçüm başarısız
    olursa özgün sıra korunur (tarayıcı yine soruyu bölmez, sadece
    sayfalar seyrek kalır).

    (html, sıralanmış_sorular) döndürür — cevap anahtarı bu sıraya göre
    basılmak zorunda, sayfa doldurma soruların sırasını değiştiriyor."""
    first = build_html(questions, title, subtitle, pages_dir, rapor)
    if len(questions) < 2:
        return first, list(questions)
    m = measure_heights(first)
    if not m or len(m.get("q", [])) != len(questions):
        return first, list(questions)
    usable = PAGE_H_PX - MARGIN_PX
    # Karne de ilk sayfada yer kaplar; hesaba katılmazsa ilk sayfa taşıp
    # deneme boşuna bir sayfa uzuyor.
    first_page = usable - m["header"] - m.get("rapor", 0.0)
    order = pack_order(m["q"], usable, first_page, m["footer"])
    if order == list(range(len(questions))):
        return first, list(questions)
    ordered = [questions[i] for i in order]
    return build_html(ordered, title, subtitle, pages_dir, rapor), ordered


def build_key_html(questions: list[dict], title: str, subtitle: str) -> str:
    """Cevap anahtarı — AYRI dosya. Öğrencinin eline geçen denemenin
    içine konamaz, ama öğretmen üretilen denemeyi okuyamazsa deneme
    kullanılamaz; şimdiye kadar eksik olan parça buydu."""
    css = CSS.replace("ACCENT", BRAND_COLOR)
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<title>{html.escape(title)}</title><style>{css}</style></head><body>
<header>
  <div class="brand">
    <div class="mark">{html.escape(BRAND[0])}</div>
    <div><div class="name">{html.escape(BRAND)}</div>
         <div class="tag">{html.escape(BRAND_TAGLINE)}</div></div>
  </div>
  <div class="doc"><span class="kind">CEVAP ANAHTARI</span>
    <div class="meta">{html.escape(subtitle)}</div></div>
</header>
{answer_key_html(questions)}
<footer><span>Öğretmen kopyası · {len(questions)} soru</span>
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
