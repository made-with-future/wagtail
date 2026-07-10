import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Sequence, TypedDict

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from wagtail.admin.templatetags.wagtailadmin_tags import user_display_name

MAX_MENTIONS = 20
MAX_MENTION_LABEL_UTF16 = 255
MAX_MENTION_JSON_BYTES = 16 * 1024
MAX_QUERY_UTF16 = 64
RESULT_LIMIT = 10

logger = logging.getLogger("wagtail.admin.comment_mentions")

_INVALID_MENTIONS_MESSAGE = "Enter a valid mention list."


class MentionOccurrence(TypedDict):
    key: str
    user_id: str
    start: int
    end: int
    label: str


@dataclass(frozen=True)
class MentionChanges:
    added: tuple[MentionOccurrence, ...] = ()
    removed: tuple[MentionOccurrence, ...] = ()


def utf16_length(value: str) -> int:
    try:
        return len(value.encode("utf-16-le")) // 2
    except UnicodeEncodeError as error:
        raise ValidationError("Invalid UTF-16 text boundary.") from error


def utf16_slice(value: str, start: int, end: int) -> str:
    try:
        encoded = value.encode("utf-16-le")
        return encoded[start * 2 : end * 2].decode("utf-16-le")
    except (UnicodeDecodeError, UnicodeEncodeError) as error:
        raise ValidationError("Invalid UTF-16 text boundary.") from error


def truncate_utf16(value: str, limit: int) -> str:
    if utf16_length(value) <= limit:
        return value
    result = ""
    for character in value:
        if utf16_length(result + character + "…") > limit:
            break
        result += character
    return result + "…"


def current_mention_email(user) -> str:
    email_field = user.get_email_field_name()
    return re.sub(r"\s+", " ", str(getattr(user, email_field, "") or "")).strip()


def normalize_mention_label(user) -> str:
    identity = current_mention_email(user)
    if not identity:
        identity = re.sub(r"\s+", " ", user_display_name(user)).strip()
    if not identity:
        identity = re.sub(r"\s+", " ", str(user.get_username())).strip()
    return truncate_utf16(f"@{identity}", MAX_MENTION_LABEL_UTF16)


def _validate_mention_json_size(value: object) -> None:
    try:
        compact_value = json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError) as error:
        raise ValidationError(_INVALID_MENTIONS_MESSAGE) from error
    if len(compact_value) > MAX_MENTION_JSON_BYTES:
        raise ValidationError(_INVALID_MENTIONS_MESSAGE)


