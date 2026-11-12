"""A business's accent colour as the chat page's CSS variables, readable in light and dark mode.

Brand colours are often too bright for white text: The Plug's neon #F920EB gives only 3.3:1 on
white, under WCAG AA's 4.5:1. So the colour is darkened (light mode) or lightened (dark mode) just
enough for text on it to pass, and stays recognisably the same hue. The page loads with these
values already in its HTML, so it never flashes Jawab's teal first.
"""


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    value = hex_colour.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def _luminance(rgb) -> float:
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _mix(rgb, other, amount: float):
    return tuple(c + (o - c) * amount for c, o in zip(rgb, other))


WHITE, BLACK = (255, 255, 255), (0, 0, 0)
DARK_TEXT = (13, 13, 13)
DARK_SURFACE = (28, 28, 25)  # chat.css's dark --surface


def _until(rgb, towards, text, ratio=4.5):
    """Mix the colour towards black or white in small steps until `text` on it reaches `ratio`."""
    for step in range(0, 21):
        candidate = _mix(rgb, towards, step * 0.05)
        if contrast(candidate, text) >= ratio:
            return candidate
    return _mix(rgb, towards, 1.0)


def accent_variables(accent: str) -> dict[str, dict[str, str]]:
    """The chat page's accent variables for a "#RRGGBB" colour, for light and dark mode."""
    base = _rgb(accent)
    light = _until(base, BLACK, WHITE)
    dark = _until(base, WHITE, DARK_TEXT)
    return {
        "light": {
            "--accent": _hex(light),
            "--accent-strong": _hex(_mix(light, BLACK, 0.2)),
            "--accent-text": "#ffffff",
            "--accent-soft": _hex(_mix(base, WHITE, 0.88)),
        },
        "dark": {
            "--accent": _hex(dark),
            "--accent-strong": _hex(_until(dark, WHITE, DARK_SURFACE, 7)),
            "--accent-text": _hex(DARK_TEXT),
            "--accent-soft": _hex(_mix(DARK_SURFACE, base, 0.22)),
        },
    }


def accent_style(accent: str | None) -> str:
    """A <style> block that overrides chat.css's teal, or "" to keep it."""
    if not accent:
        return ""
    v = accent_variables(accent)
    light = ";".join(f"{k}:{val}" for k, val in v["light"].items())
    dark = ";".join(f"{k}:{val}" for k, val in v["dark"].items())
    return (f"<style>:root{{{light}}}@media (prefers-color-scheme: dark)"
            f"{{:root:not([data-theme=\"light\"]){{{dark}}}}}</style>")
