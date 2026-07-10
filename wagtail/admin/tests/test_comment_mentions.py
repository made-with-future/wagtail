import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db.models.base import ModelBase
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from wagtail.admin.comment_mentions import (
    MAX_MENTION_JSON_BYTES,
    MAX_MENTION_LABEL_UTF16,
    comments_available_for_page_model,
    compare_mentions,
    current_mention_email,
    future_page_mention_candidates,
    normalize_mention_label,
    page_mention_candidates,
    resolve_creatable_page_model,
    resolve_new_mention_users,
    sanitize_stored_mentions,
    search_mention_candidates,
    split_text_by_mentions,
    truncate_utf16,
    utf16_length,
    utf16_slice,
    validate_mention_occurrences,
    validate_retained_mentions,
)
from wagtail.exceptions import PageClassNotFoundError
from wagtail.models import GroupPagePermission, Page
from wagtail.test.testapp.models import BusinessChild, SimplePage, SingletonPage
from wagtail.test.utils import WagtailTestUtils

MENTION_KEY = "29cc6a1f-00ed-41d7-94b1-d46a947962cb"
SECOND_MENTION_KEY = "327547cc-f9ee-4bce-852f-bf96f14179b9"


def valid_user_id():
    if get_user_model()._meta.pk.get_internal_type() == "UUIDField":
        return str(uuid.UUID(int=1))
    return "1"


