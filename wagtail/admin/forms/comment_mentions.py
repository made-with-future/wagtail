import json

from django import forms
from django.core.exceptions import ValidationError
from django.forms.fields import InvalidJSONInput
from django.utils.translation import gettext_lazy as _

from wagtail.admin.comment_mentions import (
    MAX_MENTION_JSON_BYTES,
    MentionChanges,
    compare_mentions,
    sanitize_stored_mentions,
    validate_mention_occurrences,
    validate_retained_mentions,
)

MENTIONS_OMITTED = object()


class CommentMentionsInput(forms.HiddenInput):
    def value_from_datadict(self, data, files, name):
        if name not in data:
            return MENTIONS_OMITTED
        return data[name]


class CommentMentionsField(forms.JSONField):
    widget = CommentMentionsInput
    default_error_messages = {
        "invalid": _("Enter a valid mention list."),
    }

    def bound_data(self, data, initial):
        if data is MENTIONS_OMITTED:
            return initial
        return InvalidJSONInput(data if isinstance(data, str) else "")

    def _validate_raw_value(self, value):
        if not isinstance(value, str) or not value:
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        try:
            value_size = len(value.encode("utf-8"))
        except UnicodeEncodeError as error:
            raise ValidationError(
                self.error_messages["invalid"], code="invalid"
            ) from error
        if value_size > MAX_MENTION_JSON_BYTES:
            raise ValidationError(self.error_messages["invalid"], code="invalid")

    def to_python(self, value):
        if value is MENTIONS_OMITTED:
            return MENTIONS_OMITTED
        self._validate_raw_value(value)
        try:
            return super().to_python(value)
        except (RecursionError, ValueError, ValidationError) as error:
            raise ValidationError(
                self.error_messages["invalid"], code="invalid"
            ) from error

    def prepare_value(self, value):
        if isinstance(value, InvalidJSONInput):
            return value
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def has_changed(self, initial, data):
        if data is MENTIONS_OMITTED:
            return False
        return super().has_changed(initial, data)


class MentionedMessageFormMixin:
    mention_validation_error = _("Enter a valid mention list.")

    def __init__(self, *args, page=None, parent_page=None, **kwargs):
        self.page = page
        self.parent_page = parent_page
        self.mention_changes = MentionChanges()
        super().__init__(*args, **kwargs)
        self.initial["mentions"] = self._initial_mentions()

    def _initial_mentions(self):
        return list(
            sanitize_stored_mentions(
                self.instance.mentions,
                text=self.instance.text,
                message_id=self.instance.pk,
            )
        )

    def clean_mentions(self):
        initial = self._initial_mentions()
        submitted = self.cleaned_data["mentions"]
        if submitted is MENTIONS_OMITTED:
            submitted = initial
        try:
            current = list(
                validate_mention_occurrences(
                    submitted,
                    text=self.cleaned_data.get("text", self.instance.text),
                )
            )
            validate_retained_mentions(initial, current)
        except ValidationError as error:
            raise ValidationError(self.mention_validation_error) from error
        self.mention_changes = compare_mentions(initial, current)
        return current

    def serialized_mentions(self, *, bound):
        if bound and "mentions" in getattr(self, "cleaned_data", {}):
            return list(self.cleaned_data["mentions"])
        return self._initial_mentions()
