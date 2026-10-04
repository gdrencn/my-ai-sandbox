"""Terminal display width and safe clipping, shared by menus and progress."""
import unicodedata


def cells(text):
    return sum(0 if unicodedata.combining(char) else
               2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1 for char in text)


def clipped(text, width):
    text = ''.join(char if char.isprintable() else ' ' for char in str(text))
    result, used = '', 0
    for char in text:
        size = cells(char)
        if used + size > width:
            break
        result += char
        used += size
    return result
