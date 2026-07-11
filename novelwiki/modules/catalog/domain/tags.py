from __future__ import annotations

from novelwiki.kernel.errors import ValidationFailed

STATUS_TAG_RADIO_GROUPS = {
    "status": ["ongoing", "finished", "hiatus"],
    "translation": ["translation_ongoing", "translation_completed"],
}
RADIO_TAGS = {
    tag for members in STATUS_TAG_RADIO_GROUPS.values() for tag in members
}
GENRE_TAGS = {
    "action", "adventure", "romance", "fantasy", "sci_fi", "comedy",
    "drama", "horror", "mystery", "slice_of_life",
}
STATUS_TAGS = RADIO_TAGS | GENRE_TAGS


def clean_status_tags(raw: list[str] | None) -> list[str]:
    tags = [tag.strip().lower() for tag in (raw or [])]
    tags = [tag for tag in dict.fromkeys(tags) if tag in STATUS_TAGS]
    for group, members in STATUS_TAG_RADIO_GROUPS.items():
        if sum(tag in members for tag in tags) > 1:
            raise ValidationFailed(
                f"At most one '{group}' tag may be set ({', '.join(members)})."
            )
    return tags
