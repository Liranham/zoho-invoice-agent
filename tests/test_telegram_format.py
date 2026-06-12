"""
Regression tests for telegram_format. Run with:
    python -m pytest tests/test_telegram_format.py -v
or:
    python -m unittest tests.test_telegram_format -v

Each input below is verbatim text Goldman or Bob has actually sent into
Telegram as raw markdown. Every test asserts the formatter produces clean
Telegram HTML with no `**`, `## `, `---`, or `|---|---|` survivors.
"""

import sys
from pathlib import Path

# Allow running from repo root (so `from utils.telegram_format import ...` resolves).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest
from utils.telegram_format import telegram_format


# ────────────────────────────────────────────────────────────────────────
# 2026-06-11 incident — Goldman's open-invoices reply that prompted this.
# Verbatim ugly markdown that survived the legacy parse_mode="Markdown".
# ────────────────────────────────────────────────────────────────────────

GOLDMAN_OPEN_INVOICES = """Here's a summary of open invoices for **AMZ-Expert Global Limited (HK)** [Zoho org 876247837]:

---

### ✅ Sent (not yet due)
| Invoice | Client | Amount | Due Date |
|---------|--------|--------|----------|
| INV-000081 | NorthPoint Enterprises Inc | $1,300.00 | 2026-05-31 |

---

### 🛑 Overdue
| Invoice | Client | Amount | Due Date |
|---------|--------|--------|----------|
| INV-000080 | MOYOU MARKETING Ltd | $1,777.00 | 2026-05-31 |
| INV-000079 | NorthPoint Enterprises Inc | $1,300.00 | 2026-04-30 |
| INV-000078 | MOYOU MARKETING Ltd | $2,244.00 | 2026-04-30 |

---

### 📊 Total Overdue: **$17,525.17 USD**
### 📊 Total Open (including sent): **$18,825.17 USD**

---

A few things worth flagging:
- **Orda USA / Small World Toys** has **3 overdue invoices** totaling **$8,873.67**.
- **MOYOU MARKETING** also has **3 overdue invoices** totaling **$6,051.50**.

Would you like me to draft payment reminder emails for any of these clients?"""


