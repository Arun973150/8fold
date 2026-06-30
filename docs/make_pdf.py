"""Render docs/DESIGN.md into a tight one-page PDF.

Usage:
    python docs/make_pdf.py "Your Full Name" your@email.com
Produces docs/<FullName>_<email>_Eightfold.pdf (plus docs/DESIGN.pdf).
"""

import os
import sys

import markdown
from xhtml2pdf import pisa

HERE = os.path.dirname(os.path.abspath(__file__))

CSS = """
@page { size: A4 portrait; margin: 12mm 12mm; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 7.6pt; line-height: 1.28; color: #111; }
h1 { font-size: 12pt; margin: 0 0 4px 0; }
h3 { font-size: 8.6pt; margin: 7px 0 2px 0; color: #1a3b6e; }
p { margin: 2px 0; }
ul, ol { margin: 2px 0 2px 14px; padding: 0; }
li { margin: 1px 0; }
code, pre { font-family: Courier, monospace; font-size: 6.8pt; background: #f3f4f6; }
pre { padding: 4px 6px; margin: 3px 0; white-space: pre-wrap; }
strong { color: #000; }
"""


def build(full_name: str, email: str) -> str:
    with open(os.path.join(HERE, "DESIGN.md"), encoding="utf-8") as fh:
        md = fh.read()
    body = markdown.markdown(md, extensions=["fenced_code", "tables"])
    html = f"<html><head><style>{CSS}</style></head><body>{body}</body></html>"

    safe_name = full_name.strip().replace(" ", "")
    safe_email = email.strip()
    out_named = os.path.join(HERE, f"{safe_name}_{safe_email}_Eightfold.pdf")
    out_stable = os.path.join(HERE, "DESIGN.pdf")

    for out in (out_named, out_stable):
        with open(out, "wb") as fh:
            result = pisa.CreatePDF(html, dest=fh)
        if result.err:
            raise SystemExit(f"PDF generation failed for {out}")
    print(f"wrote {out_named}")
    print(f"wrote {out_stable}")
    return out_named


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "Candidate"
    mail = sys.argv[2] if len(sys.argv) > 2 else "candidate@example.com"
    build(name, mail)
