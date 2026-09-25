"""templates.py -- the document templates the pslib MCP server holds.

The registry is code, not files: a template is a Python object here, a new or
changed one is a commit and a server restart, and template_info() reports the
version the document was rendered with. Clients never see the template, only
its schema; they send data.

A template is markdown with jinja2 markup (loops and conditions included),
rendered with the data and handed to md2ps.md_to_pdf() with the template's own
MdConfig overrides and overlays. Data is validated against `schema` (a small
JSON-Schema subset: type, required, properties, items, enum, minLength) before
anything is rendered.
"""


class Template:
    """A markdown template (body, rendered by jinja2 then md2ps) or, when the
    layout needs PSDoc directly, a Python one (render_pdf(data, pdf_path))."""

    def __init__(self, name, description, version, schema, sample, body=None,
                 render_pdf=None, config=None, overlays=None):
        self.name = name
        self.description = description
        self.version = version
        self.schema = schema
        self.body = body
        self.render_pdf = render_pdf
        self.sample = sample
        self.config = config or {}
        self.overlays = overlays      # None -> md2ps defaults (footer + QR)


# ── validation (a JSON-Schema subset, no dependency) ───────────────────────

_TYPES = {"string": str, "number": (int, float), "integer": int,
          "boolean": bool, "object": dict, "array": list}


def _check(schema, value, path, out):
    t = schema.get("type")
    if t and not isinstance(value, _TYPES[t]) or (t == "integer" and isinstance(value, bool)):
        out.append(f"{path}: expected {t}, got {type(value).__name__}")
        return
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{path}: must be one of {schema['enum']}")
    if t == "string" and len(value) < schema.get("minLength", 0):
        out.append(f"{path}: must not be empty")
    if t == "object":
        for key in schema.get("required", []):
            if key not in value:
                out.append(f"{path}.{key}: required")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                _check(sub, value[key], f"{path}.{key}", out)
    if t == "array":
        if len(value) < schema.get("minItems", 0):
            out.append(f"{path}: needs at least {schema['minItems']} item(s)")
        item = schema.get("items")
        if item:
            for i, v in enumerate(value):
                _check(item, v, f"{path}[{i}]", out)


def validate(tpl, data):
    """A list of problems, empty when the data fits the template."""
    out = []
    _check(tpl.schema, data, "data", out)
    return out


def render(tpl, data):
    """The template's markdown with the data poured in."""
    import jinja2   # only needed when a template is rendered
    env = jinja2.Environment(autoescape=False, trim_blocks=True, lstrip_blocks=True,
                             undefined=jinja2.StrictUndefined)
    return env.from_string(tpl.body).render(**data)


# ── the registry ────────────────────────────────────────────────────────────

REPORT = Template(
    name="report",
    description="Technical report: title, author/date line, numbered sections with text, "
                "bullets and optional tables",
    version=1,
    schema={
        "type": "object",
        "required": ["title", "author", "date", "sections"],
        "properties": {
            "title": {"type": "string", "minLength": 1},
            "author": {"type": "string", "minLength": 1},
            "date": {"type": "string", "minLength": 1, "description": "as it should print, e.g. 2026-09-25"},
            "summary": {"type": "string"},
            "sections": {
                "type": "array", "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["heading"],
                    "properties": {
                        "heading": {"type": "string", "minLength": 1},
                        "text": {"type": "string", "description": "paragraphs, blank-line separated"},
                        "bullets": {"type": "array", "items": {"type": "string"}},
                        "table": {
                            "type": "object",
                            "required": ["headers", "rows"],
                            "properties": {
                                "headers": {"type": "array", "items": {"type": "string"}},
                                "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                            },
                        },
                    },
                },
            },
        },
    },
    body="""# {{ title }}

{{ author }}, {{ date }}

{% if summary is defined and summary %}
{{ summary }}

{% endif %}
{% for s in sections %}
## {{ s.heading }}

{% if s.get('text') %}
{{ s.text }}

{% endif %}
{% for b in s.get('bullets', []) %}
- {{ b }}
{% endfor %}
{% if s.get('table') %}

| {{ s.table.headers | join(' | ') }} |
| {% for h in s.table.headers %}--- | {% endfor %}
{% for r in s.table.rows %}
| {{ r | join(' | ') }} |
{% endfor %}

{% endif %}
{% endfor %}
""",
    sample={
        "title": "Отчет за измерванията",
        "author": "SC Team",
        "date": "2026-09-25",
        "summary": "Кратко резюме на резултатите.",
        "sections": [
            {"heading": "Постановка", "text": "Какво и как беше измерено.",
             "bullets": ["HackRF One", "RTL-SDR"]},
            {"heading": "Резултати",
             "table": {"headers": ["#", "Канал", "BER"],
                       "rows": [["1", "DMR TS1", "0.4%"], ["2", "DMR TS2", "1.1%"]]}},
        ],
    },
)

