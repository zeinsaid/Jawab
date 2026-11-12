"""The HTML version of every email Jawab sends (D-017), next to the plain text, which stays.

Email apps only support old-fashioned HTML: tables for layout, every style inline, no web fonts and
no images (often blocked). The layout: a dark header with the business's name in its accent colour,
an optional banner, a title, buttons, a table of short facts, then boxes for longer text (a summary,
a conversation, an answer). Arabic emails are right to left. Everything that came from a customer,
the model or the owner is escaped.
"""

from dataclasses import dataclass, field
from html import escape

from app.services.theme import _rgb, contrast

DEFAULT_ACCENT = "#0f766e"  # Jawab's teal (chat.css)
INK = "#1b1320"
SOFT = "#5a5160"
LINE = "#eeebe6"
FONT = "Arial, Helvetica, sans-serif"


@dataclass
class Block:
    label: str
    text: str = ""
    conversation: list[tuple[str, str]] = field(default_factory=list)  # (who, said), shown as a chat


@dataclass
class Email:
    brand: str  # the business's name in the header
    kicker: str  # what this email is, next to the name
    title: str
    accent: str | None = None
    lang: str = "en"
    banner: str | None = None  # a highlighted line under the header
    actions: list[tuple[str, str]] = field(default_factory=list)  # (label, href)
    rows: list[tuple[str, str]] = field(default_factory=list)  # (label, value)
    blocks: list[Block] = field(default_factory=list)
    footer: list[str] = field(default_factory=list)
    preheader: str = ""  # the grey preview line in the inbox list


def _e(text: str) -> str:
    return escape(text or "", quote=True)


def _block(block: Block, accent: str, start: str) -> str:
    if block.conversation:
        inner = "".join(
            f'<div style="margin:0 0 10px;"><b style="color:{INK};">{_e(who)}:</b> '
            f'<span style="white-space:pre-wrap;">{_e(said)}</span></div>'
            for who, said in block.conversation
        )
    else:
        inner = f'<div style="white-space:pre-wrap;">{_e(block.text)}</div>'
    return (
        f'<tr><td style="padding:22px 28px 0;">'
        f'<div style="font-size:13px;color:{SOFT};margin:0 0 6px;font-family:{FONT};">{_e(block.label)}</div>'
        f'<div style="background:#faf7fb;border-{start}:4px solid {accent};padding:14px 16px;font-size:15px;'
        f'line-height:1.55;color:{INK};font-family:{FONT};word-break:break-word;">{inner}</div></td></tr>'
    )


HEADER = "#0e0911"


def render(mail: Email) -> str:
    accent = mail.accent or DEFAULT_ACCENT
    # The name sits on the dark header in the accent colour if that reads (The Plug's neon does),
    # else in white (Jawab's dark teal), with the accent kept as the stripe under the header.
    name_colour = accent if contrast(_rgb(accent), _rgb(HEADER)) >= 4.5 else "#ffffff"
    rtl = mail.lang == "ar"
    start, end = ("right", "left") if rtl else ("left", "right")
    actions = ""
    if mail.actions:
        buttons = "".join(
            f'<a href="{_e(href)}" style="display:inline-block;background:{INK};color:#ffffff;text-decoration:none;'
            f'font-weight:bold;font-size:14px;padding:11px 20px;border-radius:999px;margin:0 0 8px;'
            f'margin-{end}:8px;font-family:{FONT};">{_e(label)}</a>'
            for label, href in mail.actions
        )
        actions = f'<tr><td style="padding:14px 28px 4px;">{buttons}</td></tr>'
    rows = ""
    if mail.rows:
        cells = "".join(
            f'<tr><td style="padding:9px 0;padding-{end}:12px;border-bottom:1px solid {LINE};font-size:13px;'
            f'color:{SOFT};width:36%;vertical-align:top;font-family:{FONT};">{_e(label)}</td>'
            f'<td style="padding:9px 0;border-bottom:1px solid {LINE};font-size:15px;color:{INK};vertical-align:top;'
            f'font-family:{FONT};word-break:break-word;white-space:pre-wrap;">{_e(value)}</td></tr>'
            for label, value in mail.rows
        )
        rows = (f'<tr><td style="padding:14px 28px 0;"><table role="presentation" width="100%" cellpadding="0" '
                f'cellspacing="0">{cells}</table></td></tr>')
    blocks = "".join(_block(b, accent, start) for b in mail.blocks)
    banner = (f'<tr><td style="background:#fff3c4;padding:14px 28px;font-size:16px;font-weight:bold;color:{INK};'
              f'font-family:{FONT};">{_e(mail.banner)}</td></tr>') if mail.banner else ""
    footer = "<br>".join(_e(line) for line in mail.footer)
    direction = ' dir="rtl"' if rtl else ""
    return f"""<!doctype html>
<html lang="{_e(mail.lang)}"{direction}><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light only"><title>{_e(mail.title)}</title></head>
<body style="margin:0;padding:0;background:#f3eef5;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{_e(mail.preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3eef5;"><tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"{direction} style="max-width:600px;background:#ffffff;border-radius:8px;overflow:hidden;text-align:{start};">
<tr><td style="background:{HEADER};padding:18px 28px;border-bottom:4px solid {accent};font-family:{FONT};">
<span style="font-size:20px;font-weight:bold;color:{name_colour};">{_e(mail.brand)}</span>
<span style="font-size:13px;color:#b9afc0;padding-{start}:10px;">{_e(mail.kicker)}</span>
</td></tr>
{banner}
<tr><td style="padding:26px 28px 0;"><h1 style="margin:0;font-size:22px;line-height:1.3;color:{INK};font-family:{FONT};">{_e(mail.title)}</h1></td></tr>
{actions}{rows}{blocks}
<tr><td style="padding:26px 28px 28px;font-size:12px;line-height:1.5;color:{SOFT};font-family:{FONT};">{footer}</td></tr>
</table>
</td></tr></table>
</body></html>"""