class TelegramFormatTests(unittest.TestCase):

    def test_no_double_asterisks_survive(self):
        out = telegram_format(GOLDMAN_OPEN_INVOICES)
        self.assertNotIn("**", out, f"** survived: {out[:200]}")

    def test_no_atx_headers_survive(self):
        out = telegram_format(GOLDMAN_OPEN_INVOICES)
        # Walk lines — no line should start with one-to-six `#` followed by space.
        for line in out.split("\n"):
            self.assertFalse(
                line.lstrip().startswith(("# ", "## ", "### ", "#### ", "##### ", "###### ")),
                f"ATX header survived: {line!r}",
            )

    def test_no_hr_divider_survives(self):
        out = telegram_format(GOLDMAN_OPEN_INVOICES)
        for line in out.split("\n"):
            self.assertNotRegex(line.strip(), r"^---+$", f"--- divider survived: {line!r}")

    def test_no_pipe_separator_survives(self):
        out = telegram_format(GOLDMAN_OPEN_INVOICES)
        for line in out.split("\n"):
            self.assertNotRegex(
                line.strip(),
                r"^\|[\-:|\t ]+\|$",
                f"|---|---| separator survived: {line!r}",
            )

    def test_pipe_table_becomes_pre_block(self):
        out = telegram_format(GOLDMAN_OPEN_INVOICES)
        self.assertIn("<pre>", out, "expected at least one <pre> block from the pipe tables")
        # Data must survive whichever layout (horizontal or vertical) the
        # formatter picked. The invoice IDs and client name are the
        # ground-truth payload — both must appear.
        self.assertIn("INV-000081", out)
        self.assertIn("NorthPoint Enterprises Inc", out)

    def test_bold_converted_to_html(self):
        self.assertEqual(
            telegram_format("Revenue dropped **58%** today"),
            "Revenue dropped <b>58%</b> today",
        )

    def test_header_converted_to_html(self):
        self.assertEqual(telegram_format("# Hello world"), "<b>Hello world</b>")
        self.assertEqual(telegram_format("###### Deep section"), "<b>Deep section</b>")

    def test_link_converted_to_html(self):
        out = telegram_format("See [the report](https://example.com/r)")
        self.assertEqual(out, 'See <a href="https://example.com/r">the report</a>')

    def test_html_special_chars_escaped(self):
        # `<`, `>`, `&` in user-visible text must be escaped so they don't
        # break the parser. `**bold**` still converts around the escaped text.
        out = telegram_format("If x < 5 and y > 10 then **AT&T** wins")
        self.assertIn("&lt; 5", out)
        self.assertIn("&gt; 10", out)
        self.assertIn("<b>AT&amp;T</b>", out)

    def test_triple_backtick_code_block_becomes_pre(self):
        out = telegram_format("```python\nprint('hi')\n```")
        self.assertEqual(out, "<pre>print('hi')\n</pre>")

    def test_inline_code_becomes_code(self):
        out = telegram_format("Run `npm install` first")
        self.assertEqual(out, "Run <code>npm install</code> first")

    def test_plain_prose_passes_through(self):
        out = telegram_format("Just a normal sentence. Nothing to convert.")
        self.assertEqual(out, "Just a normal sentence. Nothing to convert.")

    def test_empty_input_returns_empty(self):
        self.assertEqual(telegram_format(""), "")

    def test_full_goldman_reply_produces_clean_html(self):
        out = telegram_format(GOLDMAN_OPEN_INVOICES)
        # Should contain at least one <pre> for the tables AND multiple <b>
        # tags for the bold spans / headers.
        self.assertGreaterEqual(out.count("<pre>"), 2, "expected ≥2 pipe tables")
        self.assertGreater(out.count("<b>"), 5, "expected several <b> tags")
        # The literal ugly markers must be gone.
        self.assertNotIn("**", out)
        self.assertNotIn("###", out)
        self.assertNotIn("|---|", out)

    # ────────────────────────────────────────────────────────────────────
    # Wide-table → vertical layout (2026-06-11 regression):
    # Goldman's last-invoice comparison reply rendered as a 6-column
    # monospace table that wrapped on mobile, collapsing the columns. Wide
    # tables should now flip to a vertical title + label/value layout.
    # ────────────────────────────────────────────────────────────────────

    GOLDMAN_LAST_INVOICE_COMPARISON = (
        "Here's the comparison:\n\n"
        "| Entity | Last Invoice | Client | Amount | Status | Due Date |\n"
        "|---|---|---|---|---|---|\n"
        "| AMZ-Expert Global (HK) | INV-000081 | NorthPoint Enterprises Inc | $1,300.00 | Sent | 2026-05-31 |\n"
        "| Pacific Edge (US) | INV-000027 | Gilad Weinberg | $3,493.89 | Overdue | 2026-04-07 |\n\n"
        "Worth noting: the Pacific Edge invoice (**INV-000027** for Gilad Weinberg) is **overdue** — "
        "would you like me to draft a payment reminder for that one?"
    )

    def test_wide_table_uses_vertical_layout(self):
        out = telegram_format(self.GOLDMAN_LAST_INVOICE_COMPARISON)
        # The table belongs in a <pre> block.
        self.assertIn("<pre>", out)
        # Vertical layout means each header label appears multiple times
        # (once per data row), and each row's title is on its own line.
        # The monospace layout joins them on a single line per row.
        pre_start = out.index("<pre>") + len("<pre>")
        pre_end = out.index("</pre>", pre_start)
        pre_body = out[pre_start:pre_end]
        # In vertical mode, "Last Invoice" appears twice (once per data row);
        # in horizontal mode it appears once (header row only).
        self.assertEqual(
            pre_body.count("Last Invoice"),
            2,
            f"expected vertical layout (2x 'Last Invoice'), got: {pre_body!r}",
        )
        # Both entity titles must be present as their own lines.
        self.assertIn("AMZ-Expert Global (HK)", pre_body)
        self.assertIn("Pacific Edge (US)", pre_body)
        # The label-value pairs should still be there.
        self.assertIn("INV-000081", pre_body)
        self.assertIn("Overdue", pre_body)

    def test_narrow_table_stays_horizontal(self):
        # A small 2x3 table well within the 42-char monospace budget
        # should stay as horizontal aligned columns — the vertical
        # fallback is only for wide tables.
        narrow = "| SKU | Units |\n|---|---|\n| A | 5 |\n| B | 12 |"
        out = telegram_format(narrow)
        pre_start = out.index("<pre>") + len("<pre>")
        pre_end = out.index("</pre>", pre_start)
        pre_body = out[pre_start:pre_end]
        # In horizontal mode, "Units" appears once (header row only).
        self.assertEqual(pre_body.count("Units"), 1, f"narrow table should stay horizontal: {pre_body!r}")
        # Both data rows live on a single line — A and 5 on the same row,
        # B and 12 on the same row.
        for line in pre_body.split("\n"):
            if line.lstrip().startswith("A"):
                self.assertIn("5", line, f"A and 5 should share a line: {line!r}")
            if line.lstrip().startswith("B"):
                self.assertIn("12", line, f"B and 12 should share a line: {line!r}")


if __name__ == "__main__":
    unittest.main()
