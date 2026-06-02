"""Extrai CSS/JS de index.html para static/."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
text = (ROOT / "index.html").read_text(encoding="utf-8")
i0 = text.index("<style>") + len("<style>")
i1 = text.index("</style>")
css = text[i0:i1].strip()
t0 = text.index("<script>", text.index("</style>")) + len("<script>")
t1 = text.index("</script>", t0)
theme_js = text[t0:t1].strip()
i2 = text.rindex("<script>") + len("<script>")
i3 = text.rindex("</script>")
main_js = text[i2:i3].strip()
html_head = text[: text.index("<style>")]
body_part = text[text.index("<body>") : text.rindex("<script>")]
new_html = (
    html_head
    + '<link rel="stylesheet" href="/app.css">\n<script>\n'
    + theme_js
    + "\n</script>\n</head>\n"
    + body_part
    + '<script src="/app.js"></script>\n</body>\n</html>'
)
(ROOT / "static" / "app.css").parent.mkdir(exist_ok=True)
(ROOT / "static" / "app.css").write_text(css, encoding="utf-8")
(ROOT / "static" / "app.js").write_text(main_js, encoding="utf-8")
(ROOT / "index.html").write_text(new_html, encoding="utf-8")
(ROOT / "static" / "index.html").write_text(new_html, encoding="utf-8")
print("ok", len(css), len(main_js))
