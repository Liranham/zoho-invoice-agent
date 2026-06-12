"""
Single source of truth for converting LLM markdown into Telegram-friendly
HTML — used by Goldman (this repo) and Bob (ai-personal-assistant repo).
Keep the TWO copies byte-for-byte identical until we refactor into a real
shared package. Drift will reintroduce the ugly-markdown bug.

Why this exists:
The Telegram client renders messages in one of three modes — plain text,
legacy Markdown, or HTML. LLM output (GitHub-style markdown — `**bold**`,
`## headers`, `|---|---|---|` tables) does not render in any of them.
This module converts the LLM output to safe Telegram HTML so:
  - `**bold**` and `# Heading` show up as actual bold text
  - `|---|---|---|` table separator rows disappear
  - Pipe tables render as a clean monospace `<pre>` block (the grey box
    Telegram displays for preformatted text — visually equivalent to
    Slack's code-block table)
  - `[Label](https://...)` becomes a proper clickable link
  - `<`, `>`, `&` in user-visible text are HTML-escaped so they don't
    break the parser

Usage:
    from utils.telegram_format import telegram_format
    text_html = telegram_format(raw_markdown)
    bot.send_message(chat_id, text_html, parse_mode="HTML")

A hard guard at the end of `telegram_format` strips anything that survived
the precise passes and logs a warning so LLM drift is visible in app logs.
"""

import logging
import re
from typing import Tuple

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────
# HTML-safe escaping (Telegram HTML mode requires `<`, `>`, `&` escaped
# inside text content; `"` must be escaped inside attribute values).
# ────────────────────────────────────────────────────────────────────────