def validate_mention_occurrences(
    value: object, *, text: str
) -> tuple[MentionOccurrence, ...]:
    if not isinstance(value, list) or len(value) > MAX_MENTIONS:
        raise ValidationError(_INVALID_MENTIONS_MESSAGE)
    _validate_mention_json_size(value)
    if not isinstance(text, str):
        raise ValidationError(_INVALID_MENTIONS_MESSAGE)

    expected_fields = {"key", "user_id", "start", "end", "label"}
    user_pk_field = get_user_model()._meta.pk
    canonical: list[MentionOccurrence] = []
    keys = set()

    for occurrence in value:
        if not isinstance(occurrence, dict) or set(occurrence) != expected_fields:
            raise ValidationError(_INVALID_MENTIONS_MESSAGE)

        key_value = occurrence["key"]
        if not isinstance(key_value, str):
            raise ValidationError(_INVALID_MENTIONS_MESSAGE)
        try:
            key = str(uuid.UUID(key_value))
        except (AttributeError, TypeError, ValueError) as error:
            raise ValidationError(_INVALID_MENTIONS_MESSAGE) from error
        if key in keys:
            raise ValidationError(_INVALID_MENTIONS_MESSAGE)
        keys.add(key)

        user_id_value = occurrence["user_id"]
        if isinstance(user_id_value, bool) or not isinstance(user_id_value, (int, str)):
            raise ValidationError(_INVALID_MENTIONS_MESSAGE)
        try:
            parsed_user_id = user_pk_field.to_python(user_id_value)
            prepared_user_id = user_pk_field.get_prep_value(parsed_user_id)
        except (OverflowError, TypeError, ValueError, ValidationError) as error:
            raise ValidationError(_INVALID_MENTIONS_MESSAGE) from error
        if parsed_user_id is None or prepared_user_id is None:
            raise ValidationError(_INVALID_MENTIONS_MESSAGE)
        raw_user_id = str(user_id_value)
        parsed_user_id = str(parsed_user_id)
        prepared_user_id = str(prepared_user_id)
        # Custom PK fields can expose distinct prepared and display strings. Preserve a
        # representation that already round-trips; otherwise use the parsed value.
        if raw_user_id in {parsed_user_id, prepared_user_id}:
            user_id = raw_user_id
        else:
            user_id = parsed_user_id

        start = occurrence["start"]
        end = occurrence["end"]
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
        ):
            raise ValidationError(_INVALID_MENTIONS_MESSAGE)

        label = occurrence["label"]
        if not isinstance(label, str):
            raise ValidationError(_INVALID_MENTIONS_MESSAGE)
        if utf16_length(label) > MAX_MENTION_LABEL_UTF16:
            raise ValidationError(_INVALID_MENTIONS_MESSAGE)

        canonical.append(
            {
                "key": key,
                "user_id": user_id,
                "start": start,
                "end": end,
                "label": label,
            }
        )

    _validate_mention_json_size(canonical)
    ordered = sorted(
        canonical, key=lambda item: (item["start"], item["end"], item["key"])
    )
    if canonical != ordered:
        raise ValidationError(_INVALID_MENTIONS_MESSAGE)

    text_length = utf16_length(text)
    previous_end = 0
    for occurrence in ordered:
        start = occurrence["start"]
        end = occurrence["end"]
        if start < previous_end or start < 0 or end <= start or end > text_length:
            raise ValidationError(_INVALID_MENTIONS_MESSAGE)
        if utf16_slice(text, start, end) != occurrence["label"]:
            raise ValidationError(_INVALID_MENTIONS_MESSAGE)
        previous_end = end

    return tuple(ordered)


def validate_retained_mentions(
    initial: Sequence[MentionOccurrence], current: Sequence[MentionOccurrence]
) -> None:
    initial_by_key = {occurrence["key"]: occurrence for occurrence in initial}
    for occurrence in current:
        retained = initial_by_key.get(occurrence["key"])
        if retained is not None and (
            retained["user_id"] != occurrence["user_id"]
            or retained["label"] != occurrence["label"]
        ):
            raise ValidationError(_INVALID_MENTIONS_MESSAGE)


def compare_mentions(
    initial: Sequence[MentionOccurrence], current: Sequence[MentionOccurrence]
) -> MentionChanges:
    initial_keys = {occurrence["key"] for occurrence in initial}
    current_keys = {occurrence["key"] for occurrence in current}
    return MentionChanges(
        added=tuple(
            occurrence
            for occurrence in current
            if occurrence["key"] not in initial_keys
        ),
        removed=tuple(
            occurrence
            for occurrence in initial
            if occurrence["key"] not in current_keys
        ),
    )


def sanitize_stored_mentions(
    value: object, *, text: str, message_id: object
) -> tuple[MentionOccurrence, ...]:
    if not isinstance(value, list):
        logger.warning(
            "Ignoring invalid stored comment mention for message %s.", message_id
        )
        return ()
    try:
        _validate_mention_json_size(value)
    except ValidationError:
        logger.warning(
            "Ignoring invalid stored comment mention for message %s.", message_id
        )
        return ()

    accepted: list[MentionOccurrence] = []
    for occurrence in value:
        try:
            accepted = list(
                validate_mention_occurrences([*accepted, occurrence], text=text)
            )
        except ValidationError:
            logger.warning(
                "Ignoring invalid stored comment mention for message %s.", message_id
            )
    return tuple(accepted)


def split_text_by_mentions(
    text: str, mentions: Sequence[MentionOccurrence]
) -> tuple[tuple[str, bool], ...]:
    segments: list[tuple[str, bool]] = []
    cursor = 0
    text_length = utf16_length(text)
    for occurrence in mentions:
        start = occurrence["start"]
        end = occurrence["end"]
        if cursor < start:
            segments.append((utf16_slice(text, cursor, start), False))
        segments.append((utf16_slice(text, start, end), True))
        cursor = end

    if cursor < text_length:
        segments.append((utf16_slice(text, cursor, text_length), False))
    return tuple(segments)
