# yamlish.py — a small, dependency-free YAML subset for device config files.
#
# MicroPython has no PyYAML and the full YAML spec is far too large for an
# ESP32. This module implements the block-style subset the config file uses:
#
#   * nested mappings (`section:\n  key: value`)
#   * block lists (`- item`) and inline lists (`[a, b]`)
#   * inline maps (`{a: 1, b: "two"}`)
#   * plain, single-quoted and double-quoted scalars
#   * comments (`#` outside quotes), blank lines
#   * booleans (true/false/yes/no/on/off), null/~/empty, ints and floats
#
# It deliberately rejects anchors, aliases, tags, multi-document streams and
# block scalars (`|`, `>`). The config schema does not need them, and failing
# loudly is much safer than silently mistaking a value for something else.
#
# The same file runs on CPython (host tests) and MicroPython (device): no
# regular expressions, no dataclasses, no f-strings, no locale assumptions.

class YamlError(ValueError):
    """Raised for malformed YAML, with a 1-based line number when possible."""


_TRUE_WORDS = ("true", "yes", "on")
_FALSE_WORDS = ("false", "no", "off")
_NULL_WORDS = ("null", "~", "")


def _escaped(text, index):
    """True when text[index] is preceded by an odd number of backslashes."""
    n = 0
    j = index - 1
    while j >= 0 and text[j] == "\\":
        n += 1
        j -= 1
    return (n & 1) == 1


