COLORS = {
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[36m",
    "purple": "\033[35m",
    "white": "\033[37m",
    "reset": "\033[0m",
}


def color_text(text: str, color: str) -> str:
    """Wrap text in an ANSI color code."""
    prefix = COLORS.get(color, "")
    return f"{prefix}{text}{COLORS['reset']}"