def _escape_html(text: str) -> str:
    """Escape `&`, `<`, `>` for Telegram HTML mode text content."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )


def _escape_html_attr(text: str) -> str:
    """Escape characters inside an HTML attribute value (e.g. href)."""
    return _escape_html(text).replace('"', "&quot;")


# ────────────────────────────────────────────────────────────────────────
# Pipe table → aligned monospace text (rendered inside <pre>).
# Drops the |---|---|---| separator row, pads columns to even width.
# ────────────────────────────────────────────────────────────────────────

_PIPE_SEPARATOR_LINE_RE = re.compile(r"^\s*\|[\s\-:+|]+\|\s*$")


def _format_pipe_table(raw: str) -> str:
    """Render a markdown pipe table as aligned monospace text."""
    lines = raw.split("\n")
    data_lines = [l for l in lines if not _PIPE_SEPARATOR_LINE_RE.match(l)]
    rows = []
    for line in data_lines:
        s = line.strip()
        if not s.startswith("|"):
            continue
        # Drop the leading and trailing pipe, split on the rest.
        cells = [c.strip() for c in s.split("|")[1:-1]]
        rows.append(cells)
    if not rows:
        return raw
    # Compute column widths.
    widths: list[int] = []
    for row in rows:
        for i, cell in enumerate(row):
            while len(widths) <= i:
                widths.append(0)
            widths[i] = max(widths[i], len(cell))
    # Render padded rows separated by two spaces.
    out_rows = []
    for row in rows:
        padded = [row[i].ljust(widths[i]) if i < len(row) else "" for i in range(len(widths))]
        out_rows.append("  ".join(padded).rstrip())
    return "\n".join(out_rows)


# ────────────────────────────────────────────────────────────────────────
# telegram_format — the entry point. Order matters here: we extract
# multi-line patterns (code blocks, pipe tables) first as placeholders
# so the line-by-line passes (header strip, bold convert) don't chew
# their internals.
# ────────────────────────────────────────────────────────────────────────

# Placeholder tokens — strings the LLM is extremely unlikely to write.
_PRE_PLACEHOLDER_PREFIX = "\x00PRE_BLOCK_"
_LINK_PLACEHOLDER_PREFIX = "\x00LINK_"
_CODE_PLACEHOLDER_PREFIX = "\x00CODE_"


def telegram_format(raw: str) -> str:
    """Convert LLM markdown to Telegram HTML.

    Pipeline:
        1. Extract triple-backtick code blocks → placeholders.
        2. Extract pipe tables (≥2 rows starting with `|`) → placeholders.
        3. Extract inline `code` → placeholders.
        4. Extract `[label](url)` links → placeholders.
        5. Escape `&`, `<`, `>` in remaining text.
        6. Convert markdown: `# Header`, `**bold**`, strip `---`.
        7. Re-insert placeholders as HTML (`<pre>`, `<code>`, `<a>`).
        8. Hard guard: strip any surviving `**`, `## `, `---` and log.
    """
    if not raw:
        return ""
    text = raw
    pre_blocks: list[str] = []
    link_blocks: list[Tuple[str, str]] = []
    code_blocks: list[str] = []

    # 1. Extract triple-backtick code blocks first. Use the multiline DOTALL
    # match. The opening fence may carry a language hint we ignore.
    def _capture_pre(m: re.Match) -> str:
        body = m.group(1)
        pre_blocks.append(body)
        return f"{_PRE_PLACEHOLDER_PREFIX}{len(pre_blocks) - 1}\x00"

    text = re.sub(r"```[^\n]*\n(.*?)```", _capture_pre, text, flags=re.DOTALL)
    # Also handle a fence pair with no inner newline (rare).
    text = re.sub(r"```([^`\n]+?)```", _capture_pre, text)

    # 2. Extract pipe tables. A pipe table is ≥2 consecutive lines starting
    # with `|`. We scan line by line and group runs.
    lines = text.split("\n")
    out_lines: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            run = "\n".join(lines[i:j])
            # Require ≥2 rows to count as a table; a single |row| stays inline.
            if (j - i) >= 2:
                formatted = _format_pipe_table(run)
                pre_blocks.append(formatted)
                out_lines.append(f"{_PRE_PLACEHOLDER_PREFIX}{len(pre_blocks) - 1}\x00")
            else:
                out_lines.extend(lines[i:j])
            i = j
        else:
            out_lines.append(lines[i])
            i += 1
    text = "\n".join(out_lines)

    # 3. Extract inline `code` spans (single backticks). Avoid matching
    # already-extracted placeholders by skipping NUL-containing matches.
    def _capture_code(m: re.Match) -> str:
        body = m.group(1)
        code_blocks.append(body)
        return f"{_CODE_PLACEHOLDER_PREFIX}{len(code_blocks) - 1}\x00"

    text = re.sub(r"`([^`\n\x00]+?)`", _capture_code, text)

    # 4. Extract `[label](url)` links.
    def _capture_link(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        link_blocks.append((label, url))
        return f"{_LINK_PLACEHOLDER_PREFIX}{len(link_blocks) - 1}\x00"

    text = re.sub(
        r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)",
        _capture_link,
        text,
    )

    # 5. Escape HTML special chars in the remaining text. Placeholders
    # contain only `\x00` and digits / ASCII — safe across this pass.
    text = _escape_html(text)

    # 6. Markdown → HTML conversions on the escaped text.
    #    - Strip lone `---` divider lines (with optional trailing newline).
    text = re.sub(r"^---+[\t ]*\n", "", text, flags=re.MULTILINE)
    text = re.sub(r"^---+\s*$", "", text, flags=re.MULTILINE)
    #    - ATX headers H1–H6 → bold (no `#` in Telegram).
    text = re.sub(r"^#{1,6} (.+?)\s*$", r"<b>\1</b>", text, flags=re.MULTILINE)
    #    - **bold** → <b>bold</b> (greedy avoids eating across paragraphs).
    text = re.sub(r"\*\*([^\n*][^\n]*?[^\n*]|\S)\*\*", r"<b>\1</b>", text)
    #    - Single _italic_ / *italic*: too noisy at this stage (false-
    #      positives on multiplication, footnote markers, etc.). Skip for
    #      now — can revisit if the user asks.
    #    - Collapse 3+ blank lines to 2.
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    # 7. Re-insert placeholders.
    def _reinsert_pre(m: re.Match) -> str:
        idx = int(m.group(1))
        body = pre_blocks[idx] if idx < len(pre_blocks) else ""
        return f"<pre>{_escape_html(body)}</pre>"

    text = re.sub(rf"{_PRE_PLACEHOLDER_PREFIX}(\d+)\x00", _reinsert_pre, text)

    def _reinsert_code(m: re.Match) -> str:
        idx = int(m.group(1))
        body = code_blocks[idx] if idx < len(code_blocks) else ""
        return f"<code>{_escape_html(body)}</code>"

    text = re.sub(rf"{_CODE_PLACEHOLDER_PREFIX}(\d+)\x00", _reinsert_code, text)

    def _reinsert_link(m: re.Match) -> str:
        idx = int(m.group(1))
        if idx >= len(link_blocks):
            return ""
        label, url = link_blocks[idx]
        return f'<a href="{_escape_html_attr(url)}">{_escape_html(label)}</a>'

    text = re.sub(rf"{_LINK_PLACEHOLDER_PREFIX}(\d+)\x00", _reinsert_link, text)

    # 8. Hard guard. If `**`, lone `---`, or `## ` survived, strip them
    # and log so we can spot LLM drift in app logs (same shape as the
    # Slack hard guard at `_shared/slack-format.ts:applyHardGuard`).
    drift: list[str] = []
    surviving_bold = len(re.findall(r"\*\*[^*\n]+\*\*", text))
    if surviving_bold:
        drift.append(f"{surviving_bold}x **")
        text = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", text)
    surviving_dash = len(re.findall(r"^---+\s*$", text, flags=re.MULTILINE))
    if surviving_dash:
        drift.append(f"{surviving_dash}x ---")
        text = re.sub(r"^---+\s*$", "", text, flags=re.MULTILINE)
    surviving_hash = len(re.findall(r"^#{1,6}\s+.+", text, flags=re.MULTILINE))
    if surviving_hash:
        drift.append(f"{surviving_hash}x ## header")
        text = re.sub(
            r"^#{1,6}\s+(.+?)\s*$",
            r"<b>\1</b>",
            text,
            flags=re.MULTILINE,
        )
    if drift:
        preview = raw[:60].replace("\n", " ")
        logger.warning(
            "[telegram-format] hard-guard stripped: %s — preview: %r",
            ", ".join(drift),
            preview,
        )

    # Final cleanup: re-collapse any blank lines the strip introduced.
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text
