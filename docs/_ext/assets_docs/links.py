"""Relative links in the repository's Markdown files, made to work in the docs.

The Markdown files outside ``docs/`` (README.md, DECISIONS.md,
bond_portfolio/model.md, ...) are shown by pages that ``{include}`` them,
and their relative links are written for GitHub. A link, or a reference
definition, is rewritten relative to the page that shows it, to

* the page that includes the target file, if a page includes it;
* the target, if it is a file inside ``docs/`` (a page such as ``plan.md``);
* the target on GitHub, if it is another file or directory of the repository.

Other links (URLs, anchors, missing files) are left as they are. Links are
found paragraph by paragraph, so link text may hold code spans or line
breaks; links inside code spans, fenced code blocks and escaped brackets are
not touched.

Two more things are rendered as on GitHub: a bare URL becomes a link (except
in HTML blocks and code), and a fenced code block without an info string is
plain text (``text``), not Python, Sphinx's default.
"""

import os
import re
from pathlib import Path
from urllib.parse import unquote

# a backtick fence's info string holds no backtick: "```x``` ..." is inline code
_FENCE = re.compile(r"^[ \t]*(`{3,}(?!.*`)|~{3,})")
_INCLUDE = re.compile(r"^ {0,3}(?:`{3,}|:{3,})\{(?:include|literalinclude)\}\s+(\S+)")
_LINK = re.compile(
    r"(?<!!)(?<!(?<!\\)\\)\[(?P<text>(?:[^\[\]]|\[(?:[^\[\]]|\[[^\[\]]*\])*\])*)\]"
    r"\((?P<target><[^<>\n]*>|[^()\s]+)"
    r"(?P<title>\s+(?:\"[^\"]*\"|'[^']*'|\([^()]*\)))?\)"
)
_REFDEF = re.compile(
    r"(?P<lead> {0,3}\[(?!\^)[^\]]+\]:[ \t]*)(?P<target><[^<>\n]*>|[^\s<]\S*)"
    r"(?P<rest>(?:[ \t]+(?:\"[^\"]*\"?|'[^']*'?|\([^()]*\)?))?[ \t]*)")
# a heading or a thematic break: a block of one line
_ONE_LINE_BLOCK = re.compile(r"^ {0,3}(?:#{1,6}(?:[ \t]|$)|([-*_])(?:[ \t]*\1){2,}[ \t]*$)")
# the start of a CommonMark HTML block, which is passed through as raw HTML
_HTML_START = re.compile(
    r" {0,3}(?:<(?:script|pre|style|textarea)(?:[\s>]|$)|<!--|<\?|<![A-Za-z]|<!\[CDATA\["
    r"|</?(?:address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup"
    r"|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset"
    r"|h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol"
    r"|optgroup|option|p|param|search|section|summary|table|tbody|td|tfoot|th|thead|title|tr"
    r"|track|ul)(?:[\s>]|/>|$)"
    r"|</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>\n]*)?/?>[ \t]*(?:\r?\n|$))", re.I)
_BARE_URL = re.compile(r"(?<![<\[\w/\"'=])(?<!\]\()https?://[^\s<>\[\]`|]+")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_CODE_RUN = re.compile(r"`+")


def included_files(srcdir, skip_dirs=()):
    """{repository file: docname} for the files the hand-written pages include.

    A file included by several pages maps to the first page in sorted order.
    """
    srcdir = Path(srcdir)
    found = {}
    for path in sorted(srcdir.rglob("*.md")):
        rel = path.relative_to(srcdir)
        if rel.parts[0].startswith(("_", ".")) or rel.parts[0] in skip_dirs:
            continue
        docname = rel.with_suffix("").as_posix()
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            m = _INCLUDE.match(line)
            if not m:
                continue
            arg = m.group(1)
            base = srcdir if arg.startswith("/") else path.parent
            target = (base / arg.lstrip("/")).resolve()
            found.setdefault(target, docname)
    return found


def _code_ranges(text):
    """The (start, end) offsets of the inline code spans of ``text``."""
    ranges, pos = [], 0
    while m := _CODE_RUN.search(text, pos):
        close = re.compile(rf"(?<!`){m.group(0)}(?!`)").search(text, m.end())
        if not close:  # an unmatched backtick run is literal text
            pos = m.end()
            continue
        ranges.append((m.start(), close.end()))
        pos = close.end()
    return ranges


def _inside(pos, ranges):
    return any(a <= pos < b for a, b in ranges)


