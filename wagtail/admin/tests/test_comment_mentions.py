import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from wagtail.admin.comment_mentions import (
    MAX_MENTION_JSON_BYTES,
    MAX_MENTION_LABEL_UTF16,
    compare_mentions,
    current_mention_email,
    normalize_mention_label,
    sanitize_stored_mentions,
    split_text_by_mentions,
    truncate_utf16,
    utf16_length,
    utf16_slice,
    validate_mention_occurrences,
    validate_retained_mentions,
)

MENTION_KEY = "29cc6a1f-00ed-41d7-94b1-d46a947962cb"
SECOND_MENTION_KEY = "327547cc-f9ee-4bce-852f-bf96f14179b9"


def mention_occurrence(**overrides):
    occurrence = {
        "key": MENTION_KEY,
        "user_id": "1",
        "start": 0,
        "end": 3,
        "label": "@Jo",
    }
    occurrence.update(overrides)
    return occurrence


def oversized_mention_list():
    text = " ".join(["@Jo"] * 20)
    value = [
        mention_occurrence(
            key=f"00000000-0000-0000-0000-{index + 1:012x}",
            user_id="1" * 900,
            start=index * 4,
            end=index * 4 + 3,
        )
        for index in range(20)
    ]
    return value, text


class TestUTF16Helpers(SimpleTestCase):
    def test_non_bmp_character_uses_two_units(self):
        self.assertEqual(utf16_length("A😀B"), 4)
        self.assertEqual(utf16_slice("A😀B", 1, 3), "😀")

    def test_surrogate_split_is_rejected(self):
        with self.assertRaises(ValidationError):
            utf16_slice("A😀B", 1, 2)

    def test_truncation_preserves_utf16_boundaries(self):
        self.assertEqual(truncate_utf16("A😀B", 4), "A😀B")
        self.assertEqual(truncate_utf16("A😀B", 3), "A…")