def strip_comment(line):
    """Remove a trailing YAML comment while respecting quoted strings."""
    out = []
    quote = ""
    i = 0
    while i < len(line):
        c = line[i]
        if quote:
            out.append(c)
            if c == quote:
                if quote == "'" and i + 1 < len(line) and line[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                if quote == '"' and _escaped(line, i):
                    pass
                else:
                    quote = ""
        else:
            if c == '"' or c == "'":
                quote = c
                out.append(c)
            elif c == "#" and (i == 0 or line[i - 1] == " " or line[i - 1] == "\t"):
                break
            else:
                out.append(c)
        i += 1
    return "".join(out)


def _tokenize(text):
    if text is None:
        return []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for number, raw in enumerate(text.split("\n"), 1):
        line = strip_comment(raw).rstrip()
        if not line.strip():
            continue
        prefix = line[:len(line) - len(line.lstrip(" \t"))]
        if "\t" in prefix or (prefix == "" and line.startswith("\t")):
            raise YamlError("tabs cannot be used for indentation (line %d)" % number)
        indent = len(prefix)
        body = line[indent:]
        lines.append((indent, body, number))
    return lines


def _find_colon(text):
    """Index of the first mapping colon (outside quotes, followed by space/end)."""
    quote = ""
    depth = 0
    i = 0
    while i < len(text):
        c = text[i]
        if quote:
            if c == quote:
                if quote == "'" and i + 1 < len(text) and text[i + 1] == "'":
                    i += 2
                    continue
                if quote == '"' and _escaped(text, i):
                    pass
                else:
                    quote = ""
        else:
            if c == '"' or c == "'":
                quote = c
            elif c == "[" or c == "{":
                depth += 1
            elif c == "]" or c == "}":
                if depth > 0:
                    depth -= 1
            elif c == ":" and depth == 0:
                if i + 1 >= len(text) or text[i + 1] == " " or text[i + 1] == "\t":
                    return i
        i += 1
    return -1


def _split_key(text):
    idx = _find_colon(text)
    if idx < 0:
        return None, None
    return text[:idx].strip(), text[idx + 1:].strip()


def _parse_key(text, number):
    if not text:
        raise YamlError("empty mapping key (line %d)" % number)
    if text[0] == '"' or text[0] == "'":
        value = _parse_scalar(text, number)
        if not isinstance(value, str):
            raise YamlError("mapping key must be a string (line %d)" % number)
        return value
    return text


def _parse_number(text):
    """Return int/float when text is a plain YAML number, else None."""
    if not text:
        return None
    t = text
    sign = 1
    if t[0] == "+" or t[0] == "-":
        if t[0] == "-":
            sign = -1
        t = t[1:]
    if not t:
        return None
    low = t.lower()
    for prefix, base in (("0x", 16), ("0o", 8), ("0b", 2)):
        if low.startswith(prefix):
            body = t[2:]
            if not body:
                return None
            try:
                return sign * int(body, base)
            except Exception:
                return None

    digits = True
    for c in t:
        if c < "0" or c > "9":
            digits = False
            break
    if digits:
        try:
            return int(text)
        except Exception:
            return None

    dot = 0
    exp = 0
    for i in range(len(t)):
        c = t[i]
        if c == ".":
            dot += 1
        elif c == "e" or c == "E":
            exp += 1
        elif c == "+" or c == "-":
            if i == 0 or (t[i - 1] != "e" and t[i - 1] != "E"):
                return None
        elif c < "0" or c > "9":
            return None
    if dot > 1 or exp > 1:
        return None
    if t[0] == "." or t[-1] == "." or t[0] == "e" or t[0] == "E":
        return None
    if t[-1] == "e" or t[-1] == "E":
        return None
    try:
        return float(text)
    except Exception:
        return None


def _unquote(text, number):
    quote = text[0]
    if len(text) < 2 or text[-1] != quote:
        raise YamlError("unterminated quoted string (line %d)" % number)
    body = text[1:-1]
    if quote == "'":
        return body.replace("''", "'")
    out = []
    i = 0
    while i < len(body):
        c = body[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        if i + 1 >= len(body):
            out.append("\\")
            break
        e = body[i + 1]
        if e == "n":
            out.append("\n")
        elif e == "r":
            out.append("\r")
        elif e == "t":
            out.append("\t")
        elif e == "0":
            out.append("\x00")
        elif e == '"' or e == "\\" or e == "/":
            out.append(e)
        elif e == "u" and i + 5 < len(body):
            try:
                out.append(chr(int(body[i + 2:i + 6], 16)))
                i += 4
            except Exception:
                out.append("u")
        else:
            out.append(e)
        i += 2
    return "".join(out)


def _split_inline(text):
    """Split flow-style items on top-level commas."""
    items = []
    start = 0
    quote = ""
    depth = 0
    i = 0
    while i < len(text):
        c = text[i]
        if quote:
            if c == quote:
                if quote == "'" and i + 1 < len(text) and text[i + 1] == "'":
                    i += 2
                    continue
                if quote == '"' and _escaped(text, i):
                    pass
                else:
                    quote = ""
        else:
            if c == '"' or c == "'":
                quote = c
            elif c == "[" or c == "{":
                depth += 1
            elif c == "]" or c == "}":
                if depth > 0:
                    depth -= 1
            elif c == "," and depth == 0:
                items.append(text[start:i].strip())
                start = i + 1
        i += 1
    tail = text[start:].strip()
    if tail:
        items.append(tail)
    return items


def _parse_inline_list(text, number):
    body = text[1:-1].strip()
    if not body:
        return []
    out = []
    for item in _split_inline(body):
        out.append(_parse_scalar(item, number))
    return out


def _parse_inline_map(text, number):
    body = text[1:-1].strip()
    if not body:
        return {}
    out = {}
    for item in _split_inline(body):
        key, value = _split_key(item)
        if key is None:
            raise YamlError("invalid inline mapping (line %d)" % number)
        out[_parse_key(key, number)] = _parse_scalar(value, number)
    return out


def _parse_scalar(text, number):
    if text is None:
        return None
    s = text.strip()
    if not s:
        return None
    if s[0] == '"' or s[0] == "'":
        return _unquote(s, number)
    if s[0] == "[":
        if s[-1] != "]":
            raise YamlError("unterminated inline list (line %d)" % number)
        return _parse_inline_list(s, number)
    if s[0] == "{":
        if s[-1] != "}":
            raise YamlError("unterminated inline map (line %d)" % number)
        return _parse_inline_map(s, number)
    low = s.lower()
    if low in _TRUE_WORDS:
        return True
    if low in _FALSE_WORDS:
        return False
    if low in _NULL_WORDS:
        return None
    number_value = _parse_number(s)
    if number_value is not None:
        return number_value
    return s


def _parse_map(lines, index, indent):
    out = {}
    while index < len(lines):
        ind, text, number = lines[index]
        if ind < indent:
            break
        if ind > indent:
            raise YamlError("unexpected indentation (line %d)" % number)
        if text == "-" or text.startswith("- "):
            break
        key_text, rest = _split_key(text)
        if key_text is None:
            raise YamlError("expected 'key: value' (line %d)" % number)
        key = _parse_key(key_text, number)
        index += 1
        if rest == "":
            if index < len(lines) and lines[index][0] > indent:
                value, index = _parse_block(lines, index, lines[index][0])
            elif (index < len(lines) and lines[index][0] == indent
                  and (lines[index][1] == "-" or lines[index][1].startswith("- "))):
                # Tolerate a sequence at the same indent as its parent key.
                value, index = _parse_list(lines, index, indent)
            else:
                value = None
        else:
            value = _parse_scalar(rest, number)
        out[key] = value
    return out, index


def _parse_list(lines, index, indent):
    out = []
    while index < len(lines):
        ind, text, number = lines[index]
        if ind < indent:
            break
        if ind > indent:
            raise YamlError("unexpected indentation (line %d)" % number)
        if not (text == "-" or text.startswith("- ")):
            break
        rest = text[1:].lstrip(" ")
        index += 1
        if rest == "":
            if index < len(lines) and lines[index][0] > indent:
                value, index = _parse_block(lines, index, lines[index][0])
            else:
                value = None
        else:
            key_text, tail = _split_key(rest)
            if key_text is not None:
                # A list item that starts a mapping: "- key: value".
                item = {}
                key = _parse_key(key_text, number)
                if tail == "":
                    if index < len(lines) and lines[index][0] > indent:
                        nested, index = _parse_block(lines, index, lines[index][0])
                        item[key] = nested
                    else:
                        item[key] = None
                else:
                    item[key] = _parse_scalar(tail, number)
                while index < len(lines) and lines[index][0] > indent:
                    sub, index = _parse_map(lines, index, lines[index][0])
                    if not isinstance(sub, dict):
                        break
                    for k in sub:
                        item[k] = sub[k]
                value = item
            else:
                value = _parse_scalar(rest, number)
        out.append(value)
    return out, index


def _parse_block(lines, index, indent):
    if index >= len(lines):
        return None, index
    text = lines[index][1]
    if text == "-" or text.startswith("- "):
        return _parse_list(lines, index, indent)
    return _parse_map(lines, index, indent)


def loads(text):
    """Parse a YAML document into dicts/lists/scalars.

    Accepts comments and blank lines. Raises ``YamlError`` for constructs this
    subset does not support; callers should treat that as a validation error.
    """
    lines = _tokenize(text)
    if not lines:
        return {}
    value, index = _parse_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise YamlError("unexpected content (line %d)" % lines[index][2])
    return value


def _needs_quotes(s):
    if s == "":
        return True
    if s != s.strip():
        return True
    low = s.lower()
    if low in _TRUE_WORDS or low in _FALSE_WORDS or low in _NULL_WORDS:
        return True
    if _parse_number(s) is not None:
        return True
    first = s[0]
    if first in "-?:,[]{}#&*!|>'\"%@`":
        if first == "-" and len(s) > 1 and s[1] != " ":
            pass
        elif first == "?" and len(s) > 1 and s[1] != " ":
            pass
        else:
            return True
    if "\n" in s or "\r" in s or "\t" in s:
        return True
    if "#" in s:
        return True
    if ":" in s:
        for i in range(len(s)):
            if s[i] == ":" and (i + 1 >= len(s) or s[i + 1] == " "):
                return True
    if s.startswith("- ") or s.startswith("? "):
        return True
    return False


def _quote(s):
    out = ['"']
    for c in s:
        if c == "\\":
            out.append("\\\\")
        elif c == '"':
            out.append('\\"')
        elif c == "\n":
            out.append("\\n")
        elif c == "\r":
            out.append("\\r")
        elif c == "\t":
            out.append("\\t")
        elif ord(c) < 0x20:
            out.append("\\u%04x" % ord(c))
        else:
            out.append(c)
    out.append('"')
    return "".join(out)


def dump_scalar(value):
    """Render a scalar as a YAML token (quoted when needed)."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        text = repr(value)
        if text == "nan" or text == "inf" or text == "-inf":
            return _quote(text)
        return text
    if isinstance(value, (dict, list)):
        return dump_inline(value)
    s = str(value)
    if _needs_quotes(s):
        return _quote(s)
    return s


def _dump_key(key):
    s = str(key)
    if not s:
        return '""'
    allowed = True
    for c in s:
        if (c >= "a" and c <= "z") or (c >= "A" and c <= "Z") or (c >= "0" and c <= "9"):
            continue
        if c == "_" or c == "-" or c == ".":
            continue
        allowed = False
        break
    if allowed and _needs_quotes(s) is False:
        return s
    return _quote(s)


def dump_inline(value):
    """Render a value as a single-line flow token (lists/maps included)."""
    if isinstance(value, dict):
        parts = []
        for key in value:
            parts.append("%s: %s" % (_dump_key(key), dump_inline(value[key])))
        return "{" + ", ".join(parts) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(dump_inline(item) for item in value) + "]"
    return dump_scalar(value)


def _ordered_keys(value, order, path):
    """Keys in schema order, then any keys the schema does not know about.

    MicroPython dicts do not preserve insertion order, so callers that care
    about a stable hand-editable file pass an order map keyed by dotted path
    (the root path is "").
    """
    keys = list(value)
    wanted = order.get(path) if order else None
    if wanted:
        head = []
        for key in wanted:
            if key in value:
                head.append(key)
        for key in keys:
            if key not in head:
                head.append(key)
        return head
    return keys


def _dump_mapping(value, indent, lines, order, path):
    pad = " " * indent
    for key in _ordered_keys(value, order, path):
        item = value[key]
        name = _dump_key(key)
        child = key if path == "" else path + "." + key
        if isinstance(item, dict):
            if item:
                lines.append(pad + name + ":")
                _dump_mapping(item, indent + 2, lines, order, child)
            else:
                lines.append(pad + name + ": {}")
        elif isinstance(item, list):
            if item:
                lines.append(pad + name + ":")
                _dump_list(item, indent + 2, lines)
            else:
                lines.append(pad + name + ": []")
        else:
            lines.append(pad + name + ": " + dump_scalar(item))


def _dump_list(value, indent, lines):
    pad = " " * indent
    for item in value:
        if isinstance(item, (dict, list)):
            lines.append(pad + "- " + dump_inline(item))
        else:
            lines.append(pad + "- " + dump_scalar(item))


def dumps(value, order=None):
    """Serialise a dict/list/scalar to block-style YAML text.

    ``order`` optionally maps a dotted path ("" for the root) to the key order
    that path should use. Unknown keys follow in their natural iteration order.
    """
    lines = []
    if isinstance(value, dict):
        _dump_mapping(value, 0, lines, order or {}, "")
    elif isinstance(value, list):
        _dump_list(value, 0, lines)
    else:
        lines.append(dump_scalar(value))
    if not lines:
        return ""
    return "\n".join(lines) + "\n"