def _autolink(m):
    """``<url>`` for a bare URL; trailing punctuation stays outside, as on GitHub."""
    url = m.group(0)
    while url and (url[-1] in ".,;:!?'\"*_~"
                   or (url[-1] == ")" and url.count(")") > url.count("("))):
        url = url[:-1]
    return f"<{url}>{m.group(0)[len(url):]}"


class LinkRewriter:
    def __init__(self, repo_root, srcdir, pages_of, github_url, branch):
        self.repo_root = Path(repo_root).resolve()
        self.srcdir = Path(srcdir).resolve()
        self.pages_of = pages_of
        self.github_url = (github_url or "").rstrip("/")
        self.branch = branch

    def target_for(self, path, docname):
        """The link to ``path`` from page ``docname``, or None to keep the link."""
        docdir = (self.srcdir / docname).parent
        if path in self.pages_of:
            page = self.srcdir / (self.pages_of[path] + ".md")
            return Path(os.path.relpath(page, docdir)).as_posix()
        if not path.exists():
            return None
        if path.is_relative_to(self.srcdir) and path.is_file():
            return Path(os.path.relpath(path, docdir)).as_posix()
        if path.is_relative_to(self.repo_root) and self.github_url:
            kind = "tree" if path.is_dir() else "blob"
            rel = path.relative_to(self.repo_root).as_posix()
            return f"{self.github_url}/{kind}/{self.branch}/{rel}"
        return None

    def _new_target(self, target, origin, docname):
        """The rewritten link target, or None to keep ``target``."""
        angle = target.startswith("<") and target.endswith(">")
        if angle:
            target = target[1:-1]
        if target.startswith(("#", "/")) or _SCHEME.match(target):
            return None
        path, sep, anchor = target.partition("#")
        if not path:
            return None
        new = self.target_for((origin.parent / unquote(path)).resolve(), docname)
        if new is None:
            return None
        new = f"{new}{sep}{anchor}"
        return f"<{new}>" if angle or " " in new else new  # a space needs <...>

    def _rewrite_block(self, block, origin, docname):
        """Rewrite the links of one paragraph-like block of lines."""
        lines = block.splitlines(keepends=True)
        ndefs = 0
        for i, line in enumerate(lines):  # reference definitions open a paragraph
            body = line.rstrip("\r\n")
            m = _REFDEF.fullmatch(body)
            if not m:
                break
            ndefs = i + 1
            new = self._new_target(m.group("target"), origin, docname)
            if new is not None:
                lines[i] = f"{m.group('lead')}{new}{m.group('rest')}{line[len(body):]}"
        block = "".join(lines)
        defs_end = len("".join(lines[:ndefs]))
        code = _code_ranges(block)

        def link(m):
            if _inside(m.start(), code):
                return m.group(0)
            new = self._new_target(m.group("target"), origin, docname)
            if new is None:
                return m.group(0)
            return f"[{m.group('text')}]({new}{m.group('title') or ''})"

        block = _LINK.sub(link, block)
        # an indented code block, or an HTML block, is shown as written
        if block.startswith(("    ", "\t")) or _HTML_START.match(block):
            return block
        keep = _code_ranges(block) + [m.span() for m in _LINK.finditer(block)]
        keep.append((0, defs_end))
        return _BARE_URL.sub(
            lambda u: u.group(0) if _inside(u.start(), keep) else _autolink(u), block)

    def rewrite(self, text, origin, docname):
        """``text``, read from file ``origin`` and shown on page ``docname``."""
        origin = Path(origin).resolve()
        out, block, fence = [], [], None

        def flush():
            if block:
                out.append(self._rewrite_block("".join(block), origin, docname))
                block.clear()

        for line in text.splitlines(keepends=True):
            m = _FENCE.match(line)
            if fence is None and m:
                flush()
                fence = m.group(1)
                if not line.strip()[len(fence):].strip():
                    body = line.rstrip("\r\n")
                    line = f"{body}text{line[len(body):]}"
                out.append(line)
            elif fence is not None:
                if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) \
                        and not line.strip()[len(m.group(1)):].strip():
                    fence = None
                out.append(line)
            elif not line.strip():
                flush()
                out.append(line)
            elif _ONE_LINE_BLOCK.match(line):  # a heading ends a paragraph, alone
                flush()
                block.append(line)
                flush()
            else:
                block.append(line)
        flush()
        return "".join(out)
