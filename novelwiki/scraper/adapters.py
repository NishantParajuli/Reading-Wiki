import re
import logging
from selectolax.parser import HTMLParser
from novelwiki.config.settings import settings

logger = logging.getLogger(__name__)


def _absolutize(href: str, current_url: str) -> str:
    if not href or href == "#":
        return ""
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        match = re.match(r"(https?://[^/]+)", current_url)
        domain = match.group(1) if match else settings.SCRAPER_BASE_URL.rstrip("/")
        return f"{domain}{href}"
    return href


def parse_chapter_number(url: str, title: str) -> float | None:
    """Parses a chapter number (int or float) from a title or URL. Shared by adapters."""
    title_clean = re.sub(r"\s+", " ", title or "")

    match = re.search(r"(?i)chapter\s+(\d+(?:\.\d+)?)", title_clean)
    if match:
        return float(match.group(1))

    match = re.search(r"(?i)\bch\b\.?\s*(\d+(?:\.\d+)?)", title_clean)
    if match:
        return float(match.group(1))

    match = re.search(r"(?i)chapter-(\d+(?:[.-]\d+)?)", url or "")
    if match:
        raw_num = match.group(1)
        if "-" in raw_num:
            raw_num = raw_num.replace("-", ".")
        try:
            return float(raw_num)
        except ValueError:
            pass

    match = re.search(r"\b(\d+(?:\.\d+)?)\b", title_clean)
    if match:
        return float(match.group(1))

    return None


class BaseAdapter:
    """Base interface for all site-specific adapters."""
    def extract_title(self, parser: HTMLParser) -> str:
        raise NotImplementedError()

    def extract_content(self, parser: HTMLParser) -> str:
        raise NotImplementedError()

    def extract_next_url(self, parser: HTMLParser, current_url: str) -> str:
        raise NotImplementedError()

    def extract_chapter_number(self, url: str, title: str) -> float | None:
        return parse_chapter_number(url, title)


class GenericAdapter(BaseAdapter):
    """Config-driven adapter: reads CSS selectors from settings so a new site can be
    supported without code (set SCRAPER_ADAPTER=generic and the SCRAPER_*_SELECTOR vars)."""

    def extract_title(self, parser: HTMLParser) -> str:
        node = parser.css_first(settings.SCRAPER_TITLE_SELECTOR)
        return node.text(strip=True) if node else "Untitled Chapter"

    def extract_content(self, parser: HTMLParser) -> str:
        for sel in ("script", "style", "nav", ".ads", ".comments", ".navigation"):
            for node in parser.css(sel):
                node.decompose()
        node = parser.css_first(settings.SCRAPER_CONTENT_SELECTOR)
        if not node:
            return ""
        paragraphs = [p.text(strip=True) for p in node.css("p") if p.text(strip=True)]
        if not paragraphs:
            raw = node.text(separator="\n", strip=True)
            paragraphs = [p.strip() for p in raw.split("\n") if p.strip()]
        return "\n\n".join(paragraphs)

    def extract_next_url(self, parser: HTMLParser, current_url: str) -> str:
        node = parser.css_first(settings.SCRAPER_NEXT_SELECTOR)
        if node:
            return _absolutize(node.attributes.get("href", ""), current_url)
        return ""

class FenriRealmAdapter(BaseAdapter):
    """Concrete adapter for fenrirealm.com."""
    
    def extract_title(self, parser: HTMLParser) -> str:
        # Selectors to try
        selectors = [
            "h1.line-clamp-1", 
            "h1.font-outfit",
            ".chapter-title",
            "h2",
            "h1"
        ]
        for sel in selectors:
            node = parser.css_first(sel)
            if node:
                text = node.text(strip=True)
                if text:
                    return text
        return "Untitled Chapter"

    def extract_content(self, parser: HTMLParser) -> str:
        # Selectors to try for main text
        content_selectors = [
            "div.content-area",
            "div.chapter-view",
            "#reader-area",
            ".entry-content",
            "article",
            "div.reader-content"
        ]
        
        # Elements we want to remove/clean
        remove_selectors = [
            "div.my-2", 
            "div.hidden.text-center.text-zinc-500", 
            "div.my-10.border-t-4.border-dashed.pt-5",
            "script",
            "style",
            "nav",
            ".ads",
            ".comments",
            ".navigation",
            "div.flex.justify-between.my-5" # common pagination containers
        ]

        # First, strip unwanted nodes
        for sel in remove_selectors:
            for node in parser.css(sel):
                node.decompose()

        # Find the content node
        for sel in content_selectors:
            node = parser.css_first(sel)
            if node:
                paragraphs = []
                # Keep paragraph structures or fallback to plain text with breaks
                p_nodes = node.css("p")
                if p_nodes:
                    for p in p_nodes:
                        text = p.text(strip=True)
                        if text:
                            paragraphs.append(text)
                
                # If no <p> tags, split by divs or text
                if not paragraphs:
                    raw_text = node.text(separator="\n", strip=True)
                    paragraphs = [p.strip() for p in raw_text.split("\n") if p.strip()]
                
                content = "\n\n".join(paragraphs)
                if len(content) > 100: # sanity check for length
                    return content
                    
        # Ultimate fallback - grab body
        body = parser.css_first("body")
        if body:
            return body.text(separator="\n\n", strip=True)
        return ""

    def extract_next_url(self, parser: HTMLParser, current_url: str) -> str:
        # Try links that have 'next' in their class, text, or relations
        for node in parser.css("a"):
            rel = node.attributes.get("rel", "") or ""
            href = node.attributes.get("href", "") or ""
            text = node.text(strip=True).lower()

            if not href or href == "#":
                continue

            if "next" in rel.lower() or "next" in text or "next" in (node.attributes.get("class", "") or "").lower():
                return _absolutize(href, current_url)
        return ""

    # extract_chapter_number is inherited from BaseAdapter (parse_chapter_number).


# ── Adapter registry ────────────────────────────────────────────────────────
ADAPTERS: dict[str, type[BaseAdapter]] = {
    "fenrirealm": FenriRealmAdapter,
    "generic": GenericAdapter,
}


def get_adapter(name: str | None = None) -> BaseAdapter:
    """Returns the configured site adapter (defaults to settings.SCRAPER_ADAPTER)."""
    key = (name or settings.SCRAPER_ADAPTER or "fenrirealm").lower()
    cls = ADAPTERS.get(key)
    if cls is None:
        logger.warning(f"Unknown SCRAPER_ADAPTER '{key}', falling back to 'fenrirealm'.")
        cls = FenriRealmAdapter
    return cls()
