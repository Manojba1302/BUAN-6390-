"""Restricted Markdown-to-PDF renderer: plain text, headings and bullets, no HTML/URLs."""
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# DejaVu covers accented, Eastern European, Greek and Cyrillic names that the built-in Helvetica cannot draw.
# The backend image installs fonts-dejavu-core; without it the renderer falls back to Helvetica.
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
PAGE = LETTER


@lru_cache
def fonts():
    regular, bold = FONT_DIR/"DejaVuSans.ttf", FONT_DIR/"DejaVuSans-Bold.ttf"
    if regular.is_file() and bold.is_file():
        pdfmetrics.registerFont(TTFont("HFSans", str(regular)))
        pdfmetrics.registerFont(TTFont("HFSans-Bold", str(bold)))
        return "HFSans", "HFSans-Bold"
    return "Helvetica", "Helvetica-Bold"


def _styles():
    regular, bold = fonts()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="HFTitle",fontName=bold,fontSize=22,leading=27,textColor=colors.HexColor("#17394d"),spaceAfter=14))
    styles.add(ParagraphStyle(name="HFHeading",fontName=bold,fontSize=13,leading=17,textColor=colors.HexColor("#17394d"),spaceBefore=8,spaceAfter=6,keepWithNext=1))
    styles.add(ParagraphStyle(name="HFBody",fontName=regular,fontSize=10,leading=14,spaceAfter=4))
    styles.add(ParagraphStyle(name="HFBullet",parent=styles["HFBody"],leftIndent=14,bulletIndent=4))
    return styles


def _paragraph(line,styles):
    if line.startswith("# "):
        return Paragraph(escape(line[2:]),styles["HFTitle"])
    if line.startswith("## "):
        return Paragraph(escape(line[3:]),styles["HFHeading"])
    if line.startswith("- "):
        return Paragraph(escape(line[2:]),styles["HFBullet"],bulletText="•")
    return Paragraph(escape(line),styles["HFBody"])


def render(markdown):
    stream = BytesIO()
    styles = _styles()
    story = [Spacer(1,6) if not line.strip() else _paragraph(line,styles) for line in markdown.splitlines()]
    doc = SimpleDocTemplate(stream,pagesize=PAGE,rightMargin=50,leftMargin=50,topMargin=46,bottomMargin=48)
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return stream.getvalue()


def footer(canvas,doc):
    canvas.saveState()
    canvas.setFont(fonts()[0],8)
    canvas.setFillColor(colors.HexColor("#536879"))
    canvas.drawString(50,26,"HomeFlow | SAMPLE - review before use")
    canvas.drawRightString(PAGE[0]-50,26,f"Page {doc.page}")
    canvas.restoreState()


def preview_pages(pdf):
    import base64
    import fitz
    with fitz.open(stream=pdf, filetype="pdf") as document:
        return [base64.b64encode(page.get_pixmap(matrix=fitz.Matrix(1.25,1.25)).tobytes("png")).decode("ascii") for page in document]
