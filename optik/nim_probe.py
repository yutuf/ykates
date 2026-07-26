#!/usr/bin/env python3
"""NIM OCR bağlantı/şema testi.

Tek bir sayfa görüntüsü gönderip HAM yanıtı ekrana ve dosyaya yazar,
sonra parser'ın o yanıttan kaç kelime çıkarabildiğini söyler.

    export NVIDIA_API_KEY=nvapi-...
    python3 optik/nim_probe.py sayfa.png

Çalışırsa: "N kelime ayrıştırıldı" görürsün, her şey hazır demektir.
Çalışmazsa: nim_response.json dosyası oluşur; onu paylaş, parser tek
noktadan (crop_booklet._nim_detections) ona göre düzeltilir.
"""
import json
import os
import sys
from pathlib import Path

from PIL import Image

from crop_booklet import NIM_OCR_URL, _nim_detections


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    image = Path(sys.argv[1])
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        print("HATA: NVIDIA_API_KEY tanımlı değil.", file=sys.stderr)
        return 2

    import base64
    import urllib.error
    import urllib.request

    with Image.open(image) as im:
        px_w, px_h = im.width, im.height

    payload = json.dumps({
        "input": [{
            "type": "image_url",
            "url": "data:image/png;base64," +
                   base64.b64encode(image.read_bytes()).decode(),
        }]
    }).encode()

    req = urllib.request.Request(
        NIM_OCR_URL, data=payload,
        headers={"Authorization": f"Bearer {api_key}",
                 "Accept": "application/json",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:1500]
        print(f"HTTP {e.code}\n{detail}", file=sys.stderr)
        return 1
    except Exception as e:  # ağ/DNS/proxy
        print(f"Bağlantı hatası: {e}", file=sys.stderr)
        return 1

    out = image.parent / "nim_response.json"
    out.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")

    words = _nim_detections(body, px_w, px_h, 72.0 / 300.0, 0.5)
    print(f"Ham yanıt yazıldı -> {out}")
    print(f"{len(words)} kelime ayrıştırıldı")
    for w in words[:10]:
        print(f"  x={w.x0:7.1f} y={w.y0:7.1f} conf={w.conf:5.1f} {w.text!r}")
    if not words:
        print("\nParser bu şemadan kelime çıkaramadı. nim_response.json'u "
              "paylaş, alan adları ona göre güncellensin.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
