import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Sequence, TypedDict

from django.conf import settings
from django.contrib.auth import get_permission_codename, get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404
from django.utils.translation import gettext_lazy as _

from wagtail.admin.templatetags.wagtailadmin_tags import user_display_name
from wagtail.models import GroupPagePermission, Page
from wagtail.permissions import page_permission_policy

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


class InvalidMentionTargets(ValidationError):
    def __init__(self, invalid_indices):
        self.invalid_indices = tuple(invalid_indices)
        super().__init__(_(_INVALID_MENTIONS_MESSAGE), code="invalid")


def users_with_admin_access(queryset):
    access_admin = Permission.objects.get(
        content_type__app_label="wagtailadmin",
        codename="access_admin",
    )
    return (
        queryset.filter(is_active=True)
        .filter(
            Q(is_superuser=True)
            | Q(user_permissions=access_admin)
            | Q(groups__permissions=access_admin)
        )
        .distinct()
    )


def page_mention_candidates(page):
    return users_with_admin_access(
        page_permission_policy.users_with_permission_for_instance("change", page)
    )


def future_page_mention_candidates(*, parent_page, owner):
    ancestors = parent_page.get_ancestors(inclusive=True)
    change_groups = GroupPagePermission.objects.filter(
        page__in=ancestors,
        permission__codename=get_permission_codename("change", Page._meta),
    ).values("group_id")
    add_groups = GroupPagePermission.objects.filter(
        page__in=ancestors,
        permission__codename=get_permission_codename("add", Page._meta),
    ).values("group_id")
    users = (
        get_user_model()
        ._default_manager.filter(is_active=True)
        .filter(
            Q(is_superuser=True)
            | Q(groups__in=change_groups)
            | (Q(pk=owner.pk) & Q(groups__in=add_groups))
        )
    )
    return users_with_admin_access(users)


def comments_available_for_page_model(page_model: type[Page]) -> bool:
    if not getattr(settings, "WAGTAILADMIN_COMMENTS_ENABLED", True):
        return False
    form_class = page_model.get_edit_handler().get_form_class()
    return "comments" in form_class.formsets


def _mention_search_fields():
    user_model = get_user_model()
    available_fields = {field.name for field in user_model._meta.concrete_fields}
    fields = []
    for field_name in (
        "first_name",
        "last_name",
        user_model.get_email_field_name(),
        user_model.USERNAME_FIELD,
    ):
        if field_name in available_fields and field_name not in fields:
            fields.append(field_name)
    return fields


def search_mention_candidates(candidates, query: str) -> list[dict[str, str]]:
    if not isinstance(query, str):
        return []
    query = query.strip()
    try:
        if not query or utf16_length(query) > MAX_QUERY_UTF16:
            return []
    except ValidationError:
        return []

    search_filter = Q()
    for field_name in _mention_search_fields():
        search_filter |= Q(**{f"{field_name}__icontains": query})

    user_model = get_user_model()
    users = (
        candidates.filter(search_filter)
        .distinct()
        .order_by(
            user_model.USERNAME_FIELD,
            user_model._meta.pk.name,
        )[:RESULT_LIMIT]
    )
    results = []
    for user in users:
        email = current_mention_email(user)
        label = normalize_mention_label(user)
        result = {
            "id": str(user.pk),
            "label": label,
            "email": email,
        }
        username = str(user.get_username())
        normalized_username = re.sub(r"\s+", " ", username).strip()
        if normalized_username and normalized_username not in {
            email,
            label.removeprefix("@"),
        }:
            result["username"] = username
        results.append(result)
    return results


def resolve_new_mention_users(occurrences, candidates) -> tuple[object, ...]:
    occurrences = tuple(occurrences)
    if not occurrences:
        return ()

    user_model = get_user_model()
    pk_field = user_model._meta.pk
    prepared_ids = []
    invalid_indices = []
    for index, occurrence in enumerate(occurrences):
        try:
            parsed_id = pk_field.to_python(occurrence["user_id"])
            prepared_id = pk_field.get_prep_value(parsed_id)
        except (KeyError, OverflowError, TypeError, ValueError, ValidationError):
            invalid_indices.append(index)
            prepared_ids.append(None)
        else:
            prepared_ids.append(str(prepared_id))

    query_ids = {prepared_id for prepared_id in prepared_ids if prepared_id is not None}
    try:
        users = list(candidates.filter(pk__in=query_ids)) if query_ids else []
    except (OverflowError, TypeError, ValueError, ValidationError) as error:
        raise InvalidMentionTargets(range(len(occurrences))) from error
    users_by_prepared_id = {
        str(pk_field.get_prep_value(user.pk)): user for user in users
    }

    resolved = []
    invalid_index_set = set(invalid_indices)
    for index, (occurrence, prepared_id) in enumerate(
        zip(occurrences, prepared_ids, strict=True)
    ):
        user = users_by_prepared_id.get(prepared_id)
        if user is None or occurrence.get("label") != normalize_mention_label(user):
            invalid_index_set.add(index)
            resolved.append(None)
        else:
            resolved.append(user)

    if invalid_index_set:
        raise InvalidMentionTargets(sorted(invalid_index_set))
    return tuple(resolved)


def resolve_creatable_page_model(
    request, parent_page, app_label, model_name
) -> type[Page]:
    if not parent_page.permissions_for_user(request.user).can_add_subpage():
        raise PermissionDenied
    try:
        page_content_type = ContentType.objects.get_by_natural_key(
            app_label, model_name
        )
    except ContentType.DoesNotExist as error:
        raise Http404 from error

    page_model = page_content_type.model_class()
    if page_model is None or not issubclass(page_model, Page):
        raise Http404
    if page_model not in parent_page.creatable_subpage_models():
        raise PermissionDenied
    if not page_model.can_create_at(parent_page):
        raise PermissionDenied
    return page_model


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
            user_pk_field.run_validators(prepared_user_id)
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


def sync_message_mention_lookups(*, message, occurrences) -> None:
    from wagtail.models import (
        Comment,
        CommentMention,
        CommentReply,
        CommentReplyMention,
    )

    if isinstance(message, Comment):
        lookup_model = CommentMention
        message_field = "comment"
    elif isinstance(message, CommentReply):
        lookup_model = CommentReplyMention
        message_field = "reply"
    else:
        raise TypeError("Mention lookups require a comment or comment reply.")

    target_ids = {occurrence["user_id"] for occurrence in occurrences}
    users = list(get_user_model()._default_manager.filter(pk__in=target_ids))
    message_lookups = lookup_model.objects.filter(**{message_field: message})
    if users:
        message_lookups.exclude(user__in=users).delete()
    else:
        message_lookups.delete()

    existing_user_ids = set(
        lookup_model.objects.filter(
            **{message_field: message}, user__in=users
        ).values_list("user_id", flat=True)
    )
    lookup_model.objects.bulk_create(
        [
            lookup_model(**{message_field: message}, user=user)
            for user in users
            if user.pk not in existing_user_ids
        ],
        ignore_conflicts=True,
    )


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
