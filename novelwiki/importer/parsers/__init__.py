"""Format parsers. Each turns one input format into a normalized ``ir.Document``.

Only this package knows about format-specific structure (EPUB XHTML/OPF, PDF spans,
OCR blocks). Everything downstream (cleanup, segment, render, commit) is format-blind.
"""