PROTOCOL = Template(
    name="protocol",
    description="Protocol / minutes: number, date, place, attendees, numbered decisions, "
                "signature lines; no QR, plain footer",
    version=1,
    schema={
        "type": "object",
        "required": ["number", "date", "place", "attendees", "items"],
        "properties": {
            "number": {"type": "string", "minLength": 1},
            "date": {"type": "string", "minLength": 1},
            "place": {"type": "string", "minLength": 1},
            "subject": {"type": "string"},
            "attendees": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "items": {
                "type": "array", "minItems": 1,
                "items": {"type": "object", "required": ["text"],
                          "properties": {"text": {"type": "string", "minLength": 1},
                                         "decision": {"type": "string"}}},
            },
            "signatures": {"type": "array", "items": {"type": "string"}},
        },
    },
    body="""# ПРОТОКОЛ № {{ number }}

{{ date }}, {{ place }}

{% if subject is defined and subject %}
Относно: {{ subject }}

{% endif %}
## Присъстващи

{% for a in attendees %}
- {{ a }}
{% endfor %}

## Дневен ред и решения

{% for it in items %}
{{ loop.index }}. {{ it.text }}
{% if it.get('decision') %}
   Решение: {{ it.decision }}
{% endif %}
{% endfor %}

{% if signatures is defined and signatures %}
## Подписи

{% for s in signatures %}
- {{ s }}: ______________________
{% endfor %}
{% endif %}
""",
    sample={
        "number": "7",
        "date": "2026-09-25",
        "place": "София",
        "subject": "Приемане на отчета",
        "attendees": ["Иван Иванов", "Мария Петрова"],
        "items": [{"text": "Отчетът е представен.", "decision": "Приема се."},
                  {"text": "Следваща среща."}],
        "signatures": ["Председател", "Секретар"],
    },
    overlays=[{"type": "footer"}],
)

# ── Технологична карта (production technology card) ──────────────────────────────────
# Three sections: the order, its parameters, the sign-off rows. The data
# comes in already fetched -- the MCP server never talks to a database.

TK_OPS = ["Нанасяне холограми", "Номерация", "Рязане", "Бандероли", "Опаковане"]
TK_GREEN = (0.36, 0.42, 0.30)


def _fmt_qty(q):
    try:
        return "{:,}".format(int(q)).replace(",", " ")
    except (TypeError, ValueError):
        return str(q) if q not in (None, "") else "-"


