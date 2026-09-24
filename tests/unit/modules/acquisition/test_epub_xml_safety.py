from __future__ import annotations

import zipfile

import pytest

from novelwiki.modules.acquisition.adapters.outbound.importer.parsers import epub


def _archive(tmp_path, package, container=None):
    path = tmp_path / "book.epub"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("book.opf", package)
        if container:
            archive.writestr("META-INF/container.xml", container)
        archive.writestr("chapter.xhtml", "<html><body><p>First chapter.</p></body></html>")
    return path


def _package(title):
    return (
        '<package xmlns="http://www.idpf.org/2007/opf" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<metadata><dc:title>{title}</dc:title></metadata>"
        '<manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest>'
        '<spine><itemref idref="chapter"/></spine></package>'
    )


@pytest.mark.parametrize("entity", ['"Expanded title"', 'SYSTEM "file:///etc/hostname"'])
def test_package_entity_declarations_are_rejected(tmp_path, entity):
    path = _archive(tmp_path, f"<!DOCTYPE package [<!ENTITY title {entity}>]>" + _package("&title;"))

    with pytest.raises(ValueError, match="entity"):
        epub.parse_epub(str(path), 1)


def test_container_entities_cannot_choose_package_path(tmp_path):
    container = (
        '<!DOCTYPE container [<!ENTITY path "book.opf">]>'
        '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="&path;"/></rootfiles></container>'
    )
    path = _archive(tmp_path, _package("Valid book"), container)

    with pytest.raises(ValueError, match="entity"):
        epub.parse_epub(str(path), 1)


def test_external_dtd_is_not_loaded(tmp_path):
    dtd = tmp_path / "external.dtd"
    dtd.write_text('<!ATTLIST package injected CDATA "unexpected">', encoding="utf-8")
    root = epub._parse_xml(
        f'<!DOCTYPE package SYSTEM "{dtd.as_uri()}"><package/>'.encode(),
    )

    assert root.attrib == {}


def test_valid_epub_preserves_builtin_entities_and_closes_archive(tmp_path, monkeypatch):
    path = _archive(tmp_path, _package("Tide &amp; Glass"))
    opened = []
    original_open = zipfile.ZipFile

    def capture(*args, **kwargs):
        archive = original_open(*args, **kwargs)
        opened.append(archive)
        return archive

    monkeypatch.setattr(epub.zipfile, "ZipFile", capture)

    document = epub.parse_epub(str(path), 1)

    assert document.meta["title"] == "Tide & Glass"
    assert document.blocks[0].text == "First chapter."
    assert opened[0].fp is None


def test_invalid_package_closes_archive(tmp_path, monkeypatch):
    path = _archive(tmp_path, "<broken")
    opened = []
    original_open = zipfile.ZipFile

    def capture(*args, **kwargs):
        archive = original_open(*args, **kwargs)
        opened.append(archive)
        return archive

    monkeypatch.setattr(epub.zipfile, "ZipFile", capture)

    with pytest.raises(epub.etree.XMLSyntaxError):
        epub.parse_epub(str(path), 1)

    assert opened[0].fp is None
