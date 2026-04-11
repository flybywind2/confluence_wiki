# Confluence HTML Parser Design

## Goal

Improve `storage_to_markdown()` so Confluence storage HTML preserves more structure when building raw markdown for wiki generation.

## Scope

- Confluence **본문 HTML** only
- Better handling for:
  - headings
  - paragraphs
  - nested lists
  - images and Confluence attachments
  - tables
  - blockquotes
  - Confluence macros such as `info`, `note`, `warning`, `expand`, and `code`

## Recommended Approach

Use a block-oriented parser with explicit Confluence rules instead of a single flat BeautifulSoup pass.

- Keep the current markdown output contract
- Reuse `render_table_block()` for tables
- Add a small Confluence-aware block renderer that:
  - walks top-level and nested blocks
  - renders inline links/images with existing placeholders
  - converts common macros to callout/code markdown

## Why This Approach

- General HTML-to-markdown conversion is too lossy for Confluence storage HTML
- The current parser collapses macro boundaries and nested structure too early
- A Confluence-specific parser is easier to reason about than adding many one-off fallbacks later

## Testing Strategy

Add parser tests first for:

- page links
- nested lists
- info/expand/code macros
- attachment images
- tables remaining intact

## Risks

- Macro coverage is never complete; implement the common macros first and keep safe text fallback for unknown macros
- HTML parser behavior around namespaced tags can vary; tests should use realistic Confluence snippets