def mention_occurrence(**overrides):
    occurrence = {
        "key": MENTION_KEY,
        "user_id": valid_user_id(),
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
                "user_id": valid_user_id(),
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

    def test_native_and_string_user_ids_have_the_same_canonical_value(self):
        string_user_id = valid_user_id()
        native_user_id = (
            string_user_id.upper()
            if get_user_model()._meta.pk.get_internal_type() == "UUIDField"
            else int(string_user_id)
        )
        native = validate_mention_occurrences(
            [mention_occurrence(user_id=native_user_id)], text="@Jo"
        )
        string = validate_mention_occurrences(
            [mention_occurrence(user_id=string_user_id)], text="@Jo"
        )

        self.assertEqual(native[0]["user_id"], string[0]["user_id"])
        self.assertIsInstance(native[0]["user_id"], str)

    def test_user_id_rejects_floating_point_values(self):
        for user_id in (1.0, 1.5):
            with self.subTest(user_id=user_id):
                with self.assertRaises(ValidationError):
                    validate_mention_occurrences(
                        [mention_occurrence(user_id=user_id)], text="@Jo"
                    )

    def test_user_id_must_fit_the_configured_primary_key_field(self):
        with self.assertRaises(ValidationError):
            validate_mention_occurrences(
                [mention_occurrence(user_id="1" * 900)], text="@Jo"
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


class TestCommentMentionsField(SimpleTestCase):
    def test_omission_is_distinct_from_an_explicit_empty_list(self):
        from wagtail.admin.forms.comment_mentions import (
            MENTIONS_OMITTED,
            CommentMentionsField,
        )

        field = CommentMentionsField(required=False)
        initial = [mention_occurrence()]

        self.assertIs(
            field.widget.value_from_datadict({}, {}, "mentions"), MENTIONS_OMITTED
        )
        self.assertEqual(field.bound_data(MENTIONS_OMITTED, initial), initial)
        self.assertFalse(field.has_changed(initial, MENTIONS_OMITTED))
        self.assertTrue(field.has_changed(initial, "[]"))

    def test_prepare_value_is_compact_and_preserves_invalid_json(self):
        from wagtail.admin.forms.comment_mentions import CommentMentionsField

        field = CommentMentionsField(required=False)

        self.assertEqual(
            field.prepare_value([mention_occurrence()]),
            json.dumps(
                [mention_occurrence()], ensure_ascii=False, separators=(",", ":")
            ),
        )
        invalid = field.bound_data("{", [])
        self.assertEqual(field.prepare_value(invalid), "{")

    def test_invalid_values_use_one_generic_validation_message(self):
        from wagtail.admin.forms.comment_mentions import CommentMentionsField

        field = CommentMentionsField(required=False)
        oversized = json.dumps(["é" * MAX_MENTION_JSON_BYTES], ensure_ascii=False)
        self.assertGreater(len(oversized.encode("utf-8")), MAX_MENTION_JSON_BYTES)

        for name, value in (
            ("blank", ""),
            ("malformed", "{"),
            ("oversized", oversized),
            ("invalid-utf8", "\ud800"),
        ):
            with self.subTest(name=name):
                with self.assertRaisesMessage(
                    ValidationError, "Enter a valid mention list."
                ):
                    field.clean(value)

    def test_oversize_is_rejected_before_json_parsing(self):
        from wagtail.admin.forms.comment_mentions import CommentMentionsField

        field = CommentMentionsField(required=False)
        oversized = "é" * (MAX_MENTION_JSON_BYTES // 2 + 1)

        with mock.patch("django.forms.fields.json.loads") as loads:
            with self.assertRaisesMessage(
                ValidationError, "Enter a valid mention list."
            ):
                field.to_python(oversized)

        loads.assert_not_called()

    def test_oversize_is_not_parsed_when_redisplaying_bound_data(self):
        from wagtail.admin.forms.comment_mentions import CommentMentionsField

        field = CommentMentionsField(required=False)
        oversized = "é" * (MAX_MENTION_JSON_BYTES // 2 + 1)

        with mock.patch("django.forms.fields.json.loads") as loads:
            bound_value = field.bound_data(oversized, [])

        loads.assert_not_called()
        self.assertEqual(field.prepare_value(bound_value), oversized)

    def test_parser_resource_errors_use_the_generic_validation_message(self):
        from wagtail.admin.forms.comment_mentions import CommentMentionsField

        field = CommentMentionsField(required=False)
        value = f"[{'1' * 5000}]"

        self.assertLess(len(value.encode("utf-8")), MAX_MENTION_JSON_BYTES)
        with self.assertRaisesMessage(ValidationError, "Enter a valid mention list."):
            field.clean(value)

    def test_parser_recursion_errors_use_the_generic_validation_message(self):
        from wagtail.admin.forms.comment_mentions import CommentMentionsField

        field = CommentMentionsField(required=False)

        with mock.patch("django.forms.fields.json.loads", side_effect=RecursionError):
            with self.assertRaisesMessage(
                ValidationError, "Enter a valid mention list."
            ):
                field.clean("[]")

    def test_bound_data_preserves_escaped_surrogates_without_decoding(self):
        from wagtail.admin.forms.comment_mentions import CommentMentionsField

        field = CommentMentionsField(required=False)
        value = '["\\ud800"]'

        prepared = field.prepare_value(field.bound_data(value, []))

        self.assertEqual(prepared, value)
        prepared.encode("utf-8")


class TestMentionLabels(TestCase):
    def test_current_configured_email_is_normalized_for_the_label(self):
        user = self._make_user(email=" jo\t.smith@example.com ")

        self.assertEqual(current_mention_email(user), "jo .smith@example.com")
        self.assertEqual(normalize_mention_label(user), "@jo .smith@example.com")

    def test_blank_email_falls_back_to_display_name_then_username(self):
        user = self._make_user(
            email="", first_name="Jo", last_name="  Smith", username="jsmith"
        )
        cases = [(user, "@Jo Smith")]
        if get_user_model().USERNAME_FIELD != get_user_model().get_email_field_name():
            cases.append((self._make_user(email="", username="jsmith"), "@jsmith"))

        for candidate, expected in cases:
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


class MentionCandidateTestMixin(WagtailTestUtils):
    def setUp(self):
        super().setUp()
        self.root_page = Page.objects.get(pk=2)
        self._group_number = 0

    def create_candidate(
        self,
        username,
        *,
        email=None,
        first_name="",
        last_name="",
        active=True,
        superuser=False,
    ):
        user_model = get_user_model()
        values = {
            user_model.USERNAME_FIELD: (
                email
                if user_model.USERNAME_FIELD == user_model.get_email_field_name()
                and email is not None
                else (
                    f"{username}@example.com"
                    if user_model.USERNAME_FIELD == user_model.get_email_field_name()
                    else username
                )
            ),
            "password": "password",
        }
        field_names = {field.name for field in user_model._meta.fields}
        email_field = user_model.get_email_field_name()
        if email_field in field_names:
            values[email_field] = (
                email if email is not None else f"{username}@example.com"
            )
        if "first_name" in field_names:
            values["first_name"] = first_name
        if "last_name" in field_names:
            values["last_name"] = last_name
        manager_method = (
            user_model._default_manager.create_superuser
            if superuser
            else user_model._default_manager.create_user
        )
        user = manager_method(**values)
        if not active:
            user.is_active = False
            user.save(update_fields=["is_active"])
        return user

    def grant_admin_access(self, user, *, direct=False):
        permission = Permission.objects.get(
            content_type__app_label="wagtailadmin",
            codename="access_admin",
        )
        if direct:
            user.user_permissions.add(permission)
            return
        group = self.create_group("admin")
        group.permissions.add(permission)
        group.user_set.add(user)

    def grant_page_permission(self, user, action, page):
        group = self.create_group(f"{action}-page")
        group.user_set.add(user)
        GroupPagePermission.objects.create(
            group=group,
            page=page,
            permission=Permission.objects.get(
                content_type=ContentType.objects.get_for_model(Page),
                codename=f"{action}_page",
            ),
        )

    def create_group(self, purpose):
        self._group_number += 1
        return Group.objects.create(name=f"mention-{purpose}-{self._group_number}")

    def create_page(self, *, owner=None, slug="mention-candidates"):
        page = SimplePage(
            title="Mention candidates",
            slug=slug,
            content="Candidate permissions",
            owner=owner,
        )
        self.root_page.add_child(instance=page)
        return page

    def make_eligible(self, user, *, page, action="change", direct_admin=False):
        self.grant_admin_access(user, direct=direct_admin)
        self.grant_page_permission(user, action, page)
        return user

    def expected_result(self, user):
        email = current_mention_email(user)
        label = normalize_mention_label(user)
        result = {
            "id": str(user.pk),
            "label": label,
            "email": email,
        }
        username = str(user.get_username())
        if username and username not in {email, label.removeprefix("@")}:
            result["username"] = username
        return result


class TestPageMentionCandidates(MentionCandidateTestMixin, TestCase):
    def test_page_permissions_admin_access_activity_and_superuser_are_filtered(self):
        owner = self.create_candidate("owner", email="owner@example.com")
        page = self.create_page(owner=owner)
        self.grant_admin_access(owner, direct=True)
        self.grant_page_permission(owner, "add", self.root_page)

        direct = self.create_candidate("direct", email="direct@example.com")
        self.make_eligible(direct, page=page, direct_admin=True)
        inherited = self.create_candidate("inherited", email="inherited@example.com")
        self.make_eligible(inherited, page=self.root_page)
        add_non_owner = self.create_candidate(
            "add-non-owner", email="add-non-owner@example.com"
        )
        self.make_eligible(add_non_owner, page=self.root_page, action="add")
        no_admin = self.create_candidate("no-admin", email="no-admin@example.com")
        self.grant_page_permission(no_admin, "change", page)
        inactive = self.create_candidate(
            "inactive", email="inactive@example.com", active=False
        )
        self.make_eligible(inactive, page=page)
        superuser = self.create_candidate(
            "superuser", email="superuser@example.com", superuser=True
        )

        candidate_ids = {str(user.pk) for user in page_mention_candidates(page)}

        self.assertEqual(
            candidate_ids,
            {
                str(owner.pk),
                str(direct.pk),
                str(inherited.pk),
                str(superuser.pk),
            },
        )

    def test_search_filters_before_slice_orders_deterministically_and_is_bounded(self):
        page = self.create_page()
        for index in range(10):
            inactive = self.create_candidate(
                f"needle-{index:02d}-inactive",
                email=f"needle-{index:02d}-inactive@example.com",
                active=False,
            )
            self.make_eligible(inactive, page=page)
        active_users = []
        for index in reversed(range(12)):
            user = self.create_candidate(
                f"needle-{index:02d}-active",
                email=f"needle-{index:02d}-active@example.com",
            )
            self.make_eligible(user, page=page)
            active_users.append(user)

        expected = sorted(
            active_users, key=lambda user: (user.get_username(), user.pk)
        )[:10]
        with self.assertNumQueries(2):
            results = search_mention_candidates(page_mention_candidates(page), "needle")

        self.assertEqual(results, [self.expected_result(user) for user in expected])
        self.assertEqual(len(results), 10)

    def test_empty_and_overlong_queries_do_not_enumerate_candidates(self):
        page = self.create_page()
        candidate = self.create_candidate("candidate", email="candidate@example.com")
        self.make_eligible(candidate, page=page)
        candidates = page_mention_candidates(page)

        with self.assertNumQueries(0):
            self.assertEqual(search_mention_candidates(candidates, ""), [])
            self.assertEqual(search_mention_candidates(candidates, "a" * 65), [])
            self.assertEqual(search_mention_candidates(candidates, "😀" * 33), [])

    def test_new_target_resolution_uses_prepared_identity_and_exact_current_label(self):
        page = self.create_page()
        candidate = self.create_candidate("candidate", email="candidate@example.com")
        self.make_eligible(candidate, page=page)
        pk_field = get_user_model()._meta.pk
        prepared_id = str(pk_field.get_prep_value(candidate.pk))
        valid = mention_occurrence(
            user_id=prepared_id,
            end=len("@candidate@example.com"),
            label="@candidate@example.com",
        )

        resolved = resolve_new_mention_users((valid,), page_mention_candidates(page))

        self.assertEqual(resolved, (candidate,))

        second = self.create_candidate("second", email="second@example.com")
        self.make_eligible(second, page=page)
        same_key_different_target = valid | {
            "user_id": str(second.pk),
            "label": "@second@example.com",
        }
        self.assertEqual(
            resolve_new_mention_users(
                (valid, same_key_different_target), page_mention_candidates(page)
            ),
            (candidate, second),
        )

        invalid_label = valid | {"label": "@forged@example.com"}
        with self.assertRaises(ValidationError):
            resolve_new_mention_users((invalid_label,), page_mention_candidates(page))


class TestFuturePageMentionCandidates(MentionCandidateTestMixin, TestCase):
    def test_change_add_owner_admin_activity_and_superuser_are_filtered(self):
        owner = self.create_candidate("owner", email="owner@example.com")
        parent = self.create_page(owner=owner, slug="future-parent")
        self.grant_admin_access(owner, direct=True)
        self.grant_page_permission(owner, "add", self.root_page)

        changer = self.create_candidate("changer", email="changer@example.com")
        self.make_eligible(changer, page=self.root_page)
        direct_changer = self.create_candidate(
            "direct-changer", email="direct-changer@example.com"
        )
        self.make_eligible(direct_changer, page=parent, direct_admin=True)
        add_non_owner = self.create_candidate(
            "add-non-owner", email="add-non-owner@example.com"
        )
        self.make_eligible(add_non_owner, page=self.root_page, action="add")
        no_admin = self.create_candidate("no-admin", email="no-admin@example.com")
        self.grant_page_permission(no_admin, "change", parent)
        inactive = self.create_candidate(
            "inactive", email="inactive@example.com", active=False
        )
        self.make_eligible(inactive, page=parent)
        superuser = self.create_candidate(
            "superuser", email="superuser@example.com", superuser=True
        )

        candidate_ids = {
            str(user.pk)
            for user in future_page_mention_candidates(
                parent_page=parent,
                owner=owner,
            )
        }

        self.assertEqual(
            candidate_ids,
            {
                str(owner.pk),
                str(changer.pk),
                str(direct_changer.pk),
                str(superuser.pk),
            },
        )


class TestPageMentionSuggestionView(MentionCandidateTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.requester = self.create_candidate(
            "requester", email="requester@example.com", superuser=True
        )
        self.page = self.create_page(owner=self.requester)
        self.editor = self.create_candidate("jane", email="jane@example.com")
        self.make_eligible(self.editor, page=self.page)
        self.client.force_login(self.requester)
        self.url = reverse(
            "wagtailadmin_pages:comment_mention_suggestions",
            args=[self.page.pk],
        )

    def test_response_has_exact_minimal_wire_shape(self):
        response = self.client.get(self.url, {"q": "jane"})

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {"results": [self.expected_result(self.editor)]},
        )
        result = response.json()["results"][0]
        self.assertIsInstance(result["id"], str)
        self.assertNotIn("url", result)
        self.assertNotIn("notification_preferences", result)
        self.assertNotIn("permissions", result)

    def test_available_name_fields_and_fallback_labels_are_searchable(self):
        fallback = self.create_candidate(
            "fallback",
            email="",
            first_name="Blank",
            last_name="Candidate",
        )
        self.make_eligible(fallback, page=self.page)

        response = self.client.get(self.url, {"q": "Blank"})

        self.assertJSONEqual(
            response.content,
            {"results": [self.expected_result(fallback)]},
        )
        self.assertEqual(response.json()["results"][0]["email"], "")
        self.assertEqual(response.json()["results"][0]["label"], "@Blank Candidate")

    def test_username_fallback_is_not_repeated_as_a_secondary_value(self):
        if get_user_model().USERNAME_FIELD == get_user_model().get_email_field_name():
            self.skipTest("Configured username is the required email field")
        fallback = self.create_candidate("only-username", email="")
        self.make_eligible(fallback, page=self.page)

        response = self.client.get(self.url, {"q": "only-username"})

        self.assertJSONEqual(
            response.content,
            {
                "results": [
                    {
                        "id": str(fallback.pk),
                        "label": "@only-username",
                        "email": "",
                    }
                ]
            },
        )

    def test_overlong_label_is_truncated_within_the_wire_limit(self):
        long_email = f"{'a' * 64}@{'b' * 63}.{'c' * 63}.{'d' * 62}"
        self.assertEqual(len(long_email), 255)
        candidate = self.create_candidate("long-label", email=long_email)
        self.make_eligible(candidate, page=self.page)

        response = self.client.get(self.url, {"q": "aaaa"})

        result = response.json()["results"][0]
        self.assertEqual(utf16_length(result["label"]), MAX_MENTION_LABEL_UTF16)
        self.assertTrue(result["label"].endswith("…"))
        self.assertEqual(result["email"], long_email)

    def test_empty_and_overlong_queries_return_no_results(self):
        self.assertJSONEqual(self.client.get(self.url).content, {"results": []})
        self.assertJSONEqual(
            self.client.get(self.url, {"q": "a" * 65}).content,
            {"results": []},
        )

    @override_settings(WAGTAILADMIN_COMMENTS_ENABLED=False)
    def test_comments_disabled_returns_not_found(self):
        self.assertEqual(self.client.get(self.url, {"q": "jane"}).status_code, 404)

    def test_page_model_without_comment_formset_returns_not_found(self):
        original_settings_panels = SimplePage.settings_panels
        SimplePage.settings_panels = []
        SimplePage.get_edit_handler.cache_clear()
        try:
            response = self.client.get(self.url, {"q": "jane"})
        finally:
            SimplePage.settings_panels = original_settings_panels
            SimplePage.get_edit_handler.cache_clear()

        self.assertEqual(response.status_code, 404)

    def test_requester_without_page_edit_permission_is_forbidden(self):
        requester = self.create_candidate(
            "unauthorized", email="unauthorized@example.com"
        )
        self.grant_admin_access(requester)
        self.client.force_login(requester)

        self.assertEqual(
            self.client.get(
                self.url,
                {"q": "jane"},
                headers={"x-requested-with": "XMLHttpRequest"},
            ).status_code,
            403,
        )

    @mock.patch("wagtail.models.ContentType.model_class", return_value=None)
    def test_stale_page_content_type_raises_page_class_not_found(self, model_class):
        with self.assertRaises(PageClassNotFoundError):
            self.client.get(self.url, {"q": "jane"})


class TestCreateMentionSuggestionView(MentionCandidateTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.requester = self.create_candidate("owner", email="owner@example.com")
        self.make_eligible(self.requester, page=self.root_page, action="add")
        self.editor = self.create_candidate("jane", email="jane@example.com")
        self.make_eligible(self.editor, page=self.root_page)
        self.client.force_login(self.requester)
        self.url = reverse(
            "wagtailadmin_pages:create_comment_mention_suggestions",
            args=["tests", "simplepage", self.root_page.pk],
        )

    def test_response_has_exact_minimal_wire_shape(self):
        response = self.client.get(self.url, {"q": "jane"})

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {"results": [self.expected_result(self.editor)]},
        )

    def test_requester_without_parent_add_permission_is_forbidden(self):
        requester = self.create_candidate(
            "unauthorized", email="unauthorized@example.com"
        )
        self.grant_admin_access(requester)
        self.client.force_login(requester)

        self.assertEqual(
            self.client.get(
                self.url,
                {"q": "jane"},
                headers={"x-requested-with": "XMLHttpRequest"},
            ).status_code,
            403,
        )

    def test_invalid_parent_content_type_and_page_model_are_rejected(self):
        ContentType.objects.create(app_label="stale", model="missingpage")
        cases = (
            (
                "missing-parent",
                reverse(
                    "wagtailadmin_pages:create_comment_mention_suggestions",
                    args=["tests", "simplepage", 999999],
                ),
                404,
            ),
            (
                "missing-type",
                reverse(
                    "wagtailadmin_pages:create_comment_mention_suggestions",
                    args=["tests", "missingpage", self.root_page.pk],
                ),
                404,
            ),
            (
                "non-page-model",
                reverse(
                    "wagtailadmin_pages:create_comment_mention_suggestions",
                    args=["auth", "group", self.root_page.pk],
                ),
                404,
            ),
            (
                "stale-content-type",
                reverse(
                    "wagtailadmin_pages:create_comment_mention_suggestions",
                    args=["stale", "missingpage", self.root_page.pk],
                ),
                404,
            ),
            (
                "disallowed-page-model",
                reverse(
                    "wagtailadmin_pages:create_comment_mention_suggestions",
                    args=[
                        BusinessChild._meta.app_label,
                        BusinessChild._meta.model_name,
                        self.root_page.pk,
                    ],
                ),
                403,
            ),
        )

        for name, url, status_code in cases:
            with self.subTest(name=name):
                request_kwargs = (
                    {"headers": {"x-requested-with": "XMLHttpRequest"}}
                    if status_code == 403
                    else {}
                )
                self.assertEqual(
                    self.client.get(url, {"q": "jane"}, **request_kwargs).status_code,
                    status_code,
                )

    def test_route_selects_the_custom_viewset_for_the_child_page_model(self):
        url = reverse(
            "wagtailadmin_pages:create_comment_mention_suggestions",
            args=["tests", "eventpage", self.root_page.pk],
        )

        response = self.client.get(url, {"q": "jane"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Wagtail-ViewSet"], "EventPageViewSet")

    def test_model_can_create_at_gate_is_enforced(self):
        existing = SingletonPage(title="Only singleton", slug="only-singleton")
        self.root_page.add_child(instance=existing)
        url = reverse(
            "wagtailadmin_pages:create_comment_mention_suggestions",
            args=[
                SingletonPage._meta.app_label,
                SingletonPage._meta.model_name,
                self.root_page.pk,
            ],
        )

        self.assertEqual(
            self.client.get(
                url,
                {"q": "jane"},
                headers={"x-requested-with": "XMLHttpRequest"},
            ).status_code,
            403,
        )

    @override_settings(WAGTAILADMIN_COMMENTS_ENABLED=False)
    def test_comments_disabled_returns_not_found(self):
        self.assertEqual(self.client.get(self.url, {"q": "jane"}).status_code, 404)

    def test_page_model_without_comment_formset_returns_not_found(self):
        original_settings_panels = SimplePage.settings_panels
        SimplePage.settings_panels = []
        SimplePage.get_edit_handler.cache_clear()
        try:
            response = self.client.get(self.url, {"q": "jane"})
        finally:
            SimplePage.settings_panels = original_settings_panels
            SimplePage.get_edit_handler.cache_clear()

        self.assertEqual(response.status_code, 404)

    def test_public_model_resolver_returns_only_the_authorized_page_model(self):
        request = mock.Mock(user=self.requester)

        page_model = resolve_creatable_page_model(
            request=request,
            parent_page=self.root_page,
            app_label="tests",
            model_name="simplepage",
        )

        self.assertIsInstance(page_model, ModelBase)
        self.assertIs(page_model, SimplePage)


class TestCommentAvailability(SimpleTestCase):
    @override_settings(WAGTAILADMIN_COMMENTS_ENABLED=False)
    def test_setting_disables_comments_before_edit_handler_lookup(self):
        with mock.patch.object(SimplePage, "get_edit_handler") as get_edit_handler:
            self.assertFalse(comments_available_for_page_model(SimplePage))

        get_edit_handler.assert_not_called()
