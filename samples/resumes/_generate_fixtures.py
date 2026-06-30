"""Generate the sample resume fixtures (one PDF, one DOCX).

The committed binaries are produced by this script so they're reproducible. Run:
    python samples/resumes/_generate_fixtures.py
(Needs reportlab for the PDF + python-docx for the DOCX.)
"""

import os

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
import docx

HERE = os.path.dirname(os.path.abspath(__file__))

JANE = [
    "Jane Doe",
    "Senior Software Engineer",
    "Email: jane.doe@example.com | Phone: +1 415-555-0132",
    "GitHub: github.com/octocat | LinkedIn: linkedin.com/in/jane-doe",
    "Portfolio: https://jane.dev",
    "",
    "Summary",
    "Backend-leaning full-stack engineer who likes clean data pipelines.",
    "",
    "Skills",
    "Python, React, GraphQL, Kubernetes, Terraform, AWS",
    "",
    "Experience",
    "Staff Engineer at Acme Corp (2021-03 to present)",
    "Junior Developer at Initech (2016-06 to 2017-12)",
    "",
    "Education",
    "B.S. in Computer Science, MIT, 2017",
]

CARLOS = [
    "Carlos Reyes",
    "Backend Engineer",
    "Email: carlos.reyes@example.com | Phone: +1 202-555-0188",
    "Portfolio: https://carlosreyes.dev",
    "",
    "Summary",
    "Backend specialist focused on Go services.",
    "",
    "Skills",
    "Go, PostgreSQL, Docker, AWS, Kafka",
    "",
    "Experience",
    "Backend Engineer at Globex (2019-06 to present)",
    "",
    "Education",
    "BS in Computer Engineering, UT Austin, 2019",
]


def write_pdf(path, lines):
    c = canvas.Canvas(path, pagesize=LETTER)
    _, height = LETTER
    y = height - 72
    for line in lines:
        c.drawString(72, y, line)
        y -= 16
    c.save()


def write_docx(path, lines):
    doc = docx.Document()
    for line in lines:
        doc.add_paragraph(line)
    doc.save(path)


if __name__ == "__main__":
    write_pdf(os.path.join(HERE, "jane_doe.pdf"), JANE)
    write_docx(os.path.join(HERE, "carlos_reyes.docx"), CARLOS)
    print("wrote jane_doe.pdf and carlos_reyes.docx")