class TestMentionOccurrenceValidation(TestCase):
    def test_valid_occurrence_is_canonicalized(self):
        value = [
            {
                "key": "29cc6a1f-00ed-41d7-94b1-d46a947962cb",
                "user_id": "1",
                "start": 4,
                "end": 7,
                "label": "@Jo",
            }
        ]
        self.assertEqual(
            validate_mention_occurrences(value, text="A😀 @Jo"),
            tuple(value),
        )

    def test_outer_value_must_be_a_list(self):
        for value in ({}, "[]", None):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    validate_mention_occurrences(value, text="")

    def test_occurrence_requires_exact_fields(self):
        missing = mention_occurrence()
        missing.pop("label")
        extra = mention_occurrence(extra="value")

        for value in (missing, extra):
            with self.subTest(fields=set(value)):
                with self.assertRaises(ValidationError):
                    validate_mention_occurrences([value], text="@Jo")

    def test_keys_must_be_unique_valid_uuids(self):
        cases = {
            "invalid": [mention_occurrence(key="not-a-uuid")],
            "duplicate": [
                mention_occurrence(),
                mention_occurrence(start=4, end=7),
            ],
        }

        for name, value in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    validate_mention_occurrences(value, text="@Jo @Jo")

    def test_uuid_keys_are_canonicalized(self):
        value = [mention_occurrence(key=MENTION_KEY.replace("-", "").upper())]

        result = validate_mention_occurrences(value, text="@Jo")

        self.assertEqual(result[0]["key"], MENTION_KEY)

    def test_user_id_rejects_boolean_collection_and_null_values(self):
        for user_id in (True, False, [], {}, (), None):
            with self.subTest(user_id=user_id):
                with self.assertRaises(ValidationError):
                    validate_mention_occurrences(
                        [mention_occurrence(user_id=user_id)], text="@Jo"
                    )

    def test_numeric_and_string_user_ids_have_the_same_canonical_value(self):
        numeric = validate_mention_occurrences(
            [mention_occurrence(user_id=1)], text="@Jo"
        )
        string = validate_mention_occurrences(
            [mention_occurrence(user_id="1")], text="@Jo"
        )

        self.assertEqual(numeric[0]["user_id"], string[0]["user_id"])
        self.assertIsInstance(numeric[0]["user_id"], str)

    def test_user_id_rejects_floating_point_values(self):
        for user_id in (1.0, 1.5):
            with self.subTest(user_id=user_id):
                with self.assertRaises(ValidationError):
                    validate_mention_occurrences(
                        [mention_occurrence(user_id=user_id)], text="@Jo"
                    )

    def test_offsets_must_be_non_boolean_integers(self):
        for field in ("start", "end"):
            for value in (True, 1.5, "1"):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValidationError):
                        validate_mention_occurrences(
                            [mention_occurrence(**{field: value})], text="@Jo"
                        )

    def test_ranges_must_be_sorted_non_overlapping_and_in_bounds(self):
        cases = {
            "unsorted": (
                [
                    mention_occurrence(
                        key=SECOND_MENTION_KEY, start=4, end=7, label="@Al"
                    ),
                    mention_occurrence(),
                ],
                "@Jo @Al",
            ),
            "overlapping": (
                [
                    mention_occurrence(),
                    mention_occurrence(
                        key=SECOND_MENTION_KEY, start=1, end=3, label="Jo"
                    ),
                ],
                "@Jo",
            ),
            "negative": ([mention_occurrence(start=-1, end=2)], "@Jo"),
            "reversed": ([mention_occurrence(start=2, end=1)], "@Jo"),
            "out-of-range": ([mention_occurrence(end=4)], "@Jo"),
        }

        for name, (value, text) in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    validate_mention_occurrences(value, text=text)

    def test_ranges_must_not_split_utf16_surrogates(self):
        value = [mention_occurrence(start=1, end=2, label="😀")]

        with self.assertRaises(ValidationError):
            validate_mention_occurrences(value, text="A😀B")

    def test_selected_text_must_equal_the_label(self):
        with self.assertRaises(ValidationError):
            validate_mention_occurrences([mention_occurrence(label="@Al")], text="@Jo")

    def test_occurrence_count_is_limited(self):
        with self.assertRaises(ValidationError):
            validate_mention_occurrences([{}] * 21, text="")

    def test_compact_json_size_is_limited(self):
        value, text = oversized_mention_list()
        self.assertEqual(len(value), 20)
        compact_size = len(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        self.assertGreater(compact_size, MAX_MENTION_JSON_BYTES)

        with self.assertRaises(ValidationError):
            validate_mention_occurrences(value, text=text)

    def test_label_length_is_limited_in_utf16_units(self):
        label = "@" + "a" * 255

        with self.assertRaises(ValidationError):
            validate_mention_occurrences(
                [mention_occurrence(end=256, label=label)], text=label
            )

    def test_repeated_targets_with_distinct_occurrences_are_accepted(self):
        value = [
            mention_occurrence(),
            mention_occurrence(key=SECOND_MENTION_KEY, start=8, end=11),
        ]

        self.assertEqual(
            validate_mention_occurrences(value, text="@Jo and @Jo"),
            tuple(value),
        )


class TestStoredMentionHandling(SimpleTestCase):
    def test_malformed_entries_are_omitted_without_logging_content(self):
        valid = mention_occurrence()
        malformed = {"private-payload": "do not log this"}
        text = "@Jo private comment text"

        with self.assertLogs(
            "wagtail.admin.comment_mentions", level="WARNING"
        ) as log_output:
            result = sanitize_stored_mentions(
                [valid, malformed], text=text, message_id=987
            )

        self.assertEqual(result, (valid,))
        self.assertEqual(len(log_output.output), 1)
        self.assertIn("987", log_output.output[0])
        self.assertNotIn(text, log_output.output[0])
        self.assertNotIn("private-payload", log_output.output[0])
        self.assertNotIn("do not log this", log_output.output[0])

    def test_oversized_stored_list_is_omitted_without_logging_content(self):
        value, text = oversized_mention_list()

        with self.assertLogs(
            "wagtail.admin.comment_mentions", level="WARNING"
        ) as log_output:
            result = sanitize_stored_mentions(value, text=text, message_id=988)

        self.assertEqual(result, ())
        self.assertEqual(len(log_output.output), 1)
        self.assertIn("988", log_output.output[0])
        self.assertNotIn(value[0]["user_id"], log_output.output[0])

    def test_retained_occurrences_cannot_change_target_or_label(self):
        initial = [mention_occurrence()]
        cases = {
            "target": [mention_occurrence(user_id="2")],
            "label": [mention_occurrence(label="@Al")],
        }

        for name, current in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    validate_retained_mentions(initial, current)

    def test_retained_occurrence_can_shift_with_unchanged_identity(self):
        initial = [mention_occurrence()]
        current = [mention_occurrence(start=5, end=8)]

        self.assertIsNone(validate_retained_mentions(initial, current))

    def test_changes_are_compared_by_occurrence_key(self):
        removed = mention_occurrence(key=SECOND_MENTION_KEY, start=4, end=7)
        retained = mention_occurrence()
        added = mention_occurrence(
            key="cab9e2e7-a2d8-428b-9f1e-9a3e78f04240",
            start=8,
            end=11,
        )

        changes = compare_mentions([retained, removed], [retained, added])

        self.assertEqual(changes.added, (added,))
        self.assertEqual(changes.removed, (removed,))

    def test_split_text_returns_data_segments_without_markup(self):
        text = "😀 <b>@Jo</b> &"
        mentions = [mention_occurrence(start=6, end=9)]

        self.assertEqual(
            split_text_by_mentions(text, mentions),
            (("😀 <b>", False), ("@Jo", True), ("</b> &", False)),
        )


class TestMentionLabels(TestCase):
    def test_current_configured_email_is_normalized_for_the_label(self):
        user = self._make_user(email=" jo\t.smith@example.com ")

        self.assertEqual(current_mention_email(user), "jo .smith@example.com")
        self.assertEqual(normalize_mention_label(user), "@jo .smith@example.com")

    def test_blank_email_falls_back_to_display_name_then_username(self):
        user = self._make_user(
            email="", first_name="Jo", last_name="  Smith", username="jsmith"
        )
        username_only = self._make_user(email="", username="jsmith")

        for candidate, expected in (
            (user, "@Jo Smith"),
            (username_only, "@jsmith"),
        ):
            with self.subTest(expected=expected):
                self.assertEqual(normalize_mention_label(candidate), expected)

    def test_generated_label_is_limited_at_a_utf16_boundary(self):
        user = self._make_user(email="a" * MAX_MENTION_LABEL_UTF16 + "😀")

        label = normalize_mention_label(user)

        self.assertEqual(utf16_length(label), MAX_MENTION_LABEL_UTF16)
        self.assertTrue(label.endswith("…"))

    def test_email_changes_do_not_rewrite_stored_labels(self):
        user = self._make_user(email="before@example.com", username="jo")
        user.save()
        occurrence = mention_occurrence(
            user_id=str(user.pk), end=19, label="@before@example.com"
        )

        email_field = user.get_email_field_name()
        setattr(user, email_field, "after@example.com")
        user.save(update_fields=[email_field])

        self.assertEqual(
            sanitize_stored_mentions(
                [occurrence], text="@before@example.com", message_id=42
            ),
            (occurrence,),
        )
        self.assertEqual(current_mention_email(user), "after@example.com")

    def _make_user(self, *, email, username="jo", first_name="", last_name=""):
        user_model = get_user_model()
        values = {}
        for field, value in (
            (user_model.USERNAME_FIELD, username),
            (user_model.get_email_field_name(), email),
            ("first_name", first_name),
            ("last_name", last_name),
        ):
            if any(
                model_field.name == field for model_field in user_model._meta.fields
            ):
                values[field] = value
        return user_model(**values)