def render_tk_card(data, pdf_path):
    import datetime
    from pslib import PSDoc
    from md2ps import MdConfig, apply_overlays, generate_rsc

    order = data["order"]
    props = data.get("params", [])
    ops = data.get("ops") or TK_OPS
    if not data.get("show_all", False):
        props = [p for p in props if str(p.get("value", "")) not in ("", "0", "None")]
    card_no = data.get("card_no") or "ТК%s/HO01" % order["oord_id"]
    now = datetime.datetime.now()

    cfg = MdConfig()
    ps = pdf_path[:-4] + ".ps"
    doc = PSDoc(ps, title=card_no,
                margin=cfg.margin_left, margin_right=cfg.margin_right,
                margin_top=cfg.margin_top + cfg.qr_zone,
                margin_bottom=cfg.margin_bottom + cfg.footer_h)

    def section(y, num, title, needs=0):
        if needs and y - needs < doc.margin_bottom:
            doc.new_page()
            y = doc.A4H - doc.margin_top - 20
        doc.font("Helvetica-Bold", 9)
        doc.setcolor(*TK_GREEN)
        doc.text(doc.margin, y, num)
        doc.text(doc.margin + 22, y, title)
        doc.setgray(0)
        return y - 6

    doc.font("Helvetica-Bold", 17)
    doc.text(doc.A4W / 2, 772, "ТЕХНОЛОГИЧНА КАРТА", align="center")
    doc.font("Helvetica", 11)
    doc.text(doc.A4W / 2, 756, card_no, align="center")
    doc.hr(748)
    y = 728

    y = section(y, "01", "Поръчка")
    doc.font("Helvetica", 9)
    y = doc.table(doc.margin, y,
                  headers=["Клиент", "Поръчка", "Тираж", "Начало", "Срок"],
                  rows=[[order.get("customer") or "-", order.get("name") or "-",
                         _fmt_qty(order.get("quantity")),
                         order.get("start") or "-", order.get("end") or "-"]],
                  col_widths=[95, 190, 60, 62, 62],
                  col_align=["left", "left", "right", "center", "center"],
                  row_height=16, header_size=8, body_size=9)
    y -= 14

    y = section(y, "02", "Параметри на поръчката")
    doc.font("Helvetica", 8)
    y = doc.table(doc.margin, y,
                  headers=["#", "Наименование", "Стойност"],
                  rows=[[str(p.get("nnum", "")), p["name"],
                         "–" if p.get("value") in (None, "") else str(p["value"])] for p in props],
                  col_widths=[26, 320, 123],
                  col_align=["right", "left", "right"],
                  row_height=13, header_size=8, body_size=8)
    y -= 14

    y = section(y, "03", "Операции", needs=22 * (len(ops) + 1) + 12)
    doc.font("Helvetica", 8)
    doc.table(doc.margin, y,
              headers=["Операция", "Дата", "Бр. пл.", "Макул.", "Реално", "Име", "Подпис"],
              rows=[[o, "", "", "", "", "", ""] for o in ops],
              col_widths=[130, 55, 45, 45, 45, 80, 69],
              col_align=["left", "center", "right", "right", "right", "left", "left"],
              row_height=22, header_size=8, body_size=9)

    apply_overlays(doc, cfg, [
        {"type": "qr", "rsc": data.get("rsc") or generate_rsc(), "date": now.strftime("%Y-%m-%dT%H:%M")},
        {"type": "footer", "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S")},
    ])
    doc.save()
    doc.to_pdf(pdf_path)


TK_CARD = Template(
    name="tk_card",
    description="Технологична карта (production technology card): order header, order "
                "parameters, sign-off rows for the operations, QR + footer",
    version=1,
    schema={
        "type": "object",
        "required": ["order", "params"],
        "properties": {
            "order": {
                "type": "object",
                "required": ["oord_id", "name", "customer"],
                "properties": {
                    "oord_id": {"type": "integer"},
                    "name": {"type": "string", "minLength": 1},
                    "customer": {"type": "string", "minLength": 1},
                    "quantity": {"type": "integer"},
                    "start": {"type": "string", "description": "YYYY-MM-DD"},
                    "end": {"type": "string", "description": "YYYY-MM-DD"},
                },
            },
            "params": {
                "type": "array",
                "items": {"type": "object", "required": ["nnum", "name"],
                          "properties": {"nnum": {"type": "string"},
                                         "name": {"type": "string", "minLength": 1},
                                         "value": {"type": "string"}}},
                "description": "the order's parameters, in nnum order",
            },
            "show_all": {"type": "boolean", "description": "print unfilled parameters too (default false)"},
            "ops": {"type": "array", "items": {"type": "string"},
                    "description": "sign-off rows; default: the five standard operations"},
            "card_no": {"type": "string", "description": "default ТК<oord_id>/HO01"},
            "rsc": {"type": "string", "description": "QR code id; generated when absent"},
        },
    },
    sample={
        "order": {"oord_id": 1001, "name": "Примерна поръчка", "customer": "Примерен клиент ЕООД",
                  "quantity": 120000, "start": "2026-09-01", "end": "2026-10-15"},
        "params": [
            {"nnum": "1", "name": "Матрица", "value": "M-0001"},
            {"nnum": "2", "name": "Ецване", "value": "стандарт"},
            {"nnum": "3", "name": "ХОЕ щамповане", "value": "2 цвята"},
            {"nnum": "4", "name": "Лепило", "value": ""},
            {"nnum": "5", "name": "ФТП форматиране", "value": "50x30 mm"},
            {"nnum": "6", "name": "Материал", "value": "PET 25 µm"},
        ],
    },
    render_pdf=render_tk_card,
)

_REGISTRY = {t.name: t for t in (REPORT, PROTOCOL, TK_CARD)}


def all():
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def get(name):
    return _REGISTRY.get(name) if isinstance(name, str) else None
