"""File-import pipeline (EPUB/PDF → chapters).

Everything funnels through one normalized IR (``ir.Document``/``ir.Block``): parsers
produce it, cleanup/segment/render/commit operate only on it, and commit reuses the
exact scraper persist path so codex + translation come for free. See the design doc
for the slice plan (S0 foundation, S1 EPUB, S2 digital PDF, S3 scanned/OCR).
"""
