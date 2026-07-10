import datetime
import json
import os
import re
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.core import mail
from django.core.files.base import ContentFile
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.test import TestCase, modify_settings, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from wagtail.admin.action_menu import ActionMenuItem, PublishMenuItem
from wagtail.admin.admin_url_finder import AdminURLFinder
from wagtail.admin.comment_notifications import (
    schedule_comment_notifications as real_schedule_comment_notifications,
)
from wagtail.admin.models import EditingSession
from wagtail.exceptions import PageClassNotFoundError
from wagtail.models import (
    Comment,
    CommentMention,
    CommentReply,
    CommentReplyMention,
    GroupPagePermission,
    Locale,
    Page,
    PageLogEntry,
    PageSubscription,
    Revision,
    Site,
    get_default_page_content_type,
)
from wagtail.signals import page_published
from wagtail.test.testapp.models import (
    EVENT_AUDIENCE_CHOICES,
    Advert,
    AdvertPlacement,
    CommentableJSONPage,
    CustomPermissionPage,
    EventCategory,
    EventPage,
    EventPageCarouselItem,
    FilePage,
    ManyToManyBlogPage,
    PageChooserModel,
    SimplePage,
    SingleEventPage,
    StandardIndex,
    StreamPage,
    TaggedPage,
)
from wagtail.test.utils import WagtailTestUtils
from wagtail.test.utils.form_data import inline_formset, nested_form_data, streamfield
from wagtail.test.utils.timestamps import submittable_timestamp
from wagtail.users.models import UserProfile
from wagtail.utils.timestamps import render_timestamp


class TestPageEdit(WagtailTestUtils, TestCase):
    STATUS_TOGGLE_BADGE_REGEX = (
        r'data-side-panel-toggle="status"[^<]+<svg[^<]+<use[^<]+</use[^<]+</svg[^<]+'
        r"<div data-side-panel-toggle-counter[^>]+w-bg-critical-200[^>]+>\s*%(num_errors)s\s*</div>"
    )

    def setUp(self):
        # Find root page
        self.root_page = Page.objects.get(id=2)

        # Add child page
        child_page = SimplePage(
            title="Hello world!",
            slug="hello-world",
            content="hello",
        )
        self.root_page.add_child(instance=child_page)
        child_page.save_revision().publish()
        self.child_page = SimplePage.objects.get(id=child_page.id)

        # Add file page
        fake_file = ContentFile("File for testing multipart")
        fake_file.name = "test.txt"
        file_page = FilePage(
            title="File Page",
            slug="file-page",
            file_field=fake_file,
        )
        self.root_page.add_child(instance=file_page)
        file_page.save_revision().publish()
        self.file_page = FilePage.objects.get(id=file_page.id)

        # Add event page (to test edit handlers)
        self.event_page = EventPage(
            title="Event page",
            slug="event-page",
            location="the moon",
            audience="public",
            cost="free",
            date_from="2001-01-01",
        )
        self.root_page.add_child(instance=self.event_page)

        # Add single event page (to test custom URL routes)
        self.single_event_page = SingleEventPage(
            title="Mars landing",
            slug="mars-landing",
            location="mars",
            audience="public",
            cost="free",
            date_from="2001-01-01",
        )
        self.root_page.add_child(instance=self.single_event_page)

        self.unpublished_page = SimplePage(
            title="Hello unpublished world!",
            slug="hello-unpublished-world",
            content="hello",
            live=False,
            has_unpublished_changes=True,
        )
        self.root_page.add_child(instance=self.unpublished_page)

        # Login
        self.user = self.login()

    def get_publish_button_label(self, response):
        soup = self.get_soup(response.content)
        publish_button = soup.select_one('.w-dropdown-button > [name="action-publish"]')
        if publish_button is None:
            publish_button = soup.select_one('[name="action-publish"]')
        self.assertIsNotNone(publish_button)
        label = publish_button.select_one('[data-w-progress-target="label"]')
        self.assertIsNotNone(label)
        return label.get_text(strip=True)

    def schedule_child_page(self, go_live_at):
        edit_url = reverse("wagtailadmin_pages:edit", args=(self.child_page.id,))
        post_data = {
            "title": self.child_page.title,
            "content": self.child_page.content,
            "slug": self.child_page.slug,
            "go_live_at": submittable_timestamp(go_live_at),
        }
        self.client.post(edit_url, post_data, follow=True)
        self.child_page.refresh_from_db(fields=["go_live_at"])
        return edit_url

    def assertSchedulingDialogRendered(self, response, edit_url):
        # Should show the "Edit schedule" button
        html = response.content.decode()
        self.assertTagInHTML(
            '<button type="button" data-a11y-dialog-show="schedule-publishing-dialog">Edit schedule</button>',
            html,
            count=1,
            allow_extra_attrs=True,
        )
        # Should show the dialog template pointing to the [data-edit-form] selector as the root
        soup = self.get_soup(html)
        dialog = soup.select_one(
            """
            template[data-controller="w-teleport"][data-w-teleport-target-value="[data-edit-form]"]
            #schedule-publishing-dialog
            """
        )
        self.assertIsNotNone(dialog)
        # Should render the main form with data-edit-form attribute
        self.assertTagInHTML(
            f'<form action="{edit_url}" method="POST" data-edit-form>',
            html,
            count=1,
            allow_extra_attrs=True,
        )
        self.assertTagInHTML(
            '<div id="schedule-publishing-dialog" class="w-dialog w-dialog--message publishing" data-controller="w-dialog">',
            html,
            count=1,
            allow_extra_attrs=True,
        )

    def test_page_edit(self):
        # Tests that the edit page loads
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.event_page.id,))
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/html; charset=utf-8")
        self.assertContains(response, 'id="status-sidebar-live"')

        # Test help text defined on FieldPanel
        self.assertContains(response, "Who this event is for")

        # Test InlinePanel labels/headings/help text
        self.assertContains(
            response,
            '<label class="w-field__label" for="id_speakers-__prefix__-last_name" id="id_speakers-__prefix__-last_name-label">',
        )
        self.assertContains(response, "Add speaker")
        self.assertContains(response, "Put the keynote speaker first")

        # Test MultiFieldPanel help text
        self.assertContains(response, "For SEO nerds only")

        # test register_page_action_menu_item hook
        self.assertContains(
            response,
            '<button type="submit" name="action-panic" value="Panic!" class="button">Panic!</button>',
        )
        self.assertContains(response, "testapp/js/siren.js")

        # test construct_page_action_menu hook
        self.assertContains(
            response,
            '<button type="submit" name="action-relax" value="Relax." class="button">Relax.</button>',
        )

        # test that workflow actions are shown
        self.assertContains(
            response,
            '<button type="submit" name="action-submit" value="Submit to Moderators approval" class="button">',
        )

        # test that side panel is shown
        self.assertContains(
            response,
            '<aside class="form-side form-side--initial" aria-label="Side panels" data-form-side>',
        )
        self.assertNotContains(response, "data-form-side-explorer")

        # test that usage info is shown
        self.assertContains(response, "Referenced 0 times")
        self.assertContains(
            response, reverse("wagtailadmin_pages:usage", args=(self.event_page.id,))
        )

        # test that the link to the history view is shown,
        # one in the header dropdown button, one beside the side panel toggles,
        # one in the status side panel
        self.assertContains(
            response,
            reverse("wagtailadmin_pages:history", args=(self.event_page.id,)),
            count=3,
        )

        # test that AdminURLFinder returns the edit view for the page
        url_finder = AdminURLFinder(self.user)
        expected_url = "/admin/pages/%d/edit/" % self.event_page.id
        self.assertEqual(url_finder.get_edit_url(self.event_page), expected_url)

        # Autosave defaults to enabled with 500ms interval
        soup = self.get_soup(response.content)
        form = soup.select_one("form[data-edit-form]")
        self.assertIsNotNone(form)
        self.assertIn("w-autosave", form["data-controller"].split())
        self.assertTrue(
            {
                "w-unsaved:add->w-autosave#save:prevent",
                "w-autosave:success->w-unsaved#clear",
            }.issubset(form["data-action"].split())
        )
        self.assertEqual(form.attrs.get("data-w-autosave-interval-value"), "500")

    def test_loaded_revision_id_and_timestamp_included_in_form(self):
        # Ensure there's a revision for the page
        self.event_page.title = "Updated event page"
        revision = self.event_page.save_revision()
        self.assertEqual(self.event_page.revisions.count(), 1)

        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.event_page.id,)),
        )
        self.assertEqual(response.status_code, 200)
        soup = self.get_soup(response.content)
        form = soup.select_one("form[data-edit-form]")
        self.assertIsNotNone(form)
        loaded_revision = form.select_one("input[name='loaded_revision_id']")
        self.assertIsNotNone(loaded_revision)
        self.assertEqual(int(loaded_revision["value"]), revision.pk)
        loaded_timestamp = form.select_one("input[name='loaded_revision_created_at']")
        self.assertIsNotNone(loaded_timestamp)
        self.assertEqual(loaded_timestamp["value"], revision.created_at.isoformat())

    @override_settings(WAGTAIL_AUTOSAVE_INTERVAL=0)
    def test_autosave_disabled(self):
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.event_page.id,))
        )
        self.assertEqual(response.status_code, 200)
        soup = self.get_soup(response.content)
        form = soup.select_one("form[data-edit-form]")
        self.assertIsNotNone(form)
        self.assertNotIn("w-autosave", form["data-controller"].split())
        self.assertNotIn("w-autosave", form["data-action"])
        self.assertIsNone(form.attrs.get("data-w-autosave-interval-value"))

    @override_settings(WAGTAIL_AUTOSAVE_INTERVAL=2000)
    def test_autosave_custom_interval(self):
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.event_page.id,))
        )
        self.assertEqual(response.status_code, 200)
        soup = self.get_soup(response.content)
        form = soup.select_one("form[data-edit-form]")
        self.assertIsNotNone(form)
        self.assertIn("w-autosave", form["data-controller"].split())
        self.assertTrue(
            {
                "w-unsaved:add->w-autosave#save:prevent",
                "w-autosave:success->w-unsaved#clear",
            }.issubset(form["data-action"].split())
        )
        self.assertEqual(form.attrs.get("data-w-autosave-interval-value"), "2000")

    def test_publish_button_shows_schedule_label_for_future_go_live(self):
        go_live_at = timezone.now() + datetime.timedelta(hours=1)

        response = self.client.get(self.schedule_child_page(go_live_at))
        self.assertEqual(response.status_code, 200)

        publish_menu_item = next(
            item
            for item in response.context["action_menu"].menu_items
            if getattr(item, "name", "") == "action-publish"
        )
        publish_context = publish_menu_item.get_context_data(
            response.context["action_menu"].context
        )

        self.assertTrue(publish_context["is_scheduled"])
        self.assertEqual(self.get_publish_button_label(response), "Schedule to publish")

    def test_publish_button_shows_publish_label_for_past_schedule(self):
        go_live_at = timezone.now() - datetime.timedelta(hours=1)

        response = self.client.get(self.schedule_child_page(go_live_at))
        self.assertEqual(response.status_code, 200)

        publish_menu_item = next(
            item
            for item in response.context["action_menu"].menu_items
            if getattr(item, "name", "") == "action-publish"
        )
        publish_context = publish_menu_item.get_context_data(
            response.context["action_menu"].context
        )

        self.assertFalse(publish_context["is_scheduled"])
        self.assertEqual(self.get_publish_button_label(response), "Publish")

    def test_construct_page_action_menu_hook_with_custom_default_button(self):
        class CustomDefaultItem(ActionMenuItem):
            label = "Custom button"
            name = "custom-default"
            classname = "custom-class"
            icon_name = "check"

            class Media:
                js = ["js/custom-default.js"]
                css = {"all": ["css/custom-default.css"]}

        def add_custom_default_item(menu_items, request, context):
            menu_items.insert(0, CustomDefaultItem())

        with self.register_hook(
            "construct_page_action_menu",
            add_custom_default_item,
        ):
            response = self.client.get(
                reverse("wagtailadmin_pages:edit", args=(self.event_page.id,))
            )

        self.assertEqual(response.status_code, 200)

        soup = self.get_soup(response.content)
        form = soup.select_one("form[data-edit-form]")
        custom_action = form.select_one("button[name='custom-default']")
        self.assertIsNotNone(custom_action)

        # We're replacing the save button, so it should not be in a dropdown
        # as it's the main action
        dropdown_parent = custom_action.find_parent(attrs={"class": "w-dropdown"})
        self.assertIsNone(dropdown_parent)

        self.assertEqual(custom_action.text.strip(), "Custom button")
        self.assertEqual(custom_action.attrs.get("class"), ["button", "custom-class"])
        icon = custom_action.select_one("svg use[href='#icon-check']")
        self.assertIsNotNone(icon)

        # Should contain media files
        js = soup.select_one("script[src='/static/js/custom-default.js']")
        self.assertIsNotNone(js)
        css = soup.select_one("link[href='/static/css/custom-default.css']")
        self.assertIsNotNone(css)

        # The save button should now be in the dropdown
        save_item = form.select_one(".w-dropdown .action-save")
        self.assertIsNotNone(save_item)

    def test_construct_page_action_menu_hook_removes_all_buttons(self):
        def remove_all_buttons(menu_items, request, context):
            menu_items[:] = []

        with self.register_hook(
            "construct_page_action_menu",
            remove_all_buttons,
        ):
            response = self.client.get(
                reverse("wagtailadmin_pages:edit", args=(self.event_page.id,))
            )

        # It shouldn't crash due to assuming a default button is present
        self.assertEqual(response.status_code, 200)

        soup = self.get_soup(response.content)
        form = soup.select_one("form[data-edit-form]")
        actions = form.select("footer button")
        self.assertEqual(len(actions), 0)

    def test_usage_count_information_shown(self):
        with self.captureOnCommitCallbacks(execute=True):
            PageChooserModel.objects.create(page=self.event_page)

        # Tests that the edit page loads
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.event_page.id,))
        )

        # test that usage info is shown
        self.assertContains(response, "Referenced 1 time")
        self.assertContains(
            response, reverse("wagtailadmin_pages:usage", args=(self.event_page.id,))
        )

    def test_edit_custom_permissions(self):
        page = CustomPermissionPage(title="Page with custom perms", slug="custom-perms")
        self.root_page.add_child(instance=page)
        response = self.client.get(reverse("wagtailadmin_pages:edit", args=(page.id,)))
        self.assertEqual(response.status_code, 200)
        # Respecting PagePermissionTester.can_view_revisions(),
        # should not contain a link to the history view
        self.assertNotContains(
            response,
            reverse("wagtailadmin_pages:history", args=(page.id,)),
        )

    @override_settings(WAGTAIL_WORKFLOW_ENABLED=False)
    def test_workflow_buttons_not_shown_when_workflow_disabled(self):
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.event_page.id,))
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'value="Submit to Moderators approval"')

    def test_edit_draft_page_with_no_revisions(self):
        # Tests that the edit page loads
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.unpublished_page.id,))
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="status-sidebar-draft"')

    def test_edit_multipart(self):
        """
        Test checks if 'enctype="multipart/form-data"' is added and only to forms that require multipart encoding.
        """
        # check for SimplePage where is no file field
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.event_page.id,))
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'enctype="multipart/form-data"')
        self.assertTemplateUsed(response, "wagtailadmin/pages/edit.html")

        # check for FilePage which has file field
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.file_page.id,))
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'enctype="multipart/form-data"')

    @mock.patch("wagtail.models.ContentType.model_class", return_value=None)
    def test_edit_when_specific_class_cannot_be_found(self, mocked_method):
        with self.assertRaises(PageClassNotFoundError):
            self.client.get(
                reverse("wagtailadmin_pages:edit", args=(self.event_page.id,))
            )

    def test_upload_file_publish(self):
        """
        Check that file uploads work when directly publishing
        """
        file_upload = ContentFile(b"A new file", name="published-file.txt")
        post_data = {
            "title": "New file",
            "slug": "new-file",
            "file_field": file_upload,
            "action-publish": "Publish",
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=[self.file_page.id]), post_data
        )

        # Should be redirected to explorer
        self.assertRedirects(
            response, reverse("wagtailadmin_explore", args=[self.root_page.id])
        )

        # Check the new file exists
        file_page = FilePage.objects.get()

        self.assertEqual(file_page.file_field.name, file_upload.name)
        self.assertTrue(os.path.exists(file_page.file_field.path))
        self.assertEqual(file_page.file_field.read(), b"A new file")

    def test_upload_file_draft(self):
        """
        Check that file uploads work when saving a draft
        """
        file_upload = ContentFile(b"A new file", name="draft-file.txt")
        post_data = {
            "title": "New file",
            "slug": "new-file",
            "file_field": file_upload,
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=[self.file_page.id]), post_data
        )

        # Should be redirected to edit page
        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=[self.file_page.id])
        )

        # Check the file was uploaded
        file_path = os.path.join(settings.MEDIA_ROOT, file_upload.name)
        self.assertTrue(os.path.exists(file_path))
        with open(file_path, "rb") as saved_file:
            self.assertEqual(saved_file.read(), b"A new file")

        # Publish the draft just created
        FilePage.objects.get().get_latest_revision().publish()

        # Get the file page, check the file is set
        file_page = FilePage.objects.get()
        self.assertEqual(file_page.file_field.name, file_upload.name)
        self.assertTrue(os.path.exists(file_page.file_field.path))
        self.assertEqual(file_page.file_field.read(), b"A new file")

    def test_page_edit_bad_permissions(self):
        # Remove privileges from user
        self.user.is_superuser = False
        self.user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="wagtailadmin", codename="access_admin"
            )
        )
        self.user.save()

        # Get edit page
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,))
        )

        # Check that the user received a 302 redirected response
        self.assertEqual(response.status_code, 302)

        url_finder = AdminURLFinder(self.user)
        self.assertIsNone(url_finder.get_edit_url(self.event_page))

    def test_page_edit_post(self):
        # Tests simple editing
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)), post_data
        )

        # Should be redirected to edit page
        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=(self.child_page.id,))
        )

        # The page should have "has_unpublished_changes" flag set
        child_page_new = SimplePage.objects.get(id=self.child_page.id)
        self.assertTrue(child_page_new.has_unpublished_changes)

        # Page fields should not be changed (because we just created a new draft)
        self.assertEqual(child_page_new.title, self.child_page.title)
        self.assertEqual(child_page_new.content, self.child_page.content)
        self.assertEqual(child_page_new.slug, self.child_page.slug)

        # The draft_title should have a new title
        self.assertEqual(child_page_new.draft_title, post_data["title"])

    def test_page_edit_post_with_json_response(self):
        self.assertEqual(self.child_page.revisions.count(), 1)
        loaded_revision = self.child_page.get_latest_revision()
        # Tests simple editing
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "loaded_revision_id": loaded_revision.pk,
            "loaded_revision_created_at": loaded_revision.created_at.isoformat(),
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)),
            post_data,
            headers={"Accept": "application/json"},
        )

        # Should be a 200 OK JSON response
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        response_json = response.json()
        self.assertEqual(response_json["success"], True)
        self.assertEqual(response_json["pk"], self.child_page.pk)
        self.assertEqual(response_json["field_updates"], {})

        # Should create a new revision to be overwritten later
        self.assertEqual(self.child_page.revisions.count(), 2)
        self.assertNotEqual(response_json["revision_id"], loaded_revision.pk)
        revision = self.child_page.revisions.get(pk=response_json["revision_id"])
        self.assertEqual(
            response_json["revision_created_at"],
            revision.created_at.isoformat(),
        )
        self.assertEqual(revision.content["title"], "I've been edited!")
        self.assertEqual(
            response_json["comments"],
            {
                "comments": [],
                "user": str(self.user.pk),
                "authors": {},
                "mentioned_users": {},
            },
        )

        soup = self.get_soup(response_json["html"])

        # Should reload only the status side panel
        side_panels = soup.select(
            "template[data-controller='w-teleport']"
            "[data-w-teleport-target-value^='[data-side-panel=']"
            "[data-w-teleport-mode-value='innerHTML']"
        )
        self.assertEqual(len(side_panels), 1)
        status_side_panel = side_panels[0]
        self.assertEqual(
            status_side_panel["data-w-teleport-target-value"],
            "[data-side-panel='status']",
        )

        # These dialogs will be teleported to the body, so don't rerender them
        # as we would end up with multiple instances of each
        workflow_status_dialog = soup.find("div", id="workflow-status-dialog")
        self.assertIsNone(workflow_status_dialog)
        set_privacy_dialog = soup.find("div", id="set-privacy")
        self.assertIsNone(set_privacy_dialog)

        breadcrumbs = soup.find(
            "template",
            {
                "data-controller": "w-teleport",
                "data-w-teleport-target-value": "header [data-w-breadcrumbs]",
                "data-w-teleport-mode-value": "outerHTML",
            },
        )
        self.assertIsNotNone(breadcrumbs)
        # Should not include header buttons as they're already rendered
        self.assertIsNone(breadcrumbs.select_one("nav#w-slim-header-buttons"))

        # History link should not be included as it's already present on the page
        history_link = soup.find(
            "template",
            {
                "data-controller": "w-teleport",
                "data-w-teleport-target-value": "[data-side-panel-toggle]:last-of-type",
                "data-w-teleport-mode-value": "afterend",
            },
        )
        self.assertIsNone(history_link)

        form_title_heading = soup.find(
            "template",
            {
                "data-controller": "w-teleport",
                "data-w-teleport-target-value": "#header-title span",
                "data-w-teleport-mode-value": "textContent",
            },
        )
        self.assertIsNone(form_title_heading)
        header_title = soup.find(
            "template",
            {
                "data-controller": "w-teleport",
                "data-w-teleport-target-value": "head title",
                "data-w-teleport-mode-value": "textContent",
            },
        )
        self.assertIsNotNone(header_title)
        self.assertEqual(
            header_title.text.strip(),
            # Looks a bit off because get_admin_display_title for SimplePage
            # adds (simple page) suffix
            "Editing Simple page: I've been edited! (simple page)",
        )

        # No form updates as we already have the loaded revision id and timestamp
        form_adds = soup.find(
            "template",
            {
                "data-controller": "w-teleport",
                "data-w-teleport-target-value": "form[data-edit-form]",
                "data-w-teleport-mode-value": "afterbegin",
            },
        )
        self.assertIsNone(form_adds)

        # Should not load the editing sessions module as it's already rendered
        editing_sessions = soup.find(
            "template",
            {
                "data-controller": "w-teleport",
                "data-w-teleport-target-value": "#w-autosave-indicator",
                "data-w-teleport-mode-value": "afterend",
            },
        )
        self.assertIsNone(editing_sessions)

        # The page should have "has_unpublished_changes" flag set
        child_page_new = SimplePage.objects.get(id=self.child_page.id)
        self.assertTrue(child_page_new.has_unpublished_changes)

        # Page fields should not be changed (because we just created a new draft)
        self.assertEqual(child_page_new.title, self.child_page.title)
        self.assertEqual(child_page_new.content, self.child_page.content)
        self.assertEqual(child_page_new.slug, self.child_page.slug)

        # The draft_title should have a new title
        self.assertEqual(child_page_new.draft_title, post_data["title"])

    def test_save_outdated_revision_with_json_response(self):
        self.assertEqual(self.child_page.revisions.count(), 1)
        loaded_revision = self.child_page.get_latest_revision()
        self.child_page.title = "Someone else edited after the page is loaded"
        other_revision = self.child_page.save_revision(user=self.user)
        self.assertEqual(self.child_page.revisions.count(), 2)

        post_data = {
            "title": "Just another edit submitted after the other edit is done",
            "content": "Some content",
            "slug": "hello-world",
            "loaded_revision_id": loaded_revision.pk,
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)),
            post_data,
            headers={"Accept": "application/json"},
        )

        # Instead of creating a new revision for autosave (which means the user
        # would unknowingly replace a newer revision), we return an error
        # response that should be a 400 response
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "error_code": "invalid_revision",
                "error_message": "Saving will overwrite a newer version.",
            },
        )

        # Page fields should still be from the published version
        self.child_page.refresh_from_db()
        self.assertEqual(self.child_page.title, "Hello world!")

        # The initially loaded revision, and the actual latest revision,
        # should both be unchanged
        self.assertEqual(self.child_page.revisions.count(), 2)
        loaded_revision.refresh_from_db()
        self.assertEqual(loaded_revision.content["title"], "Hello world!")
        other_revision.refresh_from_db()
        self.assertEqual(
            other_revision.content["title"],
            "Someone else edited after the page is loaded",
        )
        self.assertEqual(self.child_page.get_latest_revision().id, other_revision.id)

    def test_save_outdated_revision_timestamp_with_json_response(self):
        self.assertEqual(self.child_page.revisions.count(), 1)
        loaded_revision = self.child_page.get_latest_revision()
        loaded_revision_created_at = loaded_revision.created_at.isoformat()
        # Simulate the loaded revision being updated via another session's autosave,
        # which means the revision is overwritten with new content and created_at
        self.child_page.title = "Someone else edited after the page is loaded"
        self.child_page.save_revision(overwrite_revision=loaded_revision)
        self.assertEqual(self.child_page.revisions.count(), 1)

        post_data = {
            "title": "Just another edit submitted after the other edit is done",
            "content": "Some content",
            "slug": "hello-world",
            "loaded_revision_id": loaded_revision.pk,
            "loaded_revision_created_at": loaded_revision_created_at,
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)),
            post_data,
            headers={"Accept": "application/json"},
        )

        # Instead of creating a new revision for autosave (which means the user
        # would unknowingly replace the updated revision), we return an error
        # response that should be a 400 response
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "error_code": "invalid_revision",
                "error_message": "Saving will overwrite a newer version.",
            },
        )

        # Page fields should still be from the published version
        self.child_page.refresh_from_db()
        self.assertEqual(self.child_page.title, "Hello world!")

        # The initially loaded revision should prefer the other session's autosave
        self.assertEqual(self.child_page.revisions.count(), 1)
        loaded_revision.refresh_from_db()
        self.assertEqual(
            loaded_revision.content["title"],
            "Someone else edited after the page is loaded",
        )
        self.assertEqual(self.child_page.get_latest_revision().id, loaded_revision.id)

    def test_page_edit_post_with_overwrite_revision_and_json_response(self):
        self.assertEqual(self.child_page.revisions.count(), 1)
        loaded_revision = self.child_page.get_latest_revision()
        self.child_page.title = "A changed title"
        revision = self.child_page.save_revision(user=self.user)
        self.assertEqual(self.child_page.revisions.count(), 2)

        post_data = {
            "title": "I've been edited again!",
            "content": "Some content",
            "slug": "hello-world",
            # The page was originally loaded with loaded_revision, but
            # a successful autosave created a new revision which we now
            # want to overwrite with a new autosave request
            "loaded_revision_id": loaded_revision.pk,
            "overwrite_revision_id": revision.id,
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)),
            post_data,
            headers={"Accept": "application/json"},
        )

        # Should be a 200 OK JSON response
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        revision.refresh_from_db()
        response_json = response.json()
        self.assertEqual(response_json["success"], True)
        self.assertEqual(response_json["pk"], self.child_page.pk)
        self.assertEqual(response_json["revision_id"], revision.pk)
        self.assertEqual(
            response_json["revision_created_at"],
            revision.created_at.isoformat(),
        )

        # The page should have "has_unpublished_changes" flag set
        child_page_new = SimplePage.objects.get(id=self.child_page.id)
        self.assertTrue(child_page_new.has_unpublished_changes)

        # Page fields should still be from the published version
        self.assertEqual(child_page_new.title, "Hello world!")

        # The draft_title should have a new title
        self.assertEqual(child_page_new.draft_title, "I've been edited again!")

        # There should still be only two revisions, but the latest one should be overwritten
        self.assertEqual(self.child_page.revisions.count(), 2)
        self.assertEqual(self.child_page.get_latest_revision().id, revision.id)
        revision.refresh_from_db()
        self.assertEqual(revision.content["title"], "I've been edited again!")

    def test_overwrite_non_latest_revision(self):
        self.child_page.title = "A changed title"
        user_revision = self.child_page.save_revision(user=self.user)
        self.child_page.title = "Someone else's changed title"
        later_revision = self.child_page.save_revision()
        self.assertEqual(self.child_page.revisions.count(), 3)

        post_data = {
            "title": "I've been edited again!",
            "content": "Some content",
            "slug": "hello-world",
            "overwrite_revision_id": user_revision.id,
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)),
            post_data,
            headers={"Accept": "application/json"},
        )

        # Should be a 400 response
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "error_code": "invalid_revision",
                "error_message": "Saving will overwrite a newer version.",
            },
        )

        # Page fields should still be from the published version
        self.child_page.refresh_from_db()
        self.assertEqual(self.child_page.title, "Hello world!")

        # The passed revision for overwriting, and the actual latest revision, should both be unchanged
        self.assertEqual(self.child_page.revisions.count(), 3)
        user_revision.refresh_from_db()
        self.assertEqual(user_revision.content["title"], "A changed title")
        later_revision.refresh_from_db()
        self.assertEqual(
            later_revision.content["title"], "Someone else's changed title"
        )
        self.assertEqual(self.child_page.get_latest_revision().id, later_revision.id)

    def test_get_hydrate_create_view(self):
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,))
            + "?_w_hydrate_create_view=1",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailadmin/pages/edit_partials.html")
        soup = self.get_soup(response.content)

        # Should reload the status and preview side panels
        side_panels = soup.select(
            "template[data-controller='w-teleport']"
            "[data-w-teleport-target-value^='[data-side-panel=']"
            "[data-w-teleport-mode-value='innerHTML']"
        )
        self.assertEqual(len(side_panels), 2)
        status_side_panel = side_panels[0]
        self.assertEqual(
            status_side_panel["data-w-teleport-target-value"],
            "[data-side-panel='status']",
        )

        # Under normal circumstances, a newly-created page would never
        # immediately enter a workflow without a full-page reload, so don't
        # bother rendering the workflow status dialog when hydrating a create view
        workflow_status_dialog = soup.find("div", id="workflow-status-dialog")
        self.assertIsNone(workflow_status_dialog)
        # However, we should still render the set privacy dialog, since the
        # user might want to set the page to private immediately after creating it,
        # and a full-page reload is not required for that
        set_privacy_dialog = soup.find("div", id="set-privacy")
        self.assertIsNotNone(set_privacy_dialog)

        # We need to change the preview URL to use the one for editing, but there is
        # no way to declaratively change attributes via partial rendering yet, and we
        # need to restart the controller anyway, so just re-render the whole panel
        preview_side_panel = side_panels[1]
        self.assertEqual(
            preview_side_panel["data-w-teleport-target-value"],
            "[data-side-panel='preview']",
        )
        preview_url = reverse(
            "wagtailadmin_pages:preview_on_edit", args=(self.child_page.id,)
        )
        self.assertIsNotNone(
            preview_side_panel.select_one(f"[data-w-preview-url-value='{preview_url}']")
        )

        breadcrumbs = soup.find(
            "template",
            {
                "data-controller": "w-teleport",
                "data-w-teleport-target-value": "header [data-w-breadcrumbs]",
                "data-w-teleport-mode-value": "outerHTML",
            },
        )
        self.assertIsNotNone(breadcrumbs)
        # Should include header buttons as they were not rendered in the create view
        self.assertIsNotNone(breadcrumbs.select_one("nav#w-slim-header-buttons"))

        # Should render the history link button as it wasn't rendered in the create view
        history_link = soup.find(
            "template",
            {
                "data-controller": "w-teleport",
                "data-w-teleport-target-value": "[data-side-panel-toggle]:last-of-type",
                "data-w-teleport-mode-value": "afterend",
            },
        )
        history_url = reverse("wagtailadmin_pages:history", args=(self.child_page.id,))
        self.assertIsNotNone(history_link)
        self.assertIsNotNone(history_link.select_one(f"a[href='{history_url}']"))

        form_title_heading = soup.find(
            "template",
            {
                "data-controller": "w-teleport",
                "data-w-teleport-target-value": "#header-title span",
                "data-w-teleport-mode-value": "textContent",
            },
        )
        self.assertIsNone(form_title_heading)
        header_title = soup.find(
            "template",
            {
                "data-controller": "w-teleport",
                "data-w-teleport-target-value": "head title",
                "data-w-teleport-mode-value": "textContent",
            },
        )
        self.assertIsNotNone(header_title)
        self.assertEqual(
            header_title.text.strip(),
            "Editing Simple page: Hello world! (simple page)",
        )

        # Should include loaded revision ID and timestamp in the form for
        # subsequent autosave requests
        form_adds = soup.find(
            "template",
            {
                "data-controller": "w-teleport",
                "data-w-teleport-target-value": "form[data-edit-form]",
                "data-w-teleport-mode-value": "afterbegin",
            },
        )
        latest_revision = self.child_page.get_latest_revision()
        self.assertIsNotNone(form_adds)
        self.assertEqual(
            form_adds.select_one("input[name='loaded_revision_id']")["value"],
            str(latest_revision.pk),
        )
        self.assertEqual(
            form_adds.select_one("input[name='loaded_revision_created_at']")["value"],
            latest_revision.created_at.isoformat(),
        )

        # Should load the editing sessions module as it was not in the create view
        editing_sessions = soup.find(
            "template",
            {
                "data-controller": "w-teleport",
                "data-w-teleport-target-value": "#w-autosave-indicator",
                "data-w-teleport-mode-value": "afterend",
            },
        )
        self.assertIsNotNone(editing_sessions)
        self.assertEqual(
            editing_sessions.select_one("input[name='revision_id']")["value"],
            str(latest_revision.pk),
        )
        self.assertEqual(
            editing_sessions.select_one("input[name='revision_created_at']")["value"],
            latest_revision.created_at.isoformat(),
        )

    def test_save_with_json_response_does_not_affect_sessions(self):
        # an old session that would be cleaned up when loading the editor
        old_session = EditingSession.objects.create(
            user=self.user,
            content_type=get_default_page_content_type(),
            object_id=self.child_page.pk,
            last_seen_at=timezone.now() - datetime.timedelta(hours=5),
        )
        # a recent session that would not be cleaned up when loading the editor
        recent_session = EditingSession.objects.create(
            user=self.user,
            content_type=get_default_page_content_type(),
            object_id=self.child_page.pk,
            last_seen_at=timezone.now() - datetime.timedelta(seconds=5),
        )
        loaded_revision = self.child_page.get_latest_revision()
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "loaded_revision_id": loaded_revision.pk,
            "loaded_revision_created_at": loaded_revision.created_at.isoformat(),
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.pk,)),
            post_data,
            headers={"Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        # Saving with a JSON response does not fully load the editor, so it
        # should not run a cleanup of old sessions, nor should it create a new
        # session for the current request.
        self.assertEqual(
            list(EditingSession.objects.values_list("pk", flat=True).order_by("pk")),
            [old_session.pk, recent_session.pk],
        )

    def test_page_edit_post_unpublished_page(self):
        # Based on test_page_edit_post(), but tests changes on a draft page vs. live page.
        post_data = {
            "title": "Hello unpublished world! edited",
            "content": "hello edited",
            "slug": "hello-unpublished-world-edited",
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.unpublished_page.id,)),
            post_data,
        )

        # Should be redirected to edit page
        self.assertRedirects(
            response,
            reverse("wagtailadmin_pages:edit", args=(self.unpublished_page.id,)),
        )

        # The page should have "has_unpublished_changes" flag set
        child_page_new = SimplePage.objects.get(id=self.unpublished_page.id)
        self.assertTrue(child_page_new.has_unpublished_changes)
        self.assertFalse(child_page_new.live)

        # Page fields should be changed, since the page is still a draft
        self.assertEqual(child_page_new.title, "Hello unpublished world! edited")
        self.assertEqual(child_page_new.content, "hello edited")
        self.assertEqual(child_page_new.slug, "hello-unpublished-world-edited")

        # The draft_title should have a new title
        self.assertEqual(child_page_new.draft_title, post_data["title"])

        # Publish the page
        go_live_at = timezone.now()
        post_data.update(
            {
                "action-publish": "Publish",
                "go_live_at": submittable_timestamp(go_live_at),
            }
        )
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.unpublished_page.id,)),
            post_data,
        )

        # Should be redirected to explorer page
        self.assertEqual(response.status_code, 302)

        # The page should be live now
        child_page_new = SimplePage.objects.get(id=self.unpublished_page.id)
        self.assertTrue(child_page_new.live)

        # We edit the live page again, but now those changes must not be written to the database.
        post_data = {
            "title": "Hello unpublished world! edited 2",
            "content": "hello edited 2",
            "slug": "hello-unpublished-world-edited-2",
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.unpublished_page.id,)),
            post_data,
        )

        # Should be redirected to edit page
        self.assertRedirects(
            response,
            reverse("wagtailadmin_pages:edit", args=(self.unpublished_page.id,)),
        )

        # The page should have "has_unpublished_changes" flag set
        child_page_new = SimplePage.objects.get(id=self.unpublished_page.id)
        self.assertTrue(child_page_new.has_unpublished_changes)

        # live Page fields should not be changed
        self.assertEqual(child_page_new.title, "Hello unpublished world! edited")
        self.assertEqual(child_page_new.content, "hello edited")
        self.assertEqual(child_page_new.slug, "hello-unpublished-world-edited")

        # The draft_title should have a new title
        self.assertEqual(child_page_new.draft_title, post_data["title"])

    def test_required_field_validation_skipped_when_saving_draft(self):
        post_data = {
            "title": "Hello unpublished world! edited",
            "content": "",
            "slug": "hello-unpublished-world-edited",
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.unpublished_page.id,)),
            post_data,
        )
        self.assertRedirects(
            response,
            reverse("wagtailadmin_pages:edit", args=(self.unpublished_page.id,)),
        )
        self.unpublished_page.refresh_from_db()
        self.assertEqual(self.unpublished_page.content, "")

    def test_save_draft_streampage_with_empty_blocks_in_body(self):
        page = StreamPage(title="Stream page", live=False)
        self.root_page.add_child(instance=page)
        page.save_revision()

        post_data = nested_form_data(
            {
                "title": "Stream page edited",
                "slug": "stream-page-edited",
                "body": streamfield(
                    [
                        ("text", ""),
                        ("rich_text", {}),
                        ("product", {"name": "", "price": ""}),
                        ("raw_html", ""),
                        ("books", streamfield([("title", ""), ("author", "")])),
                        ("title_list", streamfield([("title", "")])),
                        (
                            "image_with_alt",
                            {"image": "", "decorative": "", "alt_text": ""},
                        ),
                    ]
                ),
            }
        )
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(page.id,)),
            post_data,
        )
        page.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(page.title, "Stream page edited")
        self.assertEqual(len(page.body), 7)
        self.assertFalse(page.live)

    def test_required_field_validation_enforced_on_publish(self):
        post_data = {
            "title": "Hello unpublished world! edited",
            "content": "",
            "slug": "hello-unpublished-world-edited",
            "action-publish": "Publish",
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.unpublished_page.id,)),
            post_data,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required.")

    def test_publish_streampage_with_empty_blocks_in_body(self):
        page = StreamPage(title="Stream page", live=False)
        self.root_page.add_child(instance=page)
        page.save_revision()

        post_data = nested_form_data(
            {
                "title": "Stream page edited",
                "slug": "stream-page-edited",
                "action-publish": "Publish",
                "body": streamfield(
                    [
                        ("text", ""),
                        ("rich_text", {}),
                        ("product", {"name": "", "price": ""}),
                        ("raw_html", ""),
                        ("books", streamfield([("title", ""), ("author", "")])),
                        ("title_list", streamfield([("title", "")])),
                        (
                            "image_with_alt",
                            {"image": "", "decorative": "", "alt_text": ""},
                        ),
                    ]
                ),
            }
        )
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(page.id,)),
            post_data,
        )
        page.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(page.title, "Stream page")
        self.assertEqual(len(page.body), 0)
        self.assertFalse(page.live)

    def test_required_asterisk_on_reshowing_form(self):
        """
        If a form is reshown due to a validation error elsewhere, fields whose validation
        was deferred should still show the required asterisk.
        """
        post_data = {
            "title": "Event page",
            "date_from": "",
            "slug": "event-page",
            "audience": "public",
            "location": "",
            "cost": "Free",
            "signup_link": "Not a valid URL",
            "carousel_items-TOTAL_FORMS": 0,
            "carousel_items-INITIAL_FORMS": 0,
            "carousel_items-MIN_NUM_FORMS": 0,
            "carousel_items-MAX_NUM_FORMS": 0,
            "speakers-TOTAL_FORMS": 0,
            "speakers-INITIAL_FORMS": 0,
            "speakers-MIN_NUM_FORMS": 0,
            "speakers-MAX_NUM_FORMS": 0,
            "related_links-TOTAL_FORMS": 0,
            "related_links-INITIAL_FORMS": 0,
            "related_links-MIN_NUM_FORMS": 0,
            "related_links-MAX_NUM_FORMS": 0,
            "head_counts-TOTAL_FORMS": 0,
            "head_counts-INITIAL_FORMS": 0,
            "head_counts-MIN_NUM_FORMS": 0,
            "head_counts-MAX_NUM_FORMS": 0,
        }
        response = self.client.post(
            reverse(
                "wagtailadmin_pages:edit",
                args=[self.event_page.id],
            ),
            post_data,
        )
        self.assertEqual(response.status_code, 200)

        # Empty fields should not cause a validation error, but the invalid URL should
        self.assertNotContains(response, "This field is required.")
        self.assertContains(response, "Enter a valid URL.", count=1)

        # Asterisks should still show against required fields
        soup = self.get_soup(response.content)
        self.assertTrue(
            soup.select_one('label[for="id_date_from"] > span.w-required-mark')
        )
        self.assertTrue(
            soup.select_one('label[for="id_location"] > span.w-required-mark')
        )

    def test_page_edit_post_when_locked(self):
        # Tests that trying to edit a locked page results in an error

        # Lock the page
        self.child_page.locked = True
        self.child_page.save()

        # Post
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)), post_data
        )

        # Shouldn't be redirected
        self.assertContains(response, "The page could not be saved as it is locked")

        # The page shouldn't have "has_unpublished_changes" flag set
        child_page_new = SimplePage.objects.get(id=self.child_page.id)
        self.assertFalse(child_page_new.has_unpublished_changes)

    def test_page_edit_post_when_locked_with_json_response(self):
        # Tests that trying to edit a locked page results in an error

        # Lock the page
        self.child_page.locked = True
        self.child_page.save()

        # Post
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)),
            post_data,
            headers={"Accept": "application/json"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "error_code": "locked",
                "error_message": "The page could not be saved as it is locked.",
            },
        )

        # The page shouldn't have "has_unpublished_changes" flag set
        child_page_new = SimplePage.objects.get(id=self.child_page.id)
        self.assertFalse(child_page_new.has_unpublished_changes)

    def test_edit_post_scheduled(self):
        # put go_live_at and expire_at several days away from the current date, to avoid
        # false matches in content__ tests
        go_live_at = timezone.now() + datetime.timedelta(days=10)
        expire_at = timezone.now() + datetime.timedelta(days=20)
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "go_live_at": submittable_timestamp(go_live_at),
            "expire_at": submittable_timestamp(expire_at),
        }
        edit_url = reverse("wagtailadmin_pages:edit", args=(self.child_page.id,))
        response = self.client.post(edit_url, post_data, follow=True)

        # Should be redirected to the edit page again
        self.assertRedirects(response, edit_url, 302, 200)

        child_page_new = SimplePage.objects.get(id=self.child_page.id)

        # The page will still be live
        self.assertTrue(child_page_new.live)

        # A revision with approved_go_live_at should not exist
        self.assertFalse(
            Revision.page_revisions.filter(object_id=child_page_new.id)
            .exclude(approved_go_live_at__isnull=True)
            .exists()
        )

        # But a revision with go_live_at and expire_at in their content json *should* exist
        self.assertTrue(
            Revision.page_revisions.filter(
                object_id=child_page_new.id,
                content__go_live_at__startswith=str(go_live_at.date()),
            ).exists()
        )
        self.assertTrue(
            Revision.page_revisions.filter(
                object_id=child_page_new.id,
                content__expire_at__startswith=str(expire_at.date()),
            ).exists()
        )

        # Should show the draft go_live_at and expire_at under the "Once scheduled" label
        self.assertContains(
            response,
            '<div class="w-label-3 w-text-primary">Once scheduled:</div>',
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            f'<span class="w-text-grey-600">Go-live:</span> {render_timestamp(go_live_at)}',
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            f'<span class="w-text-grey-600">Expiry:</span> {render_timestamp(expire_at)}',
            html=True,
            count=1,
        )

        self.assertSchedulingDialogRendered(response, edit_url)

        self.assertContains(
            response,
            'This publishing schedule will only take effect after you select the "Schedule to publish" option',
        )

    def test_edit_post_scheduled_custom_timezone(self):
        # Set user's timezone to something different from the server timezone
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={"current_time_zone": "Asia/Jakarta"},
        )

        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "go_live_at": "2022-03-20 06:00",
        }
        edit_url = reverse("wagtailadmin_pages:edit", args=(self.child_page.id,))
        response = self.client.post(edit_url, post_data, follow=True)
        html = response.content.decode()

        # Should be redirected to the edit page again
        self.assertRedirects(response, edit_url, 302, 200)

        child_page_new = SimplePage.objects.get(id=self.child_page.id)

        # The page will still be live
        self.assertTrue(child_page_new.live)

        # A revision with approved_go_live_at should not exist
        self.assertFalse(
            Revision.page_revisions.filter(object_id=child_page_new.id)
            .exclude(approved_go_live_at__isnull=True)
            .exists()
        )

        # But a revision with go_live_at in their content json *should* exist
        if settings.USE_TZ:
            # The saved timestamp should be in UTC
            self.assertTrue(
                Revision.page_revisions.filter(
                    object_id=child_page_new.id,
                    content__go_live_at="2022-03-19T23:00:00Z",
                ).exists()
            )
        else:
            # Without TZ support, just use the submitted timestamp as-is
            self.assertTrue(
                Revision.page_revisions.filter(
                    object_id=child_page_new.id,
                    content__go_live_at="2022-03-20T06:00:00",
                ).exists()
            )

        # Should show the draft go_live_at under the "Once scheduled" label
        # and should be in the user's timezone
        self.assertContains(
            response,
            '<div class="w-label-3 w-text-primary">Once scheduled:</div>',
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            '<span class="w-text-grey-600">Go-live:</span> March 20, 2022, 6 a.m.',
            html=True,
            count=1,
        )

        self.assertSchedulingDialogRendered(response, edit_url)

        # Should show the input with the correct value in the user's timezone
        self.assertTagInHTML(
            '<input type="text" name="go_live_at" value="2022-03-20 06:00">',
            html,
            count=1,
            allow_extra_attrs=True,
        )

        self.assertContains(
            response,
            'This publishing schedule will only take effect after you select the "Schedule to publish" option',
        )

    def test_schedule_panel_without_publish_permission(self):
        editor = self.create_user("editor", password="password")
        editor.groups.add(Group.objects.get(name="Editors"))
        self.login(username="editor")
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.event_page.id,))
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Anyone with editing permissions can create schedules"
        )

    def test_edit_scheduled_go_live_before_expiry(self):
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "go_live_at": submittable_timestamp(
                timezone.now() + datetime.timedelta(days=2)
            ),
            "expire_at": submittable_timestamp(
                timezone.now() + datetime.timedelta(days=1)
            ),
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)), post_data
        )

        self.assertEqual(response.status_code, 200)

        # Check that a form error was raised
        self.assertFormError(
            response.context["form"],
            "go_live_at",
            "Go live date/time must be before expiry date/time",
        )
        self.assertFormError(
            response.context["form"],
            "expire_at",
            "Go live date/time must be before expiry date/time",
        )

        self.assertContains(
            response,
            '<div class="w-label-3 w-text-primary">Invalid schedule</div>',
            html=True,
        )

        num_errors = 2

        # Should show the correct number on the badge of the toggle button
        self.assertRegex(
            response.content.decode(),
            self.STATUS_TOGGLE_BADGE_REGEX % {"num_errors": num_errors},
        )

        # form should be marked as having unsaved changes for the purposes of the dirty-forms warning
        self.assertContains(response, 'data-w-unsaved-force-value="true"')

    def test_edit_scheduled_expire_in_the_past(self):
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "expire_at": submittable_timestamp(
                timezone.now() + datetime.timedelta(days=-1)
            ),
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)), post_data
        )

        self.assertEqual(response.status_code, 200)

        # Check that a form error was raised
        self.assertFormError(
            response.context["form"],
            "expire_at",
            "Expiry date/time must be in the future.",
        )

        self.assertContains(
            response,
            '<div class="w-label-3 w-text-primary">Invalid schedule</div>',
            html=True,
        )

        num_errors = 1

        # Should show the correct number on the badge of the toggle button
        self.assertRegex(
            response.content.decode(),
            self.STATUS_TOGGLE_BADGE_REGEX % {"num_errors": num_errors},
        )

        # form should be marked as having unsaved changes for the purposes of the dirty-forms warning
        self.assertContains(response, 'data-w-unsaved-force-value="true"')

    def test_edit_post_invalid_schedule_with_existing_draft_schedule(self):
        self.child_page.go_live_at = timezone.now() + datetime.timedelta(days=1)
        self.child_page.expire_at = timezone.now() + datetime.timedelta(days=2)
        latest_revision = self.child_page.save_revision()

        go_live_at = timezone.now() + datetime.timedelta(days=10)
        expire_at = timezone.now() + datetime.timedelta(days=-20)
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "go_live_at": submittable_timestamp(go_live_at),
            "expire_at": submittable_timestamp(expire_at),
        }
        edit_url = reverse("wagtailadmin_pages:edit", args=(self.child_page.id,))
        response = self.client.post(edit_url, post_data)

        # Should render the edit page with errors instead of redirecting
        self.assertEqual(response.status_code, 200)

        child_page_new = SimplePage.objects.get(id=self.child_page.id)

        # The page will still be live
        self.assertTrue(child_page_new.live)

        # No new revision should have been created
        self.assertEqual(child_page_new.latest_revision_id, latest_revision.pk)

        # Should not show the draft go_live_at and expire_at under the "Once scheduled" label
        self.assertNotContains(
            response,
            '<div class="w-label-3 w-text-primary">Once scheduled:</div>',
            html=True,
        )
        self.assertNotContains(
            response,
            '<span class="w-text-grey-600">Go-live:</span>',
            html=True,
        )
        self.assertNotContains(
            response,
            '<span class="w-text-grey-600">Expiry:</span>',
            html=True,
        )

        # Should show the "Edit schedule" button
        html = response.content.decode()
        self.assertTagInHTML(
            '<button type="button" data-a11y-dialog-show="schedule-publishing-dialog">Edit schedule</button>',
            html,
            count=1,
            allow_extra_attrs=True,
        )

        self.assertContains(
            response,
            '<div class="w-label-3 w-text-primary">Invalid schedule</div>',
            html=True,
        )

        num_errors = 2

        # Should show the correct number on the badge of the toggle button
        self.assertRegex(
            response.content.decode(),
            self.STATUS_TOGGLE_BADGE_REGEX % {"num_errors": num_errors},
        )

    def test_page_edit_post_publish(self):
        # Connect a mock signal handler to page_published signal
        mock_handler = mock.MagicMock()
        page_published.connect(mock_handler)

        try:
            # Set has_unpublished_changes=True on the existing record to confirm that the publish action
            # is resetting it (and not just leaving it alone)
            self.child_page.has_unpublished_changes = True
            self.child_page.save()

            # Save current value of first_published_at so we can check that it doesn't change
            first_published_at = SimplePage.objects.get(
                id=self.child_page.id
            ).first_published_at

            # Tests publish from edit page
            post_data = {
                "title": "I've been edited!",
                "content": "Some content",
                "slug": "hello-world-new",
                "action-publish": "Publish",
            }
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)),
                post_data,
                follow=True,
            )

            # Should be redirected to explorer
            self.assertRedirects(
                response, reverse("wagtailadmin_explore", args=(self.root_page.id,))
            )

            # Check that the page was edited
            child_page_new = SimplePage.objects.get(id=self.child_page.id)
            self.assertEqual(child_page_new.title, post_data["title"])
            self.assertEqual(child_page_new.draft_title, post_data["title"])

            # Check that the page_published signal was fired
            self.assertEqual(mock_handler.call_count, 1)
            mock_call = mock_handler.mock_calls[0][2]

            self.assertEqual(mock_call["sender"], child_page_new.specific_class)
            self.assertEqual(mock_call["instance"], child_page_new)
            self.assertIsInstance(mock_call["instance"], child_page_new.specific_class)

            # The page shouldn't have "has_unpublished_changes" flag set
            self.assertFalse(child_page_new.has_unpublished_changes)

            # first_published_at should not change as it was already set
            self.assertEqual(first_published_at, child_page_new.first_published_at)

            # The "View Live" button should have the updated slug.
            for message in response.context["messages"]:
                self.assertIn("hello-world-new", message.message)
                break
        finally:
            page_published.disconnect(mock_handler)

    def test_first_published_at_editable(self):
        """Test that we can update the first_published_at via the Page edit form,
        for page models that expose it."""

        # Add child page, of a type which has first_published_at in its form
        child_page = ManyToManyBlogPage(
            title="Hello world!",
            slug="hello-again-world",
            body="hello",
        )
        self.root_page.add_child(instance=child_page)
        child_page.save_revision().publish()
        self.child_page = ManyToManyBlogPage.objects.get(id=child_page.id)

        initial_delta = self.child_page.first_published_at - timezone.now()

        first_published_at = timezone.now() - datetime.timedelta(days=2)

        post_data = {
            "title": "I've been edited!",
            "body": "Some content",
            "slug": "hello-again-world",
            "action-publish": "Publish",
            "first_published_at": submittable_timestamp(first_published_at),
            "comments-TOTAL_FORMS": 0,
            "comments-INITIAL_FORMS": 0,
            "comments-MIN_NUM_FORMS": 0,
            "comments-MAX_NUM_FORMS": 1000,
        }
        self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)), post_data
        )

        # Get the edited page.
        child_page_new = ManyToManyBlogPage.objects.get(id=self.child_page.id)

        # first_published_at should have changed.
        new_delta = child_page_new.first_published_at - timezone.now()
        self.assertNotEqual(new_delta.days, initial_delta.days)
        # first_published_at should be 3 days ago.
        self.assertEqual(new_delta.days, -3)

    def test_edit_post_publish_scheduled_unpublished_page(self):
        # Unpublish the page
        self.child_page.live = False
        self.child_page.save()

        go_live_at = timezone.now() + datetime.timedelta(days=1)
        expire_at = timezone.now() + datetime.timedelta(days=2)
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "action-publish": "Publish",
            "go_live_at": submittable_timestamp(go_live_at),
            "expire_at": submittable_timestamp(expire_at),
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)), post_data
        )

        # Should be redirected to explorer page
        self.assertEqual(response.status_code, 302)

        child_page_new = SimplePage.objects.get(id=self.child_page.id)

        # The page should not be live anymore
        self.assertFalse(child_page_new.live)

        # Instead a revision with approved_go_live_at should now exist
        self.assertTrue(
            Revision.page_revisions.filter(object_id=child_page_new.id)
            .exclude(approved_go_live_at__isnull=True)
            .exists()
        )

        # The page SHOULD have the "has_unpublished_changes" flag set,
        # because the changes are not visible as a live page yet
        self.assertTrue(
            child_page_new.has_unpublished_changes,
            msg="A page scheduled for future publishing should have has_unpublished_changes=True",
        )

        self.assertEqual(child_page_new.status_string, "scheduled")

        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)), post_data
        )

        # Should show the go_live_at and expire_at without the "Once scheduled" label
        self.assertNotContains(
            response,
            '<div class="w-label-3 w-text-primary">Once scheduled:</div>',
            html=True,
        )
        self.assertContains(
            response,
            f'<span class="w-text-grey-600">Go-live:</span> {render_timestamp(go_live_at)}',
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            f'<span class="w-text-grey-600">Expiry:</span> {render_timestamp(expire_at)}',
            html=True,
            count=1,
        )

        # Should not show the "Edit schedule" button
        html = response.content.decode()
        self.assertTagInHTML(
            '<button type="button" data-a11y-dialog-show="schedule-publishing-dialog">Edit schedule</button>',
            html,
            count=0,
            allow_extra_attrs=True,
        )

    def test_edit_post_publish_now_an_already_scheduled_unpublished_page(self):
        # Unpublish the page
        self.child_page.live = False
        self.child_page.save()

        # First let's publish a page with a go_live_at in the future
        go_live_at = timezone.now() + datetime.timedelta(days=1)
        expire_at = timezone.now() + datetime.timedelta(days=2)
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "action-publish": "Publish",
            "go_live_at": submittable_timestamp(go_live_at),
            "expire_at": submittable_timestamp(expire_at),
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)), post_data
        )

        # Should be redirected to edit page
        self.assertEqual(response.status_code, 302)

        child_page_new = SimplePage.objects.get(id=self.child_page.id)

        # The page should not be live
        self.assertFalse(child_page_new.live)

        self.assertEqual(child_page_new.status_string, "scheduled")

        # Instead a revision with approved_go_live_at should now exist
        self.assertTrue(
            Revision.page_revisions.filter(object_id=child_page_new.id)
            .exclude(approved_go_live_at__isnull=True)
            .exists()
        )

        # Now, let's edit it and publish it right now
        go_live_at = timezone.now()
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "action-publish": "Publish",
            "go_live_at": go_live_at,
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)), post_data
        )

        # Should be blocked, as the page is already scheduled
        self.assertEqual(response.status_code, 200)

        child_page_new = SimplePage.objects.get(id=self.child_page.id)

        # The page should not be live
        self.assertFalse(child_page_new.live)

        # The revision with approved_go_live_at should still exist
        self.assertTrue(
            Revision.page_revisions.filter(object_id=child_page_new.id)
            .exclude(approved_go_live_at__isnull=True)
            .exists()
        )

        # Should not show the "Edit schedule" button
        html = response.content.decode()
        self.assertTagInHTML(
            '<button type="button" data-a11y-dialog-show="schedule-publishing-dialog">Edit schedule</button>',
            html,
            count=0,
            allow_extra_attrs=True,
        )

    def test_edit_post_publish_scheduled_published_page(self):
        # Page is live
        self.child_page.live = True
        self.child_page.save()

        live_revision = self.child_page.live_revision
        original_title = self.child_page.title

        go_live_at = timezone.now() + datetime.timedelta(days=1)
        expire_at = timezone.now() + datetime.timedelta(days=2)
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "action-publish": "Publish",
            "go_live_at": submittable_timestamp(go_live_at),
            "expire_at": submittable_timestamp(expire_at),
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)), post_data
        )

        # Should be redirected to explorer page
        self.assertEqual(response.status_code, 302)

        child_page_new = SimplePage.objects.get(id=self.child_page.id)

        # The page should still be live
        self.assertTrue(child_page_new.live)

        self.assertEqual(child_page_new.status_string, "live + scheduled")

        # Instead a revision with approved_go_live_at should now exist
        self.assertTrue(
            Revision.page_revisions.filter(object_id=child_page_new.id)
            .exclude(approved_go_live_at__isnull=True)
            .exists()
        )

        # The page SHOULD have the "has_unpublished_changes" flag set,
        # because the changes are not visible as a live page yet
        self.assertTrue(
            child_page_new.has_unpublished_changes,
            msg="A page scheduled for future publishing should have has_unpublished_changes=True",
        )

        self.assertNotEqual(
            child_page_new.get_latest_revision(),
            live_revision,
            "A page scheduled for future publishing should have a new revision, that is not the live revision",
        )

        self.assertEqual(
            child_page_new.title,
            original_title,
            msg="A live page with scheduled revisions should still have original content",
        )

        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)), post_data
        )

        # Should show the go_live_at and expire_at without the "Once scheduled" label
        self.assertNotContains(
            response,
            '<div class="w-label-3 w-text-primary">Once scheduled:</div>',
            html=True,
        )
        self.assertContains(
            response,
            f'<span class="w-text-grey-600">Go-live:</span> {render_timestamp(go_live_at)}',
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            f'<span class="w-text-grey-600">Expiry:</span> {render_timestamp(expire_at)}',
            html=True,
            count=1,
        )

        # Should not show the "Edit schedule" button
        html = response.content.decode()
        self.assertTagInHTML(
            '<button type="button" data-a11y-dialog-show="schedule-publishing-dialog">Edit schedule</button>',
            html,
            count=0,
            allow_extra_attrs=True,
        )

    def test_edit_post_publish_now_an_already_scheduled_published_page(self):
        # Unpublish the page
        self.child_page.live = True
        self.child_page.save()

        original_title = self.child_page.title
        # First let's publish a page with a go_live_at in the future
        go_live_at = timezone.now() + datetime.timedelta(days=1)
        expire_at = timezone.now() + datetime.timedelta(days=2)
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "action-publish": "Publish",
            "go_live_at": submittable_timestamp(go_live_at),
            "expire_at": submittable_timestamp(expire_at),
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)), post_data
        )

        # Should be redirected to edit page
        self.assertEqual(response.status_code, 302)

        child_page_new = SimplePage.objects.get(id=self.child_page.id)

        # The page should still be live
        self.assertTrue(child_page_new.live)

        # Instead a revision with approved_go_live_at should now exist
        self.assertTrue(
            Revision.page_revisions.filter(object_id=child_page_new.id)
            .exclude(approved_go_live_at__isnull=True)
            .exists()
        )

        self.assertEqual(
            child_page_new.title,
            original_title,
            "A live page with scheduled revisions should still have original content",
        )

        # Now, let's edit it and publish it right now
        go_live_at = timezone.now()
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "action-publish": "Publish",
            "go_live_at": go_live_at,
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)), post_data
        )

        # Should be blocked, as the page is alrready scheduled
        self.assertEqual(response.status_code, 200)

        child_page_new = SimplePage.objects.get(id=self.child_page.id)

        # The page should still be live
        self.assertTrue(child_page_new.live)

        # The scheduled revision should still exist
        self.assertTrue(
            Revision.page_revisions.filter(object_id=child_page_new.id)
            .exclude(approved_go_live_at__isnull=True)
            .exists()
        )

        # The title should still be the same, as the publish didn't work
        self.assertEqual(
            child_page_new.title,
            "Hello world!",
        )

    def test_edit_post_save_schedule_before_a_scheduled_expire_page(self):
        # First let's publish a page with *just* an expire_at in the future
        expire_at = timezone.now() + datetime.timedelta(days=20)
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "action-publish": "Publish",
            "expire_at": submittable_timestamp(expire_at),
        }
        edit_url = reverse("wagtailadmin_pages:edit", args=(self.child_page.id,))
        response = self.client.post(edit_url, post_data)

        # Should be redirected to page explorer
        self.assertEqual(response.status_code, 302)

        child_page_new = SimplePage.objects.get(id=self.child_page.id)

        # The page should still be live
        self.assertTrue(child_page_new.live)

        self.assertEqual(child_page_new.status_string, "live")

        # The live page object should have the expire_at field set
        self.assertEqual(
            child_page_new.expire_at,
            expire_at.replace(second=0, microsecond=0),
        )

        # Now, let's save a page with a go_live_at in the future,
        # but before the existing expire_at
        go_live_at = timezone.now() + datetime.timedelta(days=10)
        new_expire_at = timezone.now() + datetime.timedelta(days=15)
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "go_live_at": submittable_timestamp(go_live_at),
            "expire_at": submittable_timestamp(new_expire_at),
        }
        response = self.client.post(edit_url, post_data, follow=True)

        # Should be redirected to the edit page again
        self.assertRedirects(response, edit_url, 302, 200)

        child_page_new = SimplePage.objects.get(id=self.child_page.id)

        # The page will still be live
        self.assertTrue(child_page_new.live)

        # A revision with approved_go_live_at should not exist
        self.assertFalse(
            Revision.page_revisions.filter(object_id=child_page_new.id)
            .exclude(approved_go_live_at__isnull=True)
            .exists()
        )

        # But a revision with go_live_at and expire_at in their content json *should* exist
        self.assertTrue(
            Revision.page_revisions.filter(
                object_id=child_page_new.id,
                content__go_live_at__startswith=str(go_live_at.date()),
            ).exists()
        )
        self.assertTrue(
            Revision.page_revisions.filter(
                object_id=child_page_new.id,
                content__expire_at__startswith=str(expire_at.date()),
            ).exists()
        )

        # Should still show the active expire_at in the live object
        self.assertContains(
            response,
            f'<span class="w-text-grey-600">Expiry:</span> {render_timestamp(expire_at)}',
            html=True,
            count=1,
        )

        # Should also show the draft go_live_at and expire_at under the "Once scheduled" label
        self.assertContains(
            response,
            '<div class="w-label-3 w-text-primary">Once scheduled:</div>',
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            f'<span class="w-text-grey-600">Go-live:</span> {render_timestamp(go_live_at)}',
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            f'<span class="w-text-grey-600">Expiry:</span> {render_timestamp(new_expire_at)}',
            html=True,
            count=1,
        )
        self.assertSchedulingDialogRendered(response, edit_url)

    def test_edit_post_publish_schedule_before_a_scheduled_expire_page(self):
        # First let's publish a page with *just* an expire_at in the future
        expire_at = timezone.now() + datetime.timedelta(days=20)
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "action-publish": "Publish",
            "expire_at": submittable_timestamp(expire_at),
        }
        edit_url = reverse("wagtailadmin_pages:edit", args=(self.child_page.id,))
        response = self.client.post(edit_url, post_data)

        # Should be redirected to page explorer
        self.assertEqual(response.status_code, 302)

        child_page_new = SimplePage.objects.get(id=self.child_page.id)

        # The page should still be live
        self.assertTrue(child_page_new.live)

        self.assertEqual(child_page_new.status_string, "live")

        # The live page object should have the expire_at field set
        self.assertEqual(
            child_page_new.expire_at,
            expire_at.replace(second=0, microsecond=0),
        )

        # Now, let's publish a page with a go_live_at in the future,
        # but before the existing expire_at
        go_live_at = timezone.now() + datetime.timedelta(days=10)
        new_expire_at = timezone.now() + datetime.timedelta(days=15)
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "action-publish": "Publish",
            "go_live_at": submittable_timestamp(go_live_at),
            "expire_at": submittable_timestamp(new_expire_at),
        }
        response = self.client.post(edit_url, post_data)

        # Should be redirected to page explorer
        self.assertEqual(response.status_code, 302)

        child_page_new = SimplePage.objects.get(id=self.child_page.id)

        # The page should still be live
        self.assertTrue(child_page_new.live)

        self.assertEqual(child_page_new.status_string, "live + scheduled")

        # A revision with approved_go_live_at should now exist
        self.assertTrue(
            Revision.page_revisions.filter(object_id=child_page_new.id)
            .exclude(approved_go_live_at__isnull=True)
            .exists()
        )

        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)), post_data
        )

        # Should not show the active expire_at in the live object because the
        # scheduled revision is before the existing expire_at, which means it will
        # override the existing expire_at when it goes live
        self.assertNotContains(
            response,
            f'<span class="w-text-grey-600">Expiry:</span> {render_timestamp(expire_at)}',
            html=True,
        )

        # Should show the go_live_at and expire_at without the "Once scheduled" label
        self.assertNotContains(
            response,
            '<div class="w-label-3 w-text-primary">Once scheduled:</div>',
            html=True,
        )
        self.assertContains(
            response,
            f'<span class="w-text-grey-600">Go-live:</span> {render_timestamp(go_live_at)}',
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            f'<span class="w-text-grey-600">Expiry:</span> {render_timestamp(new_expire_at)}',
            html=True,
            count=1,
        )

        # Should not show the "Edit schedule" button
        html = response.content.decode()
        self.assertTagInHTML(
            '<button type="button" data-a11y-dialog-show="schedule-publishing-dialog">Edit schedule</button>',
            html,
            count=0,
            allow_extra_attrs=True,
        )

    def test_edit_post_publish_schedule_after_a_scheduled_expire_page(self):
        # First let's publish a page with *just* an expire_at in the future
        expire_at = timezone.now() + datetime.timedelta(days=20)
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "action-publish": "Publish",
            "expire_at": submittable_timestamp(expire_at),
        }
        edit_url = reverse("wagtailadmin_pages:edit", args=(self.child_page.id,))
        response = self.client.post(edit_url, post_data)

        # Should be redirected to page explorer
        self.assertEqual(response.status_code, 302)

        child_page_new = SimplePage.objects.get(id=self.child_page.id)

        # The page should still be live
        self.assertTrue(child_page_new.live)

        self.assertEqual(child_page_new.status_string, "live")

        # The live page object should have the expire_at field set
        self.assertEqual(
            child_page_new.expire_at,
            expire_at.replace(second=0, microsecond=0),
        )

        # Now, let's publish a page with a go_live_at in the future,
        # but after the existing expire_at
        go_live_at = timezone.now() + datetime.timedelta(days=23)
        new_expire_at = timezone.now() + datetime.timedelta(days=25)
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "action-publish": "Publish",
            "go_live_at": submittable_timestamp(go_live_at),
            "expire_at": submittable_timestamp(new_expire_at),
        }
        response = self.client.post(edit_url, post_data)

        # Should be redirected to page explorer
        self.assertEqual(response.status_code, 302)

        child_page_new = SimplePage.objects.get(id=self.child_page.id)

        # The page should still be live
        self.assertTrue(child_page_new.live)

        self.assertEqual(child_page_new.status_string, "live + scheduled")

        # Instead a revision with approved_go_live_at should now exist
        self.assertTrue(
            Revision.page_revisions.filter(object_id=child_page_new.id)
            .exclude(approved_go_live_at__isnull=True)
            .exists()
        )

        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)), post_data
        )

        # Should still show the active expire_at in the live object because the
        # scheduled revision is after the existing expire_at, which means the
        # new expire_at won't take effect until the revision goes live.
        # This means the page will be:
        # unpublished (expired) -> published (scheduled) -> unpublished (expired again)
        self.assertContains(
            response,
            f'<span class="w-text-grey-600">Expiry:</span> {render_timestamp(expire_at)}',
            html=True,
            count=1,
        )

        # Should show the go_live_at and expire_at without the "Once scheduled" label
        self.assertNotContains(
            response,
            '<div class="w-label-3 w-text-primary">Once scheduled:</div>',
            html=True,
        )
        self.assertContains(
            response,
            f'<span class="w-text-grey-600">Go-live:</span> {render_timestamp(go_live_at)}',
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            f'<span class="w-text-grey-600">Expiry:</span> {render_timestamp(new_expire_at)}',
            html=True,
            count=1,
        )

        # Should not show the "Edit schedule" button
        html = response.content.decode()
        self.assertTagInHTML(
            '<button type="button" data-a11y-dialog-show="schedule-publishing-dialog">Edit schedule</button>',
            html,
            count=0,
            allow_extra_attrs=True,
        )

    def test_page_edit_post_submit(self):
        # Create a moderator user for testing email
        self.create_superuser("moderator", "moderator@email.com", "password")

        # Tests submitting from edit page
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "action-submit": "Submit",
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)), post_data
        )

        # Should be redirected to explorer
        self.assertRedirects(
            response, reverse("wagtailadmin_explore", args=(self.root_page.id,))
        )

        # The page should have "has_unpublished_changes" flag set
        child_page_new = SimplePage.objects.get(id=self.child_page.id)
        self.assertTrue(child_page_new.has_unpublished_changes)

        # The latest revision for the page should now be in moderation
        self.assertEqual(
            child_page_new.current_workflow_state.status,
            child_page_new.current_workflow_state.STATUS_IN_PROGRESS,
        )

    def test_page_edit_post_existing_slug(self):
        # This tests the existing slug checking on page edit

        # Create a page
        self.child_page = SimplePage(
            title="Hello world 2", slug="hello-world2", content="hello"
        )
        self.root_page.add_child(instance=self.child_page)

        # Attempt to change the slug to one that's already in use
        post_data = {
            "title": "Hello world 2",
            "slug": "hello-world",
            "action-submit": "Submit",
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)), post_data
        )

        # Should not be redirected (as the save should fail)
        self.assertEqual(response.status_code, 200)

        # Check that a form error was raised
        self.assertFormError(
            response.context["form"],
            "slug",
            "The slug 'hello-world' is already in use within the parent page.",
        )

    def test_preview_on_edit(self):
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "action-submit": "Submit",
        }
        preview_url = reverse(
            "wagtailadmin_pages:preview_on_edit", args=(self.child_page.id,)
        )
        response = self.client.post(preview_url, post_data)

        # Check the JSON response
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content.decode(),
            {"is_valid": True, "is_available": True},
        )

        response = self.client.get(preview_url)

        # Check the HTML response
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "tests/simple_page.html")
        self.assertContains(response, "I&#39;ve been edited!", html=True)

        # Should not show edit link in the userbar
        # https://github.com/wagtail/wagtail/issues/8765
        self.assertNotContains(response, "Edit this page")
        self.assertNotContains(
            response, reverse("wagtailadmin_pages:edit", args=(self.child_page.id,))
        )

    def test_preview_on_edit_no_session_key(self):
        preview_url = reverse(
            "wagtailadmin_pages:preview_on_edit", args=(self.child_page.id,)
        )

        # get() without corresponding post(), key not set.
        response = self.client.get(preview_url)

        # Check the HTML response
        self.assertEqual(response.status_code, 200)

        # We should have an error page because we are unable to
        # preview; the page key was not in the session.
        self.assertContains(
            response, "<title>Preview not available - Wagtail</title>", html=True
        )
        self.assertContains(
            response,
            '<h1 class="preview-error__title">Preview not available</h1>',
            html=True,
        )

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            }
        }
    )
    @modify_settings(
        MIDDLEWARE={
            "append": "django.middleware.cache.FetchFromCacheMiddleware",
            "prepend": "django.middleware.cache.UpdateCacheMiddleware",
        }
    )
    def test_preview_does_not_cache(self):
        """
        Tests solution to issue #5975
        """
        post_data = {
            "title": "I've been edited one time!",
            "content": "Some content",
            "slug": "hello-world",
            "action-submit": "Submit",
        }
        preview_url = reverse(
            "wagtailadmin_pages:preview_on_edit", args=(self.child_page.id,)
        )
        self.client.post(preview_url, post_data)
        response = self.client.get(preview_url)
        self.assertContains(response, "I&#39;ve been edited one time!", html=True)

        post_data["title"] = "I've been edited two times!"
        self.client.post(preview_url, post_data)
        response = self.client.get(preview_url)
        self.assertContains(response, "I&#39;ve been edited two times!", html=True)

    @modify_settings(ALLOWED_HOSTS={"append": "childpage.example.com"})
    def test_preview_uses_correct_site(self):
        # create a Site record for the child page
        Site.objects.create(hostname="childpage.example.com", root_page=self.child_page)

        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "action-submit": "Submit",
        }
        preview_url = reverse(
            "wagtailadmin_pages:preview_on_edit", args=(self.child_page.id,)
        )
        response = self.client.post(preview_url, post_data)

        # Check the JSON response
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content.decode(),
            {"is_valid": True, "is_available": True},
        )

        response = self.client.get(preview_url)

        # Check that the correct site object has been selected by the site middleware
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "tests/simple_page.html")
        self.assertEqual(
            Site.find_for_request(response.context["request"]).hostname,
            "childpage.example.com",
        )

    def test_editor_picks_up_direct_model_edits(self):
        # If a page has no draft edits, the editor should show the version from the live database
        # record rather than the latest revision record. This ensures that the edit interface
        # reflects any changes made directly on the model.
        self.child_page.title = "This title only exists on the live database record"
        self.child_page.save()

        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,))
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "This title only exists on the live database record"
        )

    def test_editor_does_not_pick_up_direct_model_edits_when_draft_edits_exist(self):
        # If a page has draft edits, we should always show those in the editor, not the live
        # database record
        self.child_page.content = "Some content with a draft edit"
        self.child_page.save_revision()

        # make an independent change to the live database record
        self.child_page = SimplePage.objects.get(id=self.child_page.id)
        self.child_page.title = "This title only exists on the live database record"
        self.child_page.save()

        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,))
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response, "This title only exists on the live database record"
        )
        self.assertContains(response, "Some content with a draft edit")

    def test_editor_page_shows_live_url_in_status_when_draft_edits_exist(self):
        # If a page has draft edits (ie. page has unpublished changes)
        # that affect the URL (slug) we  should still ensure the
        # status button at the top of the page links to the live URL

        self.child_page.content = "Some content with a draft edit"
        self.child_page.slug = (
            "revised-slug-in-draft-only"  # live version contains 'hello-world'
        )
        self.child_page.save_revision()

        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,))
        )

        input_field_for_draft_slug = '<input type="text" name="slug" value="revised-slug-in-draft-only" data-controller="w-slug" data-action="blur-&gt;w-slug#slugify w-sync:check-&gt;w-slug#compare w-sync:apply-&gt;w-slug#urlify:prevent" data-w-slug-compare-as-param="urlify" data-w-slug-allow-unicode-value data-w-slug-trim-value="true" maxlength="255" aria-describedby="panel-child-promote-child-for_search_engines-child-slug-helptext" required id="id_slug">'
        input_field_for_live_slug = '<input type="text" name="slug" value="hello-world" data-controller="w-slug" data-action="blur-&gt;w-slug#slugify w-sync:check-&gt;w-slug#compare w-sync:apply-&gt;w-slug#urlify:prevent" data-w-slug-compare-as-param="urlify" data-w-slug-allow-unicode-value data-w-slug-trim-value="true" maxlength="255" aria-describedby="panel-child-promote-child-for_search_engines-child-slug-helptext" required id="id_slug" />'

        # Status Link should be the live page (not revision)
        self.assertNotContains(
            response, 'href="/revised-slug-in-draft-only/"', html=True
        )

        # Editing input for slug should be the draft revision
        self.assertContains(response, input_field_for_draft_slug, html=True)
        self.assertNotContains(response, input_field_for_live_slug, html=True)

    def test_editor_page_shows_custom_live_url_in_status_when_draft_edits_exist(self):
        # When showing a live URL in the status button that differs from the draft one,
        # ensure that we pick up any custom URL logic defined on the specific page model

        self.single_event_page.location = "The other side of Mars"
        self.single_event_page.slug = (
            "revised-slug-in-draft-only"  # live version contains 'hello-world'
        )
        self.single_event_page.save_revision()

        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.single_event_page.id,))
        )

        input_field_for_draft_slug = '<input type="text" name="slug" value="revised-slug-in-draft-only" data-controller="w-slug" data-action="blur-&gt;w-slug#slugify w-sync:check-&gt;w-slug#compare w-sync:apply-&gt;w-slug#urlify:prevent" data-w-slug-compare-as-param="urlify" data-w-slug-allow-unicode-value data-w-slug-trim-value="true" maxlength="255" aria-describedby="panel-child-promote-child-common_page_configuration-child-slug-helptext" required id="id_slug" />'
        input_field_for_live_slug = '<input type="text" name="slug" value="mars-landing" data-controller="w-slug" data-action="blur-&gt;w-slug#slugify w-sync:check-&gt;w-slug#compare w-sync:apply-&gt;w-slug#urlify:prevent" data-w-slug-compare-as-param="urlify" data-w-slug-allow-unicode-value data-w-slug-trim-value="true" maxlength="255" aria-describedby="panel-child-promote-child-common_page_configuration-child-slug-helptext" required id="id_slug" />'

        # Status Link should be the live page (not revision)
        self.assertNotContains(
            response, 'href="/revised-slug-in-draft-only/pointless-suffix/"', html=True
        )

        # Editing input for slug should be the draft revision
        self.assertContains(response, input_field_for_draft_slug, html=True)
        self.assertNotContains(response, input_field_for_live_slug, html=True)

    def test_before_edit_page_hook(self):
        def hook_func(request, page):
            self.assertIsInstance(request, HttpRequest)
            self.assertEqual(page.id, self.child_page.id)

            return HttpResponse("Overridden!")

        with self.register_hook("before_edit_page", hook_func):
            response = self.client.get(
                reverse("wagtailadmin_pages:edit", args=(self.child_page.id,))
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"Overridden!")

    def test_before_edit_page_hook_with_json_response(self):
        def non_json_hook_func(request, page):
            self.assertIsInstance(request, HttpRequest)
            self.assertEqual(page.id, self.child_page.id)

            return HttpResponse("Overridden!")

        def json_hook_func(request, page):
            self.assertIsInstance(request, HttpRequest)
            self.assertEqual(page.id, self.child_page.id)

            return JsonResponse({"status": "purple"})

        with self.register_hook("before_edit_page", non_json_hook_func):
            response = self.client.get(
                reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)),
                headers={"Accept": "application/json"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "error_code": "blocked_by_hook",
                "error_message": "Request to edit page was blocked by hook.",
            },
        )

        with self.register_hook("before_edit_page", json_hook_func):
            response = self.client.get(
                reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)),
                headers={"Accept": "application/json"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "purple"})

    def test_before_edit_page_hook_post(self):
        def hook_func(request, page):
            self.assertIsInstance(request, HttpRequest)
            self.assertEqual(page.id, self.child_page.id)

            return HttpResponse("Overridden!")

        with self.register_hook("before_edit_page", hook_func):
            post_data = {
                "title": "I've been edited!",
                "content": "Some content",
                "slug": "hello-world-new",
                "action-publish": "Publish",
            }
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)),
                post_data,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"Overridden!")

        # page should not be edited
        self.assertEqual(Page.objects.get(id=self.child_page.id).title, "Hello world!")

    def test_before_edit_page_hook_post_with_json_response(self):
        def non_json_hook_func(request, page):
            self.assertIsInstance(request, HttpRequest)
            self.assertEqual(page.id, self.child_page.id)

            return HttpResponse("Overridden!")

        def json_hook_func(request, page):
            self.assertIsInstance(request, HttpRequest)
            self.assertEqual(page.id, self.child_page.id)

            return JsonResponse({"status": "purple"})

        with self.register_hook("before_edit_page", non_json_hook_func):
            post_data = {
                "title": "I've been edited!",
                "content": "Some content",
                "slug": "hello-world-new",
            }
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)),
                post_data,
                headers={"Accept": "application/json"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "error_code": "blocked_by_hook",
                "error_message": "Request to edit page was blocked by hook.",
            },
        )

        # page should not be edited
        self.assertEqual(
            Page.objects.get(id=self.child_page.id)
            .get_latest_revision_as_object()
            .title,
            "Hello world!",
        )

        with self.register_hook("before_edit_page", json_hook_func):
            post_data = {
                "title": "I've been edited!",
                "content": "Some content",
                "slug": "hello-world-new",
            }
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)),
                post_data,
                headers={"Accept": "application/json"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "purple"})

        # page should not be edited
        self.assertEqual(
            Page.objects.get(id=self.child_page.id)
            .get_latest_revision_as_object()
            .title,
            "Hello world!",
        )

    def test_after_edit_page_hook(self):
        def hook_func(request, page):
            self.assertIsInstance(request, HttpRequest)
            self.assertEqual(page.id, self.child_page.id)

            return HttpResponse("Overridden!")

        with self.register_hook("after_edit_page", hook_func):
            post_data = {
                "title": "I've been edited!",
                "content": "Some content",
                "slug": "hello-world-new",
                "action-publish": "Publish",
            }
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)),
                post_data,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"Overridden!")

        # page should be edited
        self.assertEqual(
            Page.objects.get(id=self.child_page.id).title, "I've been edited!"
        )

    def test_after_edit_page_hook_with_json_response(self):
        def non_json_hook_func(request, page):
            self.assertIsInstance(request, HttpRequest)
            self.assertEqual(page.id, self.child_page.id)

            return HttpResponse("Overridden!")

        def json_hook_func(request, page):
            self.assertIsInstance(request, HttpRequest)
            self.assertEqual(page.id, self.child_page.id)

            return JsonResponse({"status": "purple"})

        with self.register_hook("after_edit_page", non_json_hook_func):
            post_data = {
                "title": "I've been edited!",
                "content": "Some content",
                "slug": "hello-world-new",
            }
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)),
                post_data,
                headers={"Accept": "application/json"},
            )

        self.assertEqual(response.status_code, 200)
        # hook response is ignored, since it's not a JSON response
        self.assertEqual(response.json()["success"], True)

        # page should be edited
        self.assertEqual(
            Page.objects.get(id=self.child_page.id)
            .get_latest_revision_as_object()
            .title,
            "I've been edited!",
        )

        with self.register_hook("after_edit_page", json_hook_func):
            post_data = {
                "title": "I've been edited again!",
                "content": "Some content",
                "slug": "hello-world-new",
            }
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)),
                post_data,
                headers={"Accept": "application/json"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "purple"})

        # page should be edited
        self.assertEqual(
            Page.objects.get(id=self.child_page.id)
            .get_latest_revision_as_object()
            .title,
            "I've been edited again!",
        )

    def test_after_publish_page(self):
        def hook_func(request, page):
            self.assertIsInstance(request, HttpRequest)
            self.assertEqual(page.id, self.child_page.id)

            return HttpResponse("Overridden!")

        with self.register_hook("after_publish_page", hook_func):
            post_data = {
                "title": "I've been edited!",
                "content": "Some content",
                "slug": "hello-world-new",
                "action-publish": "Publish",
            }
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)),
                post_data,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"Overridden!")
        self.child_page.refresh_from_db()
        self.assertEqual(self.child_page.status_string, _("live"))

    def test_before_publish_page(self):
        def hook_func(request, page):
            self.assertIsInstance(request, HttpRequest)
            self.assertEqual(page.id, self.child_page.id)

            return HttpResponse("Overridden!")

        with self.register_hook("before_publish_page", hook_func):
            post_data = {
                "title": "I've been edited!",
                "content": "Some content",
                "slug": "hello-world-new",
                "action-publish": "Publish",
            }
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)),
                post_data,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"Overridden!")
        self.child_page.refresh_from_db()
        self.assertEqual(self.child_page.status_string, _("live + draft"))

    def test_override_default_action_menu_item(self):
        def hook_func(menu_items, request, context):
            for index, item in enumerate(menu_items):
                if item.name == "action-publish":
                    # move to top of list
                    menu_items.pop(index)
                    menu_items.insert(0, item)
                    break

        with self.register_hook("construct_page_action_menu", hook_func):
            response = self.client.get(
                reverse("wagtailadmin_pages:edit", args=(self.single_event_page.id,))
            )

        soup = self.get_soup(response.content)

        # save button should be inside "More actions" toggle.
        save_button = soup.select_one(".w-dropdown__content .action-save")
        self.assertIsNotNone(save_button)
        # publish button should be directly inside "Dropdown button".
        publish_button = soup.select_one('.w-dropdown-button > [name="action-publish"]')
        self.assertIsNotNone(publish_button)

    def test_override_publish_action_menu_item_label(self):
        class CustomPublishMenuItem(PublishMenuItem):
            label = "Foobar"

        def hook_func(menu_items, request, context):
            menu_items[:] = [
                CustomPublishMenuItem() if item.name == "action-publish" else item
                for item in menu_items
            ]

        with self.register_hook("construct_page_action_menu", hook_func):
            response = self.client.get(
                reverse("wagtailadmin_pages:edit", args=(self.single_event_page.id,))
            )

        # publish button should have another label
        self.assertContains(response, "Foobar")

    def test_edit_alias_page(self):
        alias_page = self.event_page.create_alias(update_slug="new-event-page")
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=[alias_page.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/html; charset=utf-8")

        # Should still have status in the sidebar
        self.assertContains(response, 'id="status-sidebar-live"')

        # Check the edit_alias.html template was used instead
        self.assertTemplateUsed(response, "wagtailadmin/pages/edit_alias.html")
        original_page_edit_url = reverse(
            "wagtailadmin_pages:edit", args=[self.event_page.id]
        )
        self.assertContains(
            response,
            f'<a class="button button-secondary" href="{original_page_edit_url}">Edit original page</a>',
            html=True,
        )

    def test_edit_alias_page_from_draft_page(self):
        # Ensure we have at least one revision. This is what happens when creating
        # a page via the admin. It is stored as latest_revision
        self.unpublished_page.save_revision()
        alias_page = self.unpublished_page.create_alias(update_slug="an-alias-page")
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=[alias_page.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/html; charset=utf-8")

        self.assertNotContains(response, 'id="status-sidebar-live"')

        # Check the edit_alias.html template was used instead
        self.assertTemplateUsed(response, "wagtailadmin/pages/edit_alias.html")
        original_page_edit_url = reverse(
            "wagtailadmin_pages:edit", args=[self.unpublished_page.id]
        )
        self.assertContains(
            response,
            f'<a class="button button-secondary" href="{original_page_edit_url}">Edit original page</a>',
            html=True,
        )

    def test_post_edit_alias_page(self):
        alias_page = self.child_page.create_alias(update_slug="new-child-page")

        # Tests simple editing
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=[alias_page.id]), post_data
        )

        self.assertEqual(response.status_code, 405)

    def test_edit_after_change_language_code(self):
        """
        Verify that changing LANGUAGE_CODE with no corresponding database change does not break editing
        """
        # Add a draft revision
        self.child_page.title = "Hello world updated"
        self.child_page.save_revision()

        # Hack the Locale model to simulate a page tree that was created with LANGUAGE_CODE = 'de'
        # (which is not a valid content language under the current configuration)
        Locale.objects.update(language_code="de")

        # Tests that the edit page loads
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,))
        )
        self.assertEqual(response.status_code, 200)

        # Tests simple editing
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)), post_data
        )

        # Should be redirected to edit page
        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=(self.child_page.id,))
        )

    def test_edit_after_change_language_code_without_revisions(self):
        """
        Verify that changing LANGUAGE_CODE with no corresponding database change does not break editing
        """
        # Hack the Locale model to simulate a page tree that was created with LANGUAGE_CODE = 'de'
        # (which is not a valid content language under the current configuration)
        Locale.objects.update(language_code="de")

        Revision.page_revisions.filter(object_id=self.child_page.id).delete()

        # Tests that the edit page loads
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,))
        )
        self.assertEqual(response.status_code, 200)

        # Tests simple editing
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)), post_data
        )

        # Should be redirected to edit page
        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=(self.child_page.id,))
        )

    def test_page_edit_num_queries_as_superuser(self):
        # Warm up cache so that result is the same when running this test in isolation
        # as when running it within the full test suite
        self.client.get(reverse("wagtailadmin_pages:edit", args=(self.event_page.id,)))

        with self.assertNumQueries(37):
            self.client.get(
                reverse("wagtailadmin_pages:edit", args=(self.event_page.id,))
            )

    def test_page_edit_num_queries_as_editor(self):
        editor = self.create_user("editor", password="password")
        editor.groups.add(Group.objects.get(name="Editors"))
        self.login(username="editor")

        # Warm up the cache as above.
        self.client.get(reverse("wagtailadmin_pages:edit", args=(self.event_page.id,)))

        with self.assertNumQueries(42):
            self.client.get(
                reverse("wagtailadmin_pages:edit", args=(self.event_page.id,))
            )


class TestPageEditReordering(WagtailTestUtils, TestCase):
    def setUp(self):
        # Find root page
        self.root_page = Page.objects.get(id=2)

        # Add event page
        self.event_page = EventPage(
            title="Event page",
            slug="event-page",
            location="the moon",
            audience="public",
            cost="free",
            date_from="2001-01-01",
        )
        self.event_page.carousel_items = [
            EventPageCarouselItem(caption="1234567", sort_order=1),
            EventPageCarouselItem(caption="7654321", sort_order=2),
            EventPageCarouselItem(caption="abcdefg", sort_order=3),
        ]
        self.root_page.add_child(instance=self.event_page)

        # Login
        self.user = self.login()

    def check_order(self, response, expected_order):
        inline_panel = response.context["edit_handler"].children[0].children[9]
        order = [child.form.instance.caption for child in inline_panel.children]
        self.assertEqual(order, expected_order)

    def test_order(self):
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.event_page.id,))
        )

        self.assertEqual(response.status_code, 200)
        self.check_order(response, ["1234567", "7654321", "abcdefg"])

    def test_reorder(self):
        post_data = {
            "title": "Event page",
            "slug": "event-page",
            "date_from": "01/01/2014",
            "cost": "$10",
            "audience": "public",
            "location": "somewhere",
            "related_links-INITIAL_FORMS": 0,
            "related_links-MAX_NUM_FORMS": 1000,
            "related_links-TOTAL_FORMS": 0,
            "speakers-INITIAL_FORMS": 0,
            "speakers-MAX_NUM_FORMS": 1000,
            "speakers-TOTAL_FORMS": 0,
            "head_counts-INITIAL_FORMS": 0,
            "head_counts-MAX_NUM_FORMS": 1000,
            "head_counts-TOTAL_FORMS": 0,
            "carousel_items-INITIAL_FORMS": 3,
            "carousel_items-MAX_NUM_FORMS": 1000,
            "carousel_items-TOTAL_FORMS": 3,
            "carousel_items-0-id": self.event_page.carousel_items.all()[0].id,
            "carousel_items-0-caption": self.event_page.carousel_items.all()[0].caption,
            "carousel_items-0-ORDER": 2,
            "carousel_items-1-id": self.event_page.carousel_items.all()[1].id,
            "carousel_items-1-caption": self.event_page.carousel_items.all()[1].caption,
            "carousel_items-1-ORDER": 3,
            "carousel_items-2-id": self.event_page.carousel_items.all()[2].id,
            "carousel_items-2-caption": self.event_page.carousel_items.all()[2].caption,
            "carousel_items-2-ORDER": 1,
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.event_page.id,)), post_data
        )

        # Should be redirected back to same page
        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=(self.event_page.id,))
        )

        # Check order
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.event_page.id,))
        )

        self.assertEqual(response.status_code, 200)
        self.check_order(response, ["abcdefg", "1234567", "7654321"])

    def test_reorder_with_validation_error(self):
        post_data = {
            "title": "",  # Validation error
            "slug": "event-page",
            "date_from": "01/01/2014",
            "cost": "$10",
            "audience": "public",
            "location": "somewhere",
            "related_links-INITIAL_FORMS": 0,
            "related_links-MAX_NUM_FORMS": 1000,
            "related_links-TOTAL_FORMS": 0,
            "speakers-INITIAL_FORMS": 0,
            "speakers-MAX_NUM_FORMS": 1000,
            "speakers-TOTAL_FORMS": 0,
            "head_counts-INITIAL_FORMS": 0,
            "head_counts-MAX_NUM_FORMS": 1000,
            "head_counts-TOTAL_FORMS": 0,
            "carousel_items-INITIAL_FORMS": 3,
            "carousel_items-MAX_NUM_FORMS": 1000,
            "carousel_items-TOTAL_FORMS": 3,
            "carousel_items-0-id": self.event_page.carousel_items.all()[0].id,
            "carousel_items-0-caption": self.event_page.carousel_items.all()[0].caption,
            "carousel_items-0-ORDER": 2,
            "carousel_items-1-id": self.event_page.carousel_items.all()[1].id,
            "carousel_items-1-caption": self.event_page.carousel_items.all()[1].caption,
            "carousel_items-1-ORDER": 3,
            "carousel_items-2-id": self.event_page.carousel_items.all()[2].id,
            "carousel_items-2-caption": self.event_page.carousel_items.all()[2].caption,
            "carousel_items-2-ORDER": 1,
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.event_page.id,)), post_data
        )

        self.assertEqual(response.status_code, 200)
        self.check_order(response, ["abcdefg", "1234567", "7654321"])


class TestIssue197(WagtailTestUtils, TestCase):
    def test_issue_197(self):
        # Find root page
        self.root_page = Page.objects.get(id=2)

        # Create a tagged page with no tags
        self.tagged_page = self.root_page.add_child(
            instance=TaggedPage(
                title="Tagged page",
                slug="tagged-page",
                live=False,
            )
        )

        # Login
        self.user = self.login()

        # Add some tags and publish using edit view
        post_data = {
            "title": "Tagged page",
            "slug": "tagged-page",
            "tags": "hello, world",
            "action-publish": "Publish",
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.tagged_page.id,)), post_data
        )

        # Should be redirected to explorer
        self.assertRedirects(
            response, reverse("wagtailadmin_explore", args=(self.root_page.id,))
        )

        # Check that both tags are in the pages tag set
        page = TaggedPage.objects.get(id=self.tagged_page.id)
        self.assertIn("hello", page.tags.slugs())
        self.assertIn("world", page.tags.slugs())


class TestChildRelationsOnSuperclass(WagtailTestUtils, TestCase):
    # In our test models we define AdvertPlacement as a child relation on the Page model.
    # Here we check that this behaves correctly when exposed on the edit form of a Page
    # subclass (StandardIndex here).
    fixtures = ["test.json"]

    def setUp(self):
        # Find root page
        self.root_page = Page.objects.get(id=2)
        self.test_advert = Advert.objects.get(id=1)

        # Add child page
        self.index_page = StandardIndex(
            title="My lovely index",
            slug="my-lovely-index",
            advert_placements=[AdvertPlacement(advert=self.test_advert)],
        )
        self.root_page.add_child(instance=self.index_page)

        # Login
        self.login()

    def test_get_create_form(self):
        response = self.client.get(
            reverse(
                "wagtailadmin_pages:add",
                args=("tests", "standardindex", self.root_page.id),
            )
        )
        self.assertEqual(response.status_code, 200)
        # Response should include an advert_placements formset labelled Adverts
        self.assertContains(response, "Adverts")
        self.assertContains(response, "id_advert_placements-TOTAL_FORMS")
        # Expecting the add-button
        self.assertContains(response, "Add advert")

    def test_post_create_form(self):
        post_data = {
            "title": "New index!",
            "slug": "new-index",
            "advert_placements-TOTAL_FORMS": "1",
            "advert_placements-INITIAL_FORMS": "0",
            "advert_placements-MAX_NUM_FORMS": "1000",
            "advert_placements-0-advert": "1",
            "advert_placements-0-colour": "yellow",
            "advert_placements-0-id": "",
        }
        response = self.client.post(
            reverse(
                "wagtailadmin_pages:add",
                args=("tests", "standardindex", self.root_page.id),
            ),
            post_data,
        )

        # Find the page and check it
        page = Page.objects.get(
            path__startswith=self.root_page.path, slug="new-index"
        ).specific

        # Should be redirected to edit page
        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=(page.id,))
        )

        self.assertEqual(page.advert_placements.count(), 1)
        self.assertEqual(page.advert_placements.first().advert.text, "test_advert")

    def test_post_create_form_with_validation_error_in_formset(self):
        post_data = {
            "title": "New index!",
            "slug": "new-index",
            "advert_placements-TOTAL_FORMS": "1",
            "advert_placements-INITIAL_FORMS": "0",
            "advert_placements-MAX_NUM_FORMS": "1000",
            "advert_placements-0-advert": "1",
            "advert_placements-0-colour": "",  # should fail as colour is a required field
            "advert_placements-0-id": "",
            "action-publish": "Publish",
        }
        response = self.client.post(
            reverse(
                "wagtailadmin_pages:add",
                args=("tests", "standardindex", self.root_page.id),
            ),
            post_data,
        )

        # Should remain on the edit page with a validation error
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required.")
        # form should be marked as having unsaved changes
        self.assertContains(response, 'data-w-unsaved-force-value="true"')

    def test_get_edit_form(self):
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.index_page.id,))
        )
        self.assertEqual(response.status_code, 200)

        # Response should include an advert_placements formset labelled Adverts
        self.assertContains(response, "Adverts")
        self.assertContains(response, "id_advert_placements-TOTAL_FORMS")
        # the formset should be populated with an existing form (with a snippet chooser widget)
        self.assertContains(
            response,
            '<div class="chooser__title" data-chooser-title id="id_advert_placements-0-advert-title">test_advert</div>',
        )
        self.assertContains(
            response,
            '<input type="hidden" name="advert_placements-0-advert" value="1" id="id_advert_placements-0-advert">',
            html=True,
        )
        # Expecting the add-button
        self.assertContains(response, "Add advert")

    def test_post_edit_form(self):
        post_data = {
            "title": "My lovely index",
            "slug": "my-lovely-index",
            "advert_placements-TOTAL_FORMS": "2",
            "advert_placements-INITIAL_FORMS": "1",
            "advert_placements-MAX_NUM_FORMS": "1000",
            "advert_placements-0-advert": "1",
            "advert_placements-0-colour": "yellow",
            "advert_placements-0-id": self.index_page.advert_placements.first().id,
            "advert_placements-1-advert": "1",
            "advert_placements-1-colour": "purple",
            "advert_placements-1-id": "",
            "action-publish": "Publish",
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.index_page.id,)), post_data
        )

        # Should be redirected to explorer
        self.assertRedirects(
            response, reverse("wagtailadmin_explore", args=(self.root_page.id,))
        )

        # Find the page and check it
        page = Page.objects.get(id=self.index_page.id).specific
        self.assertEqual(page.advert_placements.count(), 2)
        self.assertEqual(page.advert_placements.all()[0].advert.text, "test_advert")
        self.assertEqual(page.advert_placements.all()[1].advert.text, "test_advert")

    def test_post_edit_form_with_validation_error_in_formset(self):
        post_data = {
            "title": "My lovely index",
            "slug": "my-lovely-index",
            "advert_placements-TOTAL_FORMS": "1",
            "advert_placements-INITIAL_FORMS": "1",
            "advert_placements-MAX_NUM_FORMS": "1000",
            "advert_placements-0-advert": "1",
            "advert_placements-0-colour": "",
            "advert_placements-0-id": self.index_page.advert_placements.first().id,
            "action-publish": "Publish",
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.index_page.id,)), post_data
        )

        # Should remain on the edit page with a validation error
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required.")
        # form should be marked as having unsaved changes
        self.assertContains(response, 'data-w-unsaved-force-value="true"')


class TestIssue2492(WagtailTestUtils, TestCase):
    """
    The publication submission message generation was performed using
    the Page class, as opposed to the specific_class for that Page.
    This test ensures that the specific_class url method is called
    when the 'view live' message button is created.
    """

    def setUp(self):
        self.root_page = Page.objects.get(id=2)
        child_page = SingleEventPage(
            title="Test Event",
            slug="test-event",
            location="test location",
            cost="10",
            date_from=datetime.datetime.now(),
            audience=EVENT_AUDIENCE_CHOICES[0][0],
        )
        self.root_page.add_child(instance=child_page)
        child_page.save_revision().publish()
        self.child_page = SingleEventPage.objects.get(id=child_page.id)
        self.user = self.login()

    def test_page_edit_post_publish_url(self):
        post_data = {
            "action-publish": "Publish",
            "title": self.child_page.title,
            "date_from": self.child_page.date_from,
            "slug": self.child_page.slug,
            "audience": self.child_page.audience,
            "location": self.child_page.location,
            "cost": self.child_page.cost,
            "carousel_items-TOTAL_FORMS": 0,
            "carousel_items-INITIAL_FORMS": 0,
            "carousel_items-MIN_NUM_FORMS": 0,
            "carousel_items-MAX_NUM_FORMS": 0,
            "speakers-TOTAL_FORMS": 0,
            "speakers-INITIAL_FORMS": 0,
            "speakers-MIN_NUM_FORMS": 0,
            "speakers-MAX_NUM_FORMS": 0,
            "related_links-TOTAL_FORMS": 0,
            "related_links-INITIAL_FORMS": 0,
            "related_links-MIN_NUM_FORMS": 0,
            "related_links-MAX_NUM_FORMS": 0,
            "head_counts-TOTAL_FORMS": 0,
            "head_counts-INITIAL_FORMS": 0,
            "head_counts-MIN_NUM_FORMS": 0,
            "head_counts-MAX_NUM_FORMS": 0,
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.child_page.id,)),
            post_data,
            follow=True,
        )

        # Grab a fresh copy's URL
        new_url = SingleEventPage.objects.get(id=self.child_page.id).url

        # The "View Live" button should have the custom URL.
        for message in response.context["messages"]:
            self.assertIn(f'"{new_url}"', message.message)
            break


class TestIssue3982(WagtailTestUtils, TestCase):
    """
    Pages that are not associated with a site, and thus do not have a live URL,
    should not display a "View live" link in the flash message after being
    edited.
    """

    def setUp(self):
        super().setUp()
        self.login()

    def _create_page(self, parent):
        response = self.client.post(
            reverse("wagtailadmin_pages:add", args=("tests", "simplepage", parent.pk)),
            {
                "title": "Hello, world!",
                "content": "Some content",
                "slug": "hello-world",
                "action-publish": "publish",
            },
            follow=True,
        )
        self.assertRedirects(
            response, reverse("wagtailadmin_explore", args=(parent.pk,))
        )
        page = SimplePage.objects.get()
        self.assertTrue(page.live)
        return response, page

    def test_create_accessible(self):
        """
        Create a page under the site root, check the flash message has a valid
        "View live" button.
        """
        response, page = self._create_page(Page.objects.get(pk=2))
        self.assertIsNotNone(page.url)
        self.assertTrue(
            any(
                "View live" in message.message and page.url in message.message
                for message in response.context["messages"]
            )
        )

    def test_create_inaccessible(self):
        """
        Create a page outside of the site root, check the flash message does
        not have a "View live" button.
        """
        response, page = self._create_page(Page.objects.get(pk=1))
        self.assertIsNone(page.url)
        self.assertFalse(
            any(
                "View live" in message.message
                for message in response.context["messages"]
            )
        )

    def _edit_page(self, parent):
        page = parent.add_child(
            instance=SimplePage(title="Hello, world!", content="Some content")
        )
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(page.pk,)),
            {
                "title": "Hello, world!",
                "content": "Some content",
                "slug": "hello-world",
                "action-publish": "publish",
            },
            follow=True,
        )
        self.assertRedirects(
            response, reverse("wagtailadmin_explore", args=(parent.pk,))
        )
        page = SimplePage.objects.get(pk=page.pk)
        self.assertTrue(page.live)
        return response, page

    def test_edit_accessible(self):
        """
        Edit a page under the site root, check the flash message has a valid
        "View live" button.
        """
        response, page = self._edit_page(Page.objects.get(pk=2))
        self.assertIsNotNone(page.url)
        self.assertTrue(
            any(
                "View live" in message.message and page.url in message.message
                for message in response.context["messages"]
            )
        )

    def test_edit_inaccessible(self):
        """
        Edit a page outside of the site root, check the flash message does
        not have a "View live" button.
        """
        response, page = self._edit_page(Page.objects.get(pk=1))
        self.assertIsNone(page.url)
        self.assertFalse(
            any(
                "View live" in message.message
                for message in response.context["messages"]
            )
        )


class TestParentalM2M(WagtailTestUtils, TestCase):
    fixtures = ["test.json"]

    def setUp(self):
        self.events_index = Page.objects.get(url_path="/home/events/")
        self.christmas_page = Page.objects.get(url_path="/home/events/christmas/")
        self.user = self.login()
        self.holiday_category = EventCategory.objects.create(name="Holiday")
        self.men_with_beards_category = EventCategory.objects.create(
            name="Men with beards"
        )

    def test_create_and_save(self):
        post_data = {
            "title": "Presidents' Day",
            "date_from": "2017-02-20",
            "slug": "presidents-day",
            "audience": "public",
            "location": "America",
            "cost": "$1",
            "carousel_items-TOTAL_FORMS": 0,
            "carousel_items-INITIAL_FORMS": 0,
            "carousel_items-MIN_NUM_FORMS": 0,
            "carousel_items-MAX_NUM_FORMS": 0,
            "speakers-TOTAL_FORMS": 0,
            "speakers-INITIAL_FORMS": 0,
            "speakers-MIN_NUM_FORMS": 0,
            "speakers-MAX_NUM_FORMS": 0,
            "related_links-TOTAL_FORMS": 0,
            "related_links-INITIAL_FORMS": 0,
            "related_links-MIN_NUM_FORMS": 0,
            "related_links-MAX_NUM_FORMS": 0,
            "head_counts-TOTAL_FORMS": 0,
            "head_counts-INITIAL_FORMS": 0,
            "head_counts-MIN_NUM_FORMS": 0,
            "head_counts-MAX_NUM_FORMS": 0,
            "categories": [self.holiday_category.id, self.men_with_beards_category.id],
        }
        response = self.client.post(
            reverse(
                "wagtailadmin_pages:add",
                args=("tests", "eventpage", self.events_index.id),
            ),
            post_data,
        )
        created_page = EventPage.objects.get(url_path="/home/events/presidents-day/")
        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=(created_page.id,))
        )
        created_revision = created_page.get_latest_revision_as_object()

        self.assertIn(self.holiday_category, created_revision.categories.all())
        self.assertIn(self.men_with_beards_category, created_revision.categories.all())

    def test_create_and_publish(self):
        post_data = {
            "action-publish": "Publish",
            "title": "Presidents' Day",
            "date_from": "2017-02-20",
            "slug": "presidents-day",
            "audience": "public",
            "location": "America",
            "cost": "$1",
            "carousel_items-TOTAL_FORMS": 0,
            "carousel_items-INITIAL_FORMS": 0,
            "carousel_items-MIN_NUM_FORMS": 0,
            "carousel_items-MAX_NUM_FORMS": 0,
            "speakers-TOTAL_FORMS": 0,
            "speakers-INITIAL_FORMS": 0,
            "speakers-MIN_NUM_FORMS": 0,
            "speakers-MAX_NUM_FORMS": 0,
            "related_links-TOTAL_FORMS": 0,
            "related_links-INITIAL_FORMS": 0,
            "related_links-MIN_NUM_FORMS": 0,
            "related_links-MAX_NUM_FORMS": 0,
            "head_counts-TOTAL_FORMS": 0,
            "head_counts-INITIAL_FORMS": 0,
            "head_counts-MIN_NUM_FORMS": 0,
            "head_counts-MAX_NUM_FORMS": 0,
            "categories": [self.holiday_category.id, self.men_with_beards_category.id],
        }
        response = self.client.post(
            reverse(
                "wagtailadmin_pages:add",
                args=("tests", "eventpage", self.events_index.id),
            ),
            post_data,
        )
        self.assertRedirects(
            response, reverse("wagtailadmin_explore", args=(self.events_index.id,))
        )

        created_page = EventPage.objects.get(url_path="/home/events/presidents-day/")
        self.assertIn(self.holiday_category, created_page.categories.all())
        self.assertIn(self.men_with_beards_category, created_page.categories.all())

    def test_edit_and_save(self):
        post_data = {
            "title": "Christmas",
            "date_from": "2017-12-25",
            "slug": "christmas",
            "audience": "public",
            "location": "The North Pole",
            "cost": "Free",
            "carousel_items-TOTAL_FORMS": 0,
            "carousel_items-INITIAL_FORMS": 0,
            "carousel_items-MIN_NUM_FORMS": 0,
            "carousel_items-MAX_NUM_FORMS": 0,
            "speakers-TOTAL_FORMS": 0,
            "speakers-INITIAL_FORMS": 0,
            "speakers-MIN_NUM_FORMS": 0,
            "speakers-MAX_NUM_FORMS": 0,
            "related_links-TOTAL_FORMS": 0,
            "related_links-INITIAL_FORMS": 0,
            "related_links-MIN_NUM_FORMS": 0,
            "related_links-MAX_NUM_FORMS": 0,
            "head_counts-TOTAL_FORMS": 0,
            "head_counts-INITIAL_FORMS": 0,
            "head_counts-MIN_NUM_FORMS": 0,
            "head_counts-MAX_NUM_FORMS": 0,
            "categories": [self.holiday_category.id, self.men_with_beards_category.id],
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.christmas_page.id,)),
            post_data,
        )
        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=(self.christmas_page.id,))
        )
        updated_page = EventPage.objects.get(id=self.christmas_page.id)
        created_revision = updated_page.get_latest_revision_as_object()

        self.assertIn(self.holiday_category, created_revision.categories.all())
        self.assertIn(self.men_with_beards_category, created_revision.categories.all())

        # no change to live page record yet
        self.assertEqual(0, updated_page.categories.count())

    def test_edit_and_publish(self):
        post_data = {
            "action-publish": "Publish",
            "title": "Christmas",
            "date_from": "2017-12-25",
            "slug": "christmas",
            "audience": "public",
            "location": "The North Pole",
            "cost": "Free",
            "carousel_items-TOTAL_FORMS": 0,
            "carousel_items-INITIAL_FORMS": 0,
            "carousel_items-MIN_NUM_FORMS": 0,
            "carousel_items-MAX_NUM_FORMS": 0,
            "speakers-TOTAL_FORMS": 0,
            "speakers-INITIAL_FORMS": 0,
            "speakers-MIN_NUM_FORMS": 0,
            "speakers-MAX_NUM_FORMS": 0,
            "related_links-TOTAL_FORMS": 0,
            "related_links-INITIAL_FORMS": 0,
            "related_links-MIN_NUM_FORMS": 0,
            "related_links-MAX_NUM_FORMS": 0,
            "head_counts-TOTAL_FORMS": 0,
            "head_counts-INITIAL_FORMS": 0,
            "head_counts-MIN_NUM_FORMS": 0,
            "head_counts-MAX_NUM_FORMS": 0,
            "categories": [self.holiday_category.id, self.men_with_beards_category.id],
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.christmas_page.id,)),
            post_data,
        )
        self.assertRedirects(
            response, reverse("wagtailadmin_explore", args=(self.events_index.id,))
        )
        updated_page = EventPage.objects.get(id=self.christmas_page.id)
        self.assertEqual(2, updated_page.categories.count())
        self.assertIn(self.holiday_category, updated_page.categories.all())
        self.assertIn(self.men_with_beards_category, updated_page.categories.all())


class TestValidationerror_messages(WagtailTestUtils, TestCase):
    fixtures = ["test.json"]

    def setUp(self):
        self.events_index = Page.objects.get(url_path="/home/events/")
        self.christmas_page = Page.objects.get(url_path="/home/events/christmas/")
        self.user = self.login()

    def test_field_error(self):
        """Field errors should be shown against the relevant fields, not in the header message"""
        post_data = {
            "title": "",
            "date_from": "2017-12-25",
            "slug": "christmas",
            "audience": "public",
            "location": "The North Pole",
            "cost": "Free",
            "carousel_items-TOTAL_FORMS": 0,
            "carousel_items-INITIAL_FORMS": 0,
            "carousel_items-MIN_NUM_FORMS": 0,
            "carousel_items-MAX_NUM_FORMS": 0,
            "speakers-TOTAL_FORMS": 0,
            "speakers-INITIAL_FORMS": 0,
            "speakers-MIN_NUM_FORMS": 0,
            "speakers-MAX_NUM_FORMS": 0,
            "related_links-TOTAL_FORMS": 0,
            "related_links-INITIAL_FORMS": 0,
            "related_links-MIN_NUM_FORMS": 0,
            "related_links-MAX_NUM_FORMS": 0,
            "head_counts-TOTAL_FORMS": 0,
            "head_counts-INITIAL_FORMS": 0,
            "head_counts-MIN_NUM_FORMS": 0,
            "head_counts-MAX_NUM_FORMS": 0,
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.christmas_page.id,)),
            post_data,
        )
        self.assertEqual(response.status_code, 200)

        soup = self.get_soup(response.content)

        header_messages = soup.css.select(".messages[role='status'] ul > li")

        # the top level message should indicate that the page could not be saved
        self.assertEqual(len(header_messages), 1)
        message = header_messages[0]
        self.assertIn(
            "The page could not be saved due to validation errors", message.get_text()
        )

        # the top level message should provide a go to error button
        buttons = message.find_all("button")
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].attrs["data-controller"], "w-count w-focus")
        self.assertIn("Go to the first error", buttons[0].get_text())

        # the error should only appear once: against the field, not in the header message
        error_messages = soup.css.select(".error-message")
        self.assertEqual(len(error_messages), 1)
        error_message = error_messages[0]
        self.assertEqual(
            error_message.parent["id"], "panel-child-content-child-title-errors"
        )
        self.assertIn("This field is required", error_message.get_text())

    def test_field_error_with_json_response(self):
        post_data = {
            "title": "",
            "date_from": "2017-12-25",
            "slug": "christmas",
            "audience": "public",
            "location": "The North Pole",
            "cost": "Free",
            "carousel_items-TOTAL_FORMS": 0,
            "carousel_items-INITIAL_FORMS": 0,
            "carousel_items-MIN_NUM_FORMS": 0,
            "carousel_items-MAX_NUM_FORMS": 0,
            "speakers-TOTAL_FORMS": 0,
            "speakers-INITIAL_FORMS": 0,
            "speakers-MIN_NUM_FORMS": 0,
            "speakers-MAX_NUM_FORMS": 0,
            "related_links-TOTAL_FORMS": 0,
            "related_links-INITIAL_FORMS": 0,
            "related_links-MIN_NUM_FORMS": 0,
            "related_links-MAX_NUM_FORMS": 0,
            "head_counts-TOTAL_FORMS": 0,
            "head_counts-INITIAL_FORMS": 0,
            "head_counts-MIN_NUM_FORMS": 0,
            "head_counts-MAX_NUM_FORMS": 0,
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.christmas_page.id,)),
            post_data,
            headers={"Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "error_code": "validation_error",
                "error_message": "There are validation errors, click save to highlight them.",
            },
        )

    def test_non_field_error(self):
        """Non-field errors should be shown in the header message"""
        post_data = {
            "title": "Christmas",
            "date_from": "2017-12-25",
            "date_to": "2017-12-24",
            "slug": "christmas",
            "audience": "public",
            "location": "The North Pole",
            "cost": "Free",
            "carousel_items-TOTAL_FORMS": 0,
            "carousel_items-INITIAL_FORMS": 0,
            "carousel_items-MIN_NUM_FORMS": 0,
            "carousel_items-MAX_NUM_FORMS": 0,
            "speakers-TOTAL_FORMS": 0,
            "speakers-INITIAL_FORMS": 0,
            "speakers-MIN_NUM_FORMS": 0,
            "speakers-MAX_NUM_FORMS": 0,
            "related_links-TOTAL_FORMS": 0,
            "related_links-INITIAL_FORMS": 0,
            "related_links-MIN_NUM_FORMS": 0,
            "related_links-MAX_NUM_FORMS": 0,
            "head_counts-TOTAL_FORMS": 0,
            "head_counts-INITIAL_FORMS": 0,
            "head_counts-MIN_NUM_FORMS": 0,
            "head_counts-MAX_NUM_FORMS": 0,
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.christmas_page.id,)),
            post_data,
        )
        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response, "The page could not be saved due to validation errors"
        )
        self.assertContains(
            response, "<li>The end date must be after the start date</li>", count=1
        )

    def test_field_and_non_field_error(self):
        """
        If both field and non-field errors exist, all errors should be shown in the header message
        with appropriate context to identify the field; and field errors should also be shown
        against the relevant fields.
        """
        post_data = {
            "title": "",
            "date_from": "2017-12-25",
            "date_to": "2017-12-24",
            "slug": "christmas",
            "audience": "public",
            "location": "The North Pole",
            "cost": "Free",
            "carousel_items-TOTAL_FORMS": 0,
            "carousel_items-INITIAL_FORMS": 0,
            "carousel_items-MIN_NUM_FORMS": 0,
            "carousel_items-MAX_NUM_FORMS": 0,
            "speakers-TOTAL_FORMS": 0,
            "speakers-INITIAL_FORMS": 0,
            "speakers-MIN_NUM_FORMS": 0,
            "speakers-MAX_NUM_FORMS": 0,
            "related_links-TOTAL_FORMS": 0,
            "related_links-INITIAL_FORMS": 0,
            "related_links-MIN_NUM_FORMS": 0,
            "related_links-MAX_NUM_FORMS": 0,
            "head_counts-TOTAL_FORMS": 0,
            "head_counts-INITIAL_FORMS": 0,
            "head_counts-MIN_NUM_FORMS": 0,
            "head_counts-MAX_NUM_FORMS": 0,
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.christmas_page.id,)),
            post_data,
        )
        self.assertEqual(response.status_code, 200)

        soup = self.get_soup(response.content)

        # there should be top level messages should indicate that the page could not be saved alongside other messages
        header_messages = soup.css.select(".messages[role='status'] ul > li")
        self.assertEqual(len(header_messages), 3)

        # the first header message should indicate that the page could not be saved & contain a go to error button
        self.assertIn(
            "The page could not be saved due to validation errors",
            header_messages[0].get_text(),
        )
        buttons = header_messages[0].find_all("button")
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].attrs["data-controller"], "w-count w-focus")
        self.assertIn("Go to the first error", buttons[0].get_text())

        # the second should be a general message about the title, no go to error button
        self.assertIn(
            "Title: This field is required",
            header_messages[1].get_text(),
        )
        self.assertEqual(len(header_messages[1].find_all("button")), 0)

        # the third header message should be the non-field error
        self.assertIn(
            "The end date must be after the start date",
            header_messages[2].get_text(),
        )

        # Error on title shown against the title field
        error_messages = soup.css.select(".error-message")
        self.assertEqual(len(error_messages), 1)
        error_message = error_messages[0]
        self.assertEqual(
            error_message.parent["id"], "panel-child-content-child-title-errors"
        )
        self.assertIn("This field is required.", error_message.get_text())


class TestNestedInlinePanel(WagtailTestUtils, TestCase):
    fixtures = ["test.json"]

    def setUp(self):
        self.events_index = Page.objects.get(url_path="/home/events/")
        self.christmas_page = EventPage.objects.get(url_path="/home/events/christmas/")
        self.speaker = self.christmas_page.speakers.first()
        self.speaker.awards.create(
            name="Beard Of The Year", date_awarded=datetime.date(1997, 12, 25)
        )
        self.speaker.save()
        self.user = self.login()

    def test_get_edit_form(self):
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=(self.christmas_page.id,))
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            """<input type="text" name="speakers-0-awards-0-name" value="Beard Of The Year" maxlength="255" id="id_speakers-0-awards-0-name">""",
            count=1,
            html=True,
        )

        # there should be no "extra" forms, as the nested formset should respect the extra_form_count=0 set on WagtailAdminModelForm
        self.assertContains(
            response,
            """<input type="hidden" name="speakers-0-awards-TOTAL_FORMS" value="1" id="id_speakers-0-awards-TOTAL_FORMS">""",
            count=1,
            html=True,
        )
        self.assertContains(
            response,
            """<input type="text" name="speakers-0-awards-1-name" value="" maxlength="255" id="id_speakers-0-awards-1-name">""",
            count=0,
            html=True,
        )

        # date field should use AdminDatePicker
        self.assertContains(
            response,
            """<input type="text" name="speakers-0-awards-0-date_awarded" value="1997-12-25" autocomplete="off" id="id_speakers-0-awards-0-date_awarded">""",
            count=1,
            html=True,
        )

    def test_post_edit(self):
        post_data = nested_form_data(
            {
                "title": "Christmas",
                "date_from": "2017-12-25",
                "date_to": "2017-12-25",
                "slug": "christmas",
                "audience": "public",
                "location": "The North Pole",
                "cost": "Free",
                "carousel_items": inline_formset([]),
                "speakers": inline_formset(
                    [
                        {
                            "id": self.speaker.id,
                            "first_name": "Jeff",
                            "last_name": "Christmas",
                            "awards": inline_formset(
                                [
                                    {
                                        "id": self.speaker.awards.first().id,
                                        "name": "Beard Of The Century",
                                        "date_awarded": "1997-12-25",
                                    },
                                    {
                                        "name": "Bobsleigh Olympic gold medallist",
                                        "date_awarded": "2018-02-01",
                                    },
                                ],
                                initial=1,
                            ),
                        },
                    ],
                    initial=1,
                ),
                "related_links": inline_formset([]),
                "head_counts": inline_formset([]),
                "action-publish": "Publish",
            }
        )
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.christmas_page.id,)),
            post_data,
        )
        self.assertRedirects(
            response, reverse("wagtailadmin_explore", args=(self.events_index.id,))
        )

        new_christmas_page = EventPage.objects.get(url_path="/home/events/christmas/")
        self.assertEqual(new_christmas_page.speakers.first().first_name, "Jeff")
        awards = new_christmas_page.speakers.first().awards.all()
        self.assertEqual(len(awards), 2)
        self.assertEqual(awards[0].name, "Beard Of The Century")
        self.assertEqual(awards[1].name, "Bobsleigh Olympic gold medallist")

    def test_post_edit_with_json_response(self):
        self.christmas_page.unpublish()  # so that draft changes are applied to the database record

        post_data = nested_form_data(
            {
                "title": "Christmas",
                "date_from": "2017-12-25",
                "date_to": "2017-12-25",
                "slug": "christmas",
                "audience": "public",
                "location": "The North Pole",
                "cost": "Free",
                "carousel_items": inline_formset([]),
                "speakers": inline_formset(
                    [
                        {
                            "id": self.speaker.id,
                            "first_name": "Jeff",
                            "last_name": "Christmas",
                            "awards": inline_formset(
                                [
                                    {
                                        "id": self.speaker.awards.first().id,
                                        "name": "Beard Of The Century",
                                        "date_awarded": "1997-12-25",
                                    },
                                    {
                                        "name": "Bobsleigh Olympic gold medallist",
                                        "date_awarded": "2018-02-01",
                                    },
                                ],
                                initial=1,
                            ),
                        },
                    ],
                    initial=1,
                ),
                "related_links": inline_formset([]),
                "head_counts": inline_formset([]),
            }
        )
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.christmas_page.id,)),
            post_data,
            headers={"Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        response_json = response.json()
        self.assertEqual(response_json["success"], True)
        self.assertEqual(response_json["pk"], self.christmas_page.id)
        self.christmas_page.refresh_from_db()
        self.assertEqual(
            response_json["revision_id"], self.christmas_page.get_latest_revision().pk
        )

        new_award = self.christmas_page.speakers.first().awards.get(
            name="Bobsleigh Olympic gold medallist"
        )
        self.assertEqual(
            response_json["field_updates"],
            {
                "speakers-0-awards-INITIAL_FORMS": "2",
                "speakers-0-awards-1-id": str(new_award.id),
            },
        )


@override_settings(WAGTAIL_I18N_ENABLED=True)
class TestLocaleSelector(WagtailTestUtils, TestCase):
    fixtures = ["test.json"]

    def setUp(self):
        self.christmas_page = EventPage.objects.get(url_path="/home/events/christmas/")
        self.fr_locale = Locale.objects.create(language_code="fr")
        self.translated_christmas_page = self.christmas_page.copy_for_translation(
            self.fr_locale, copy_parents=True
        )
        self.user = self.login()

    def test_locale_selector(self):
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=[self.christmas_page.id])
        )

        self.assertContains(response, 'id="status-sidebar-english"')

        edit_translation_url = reverse(
            "wagtailadmin_pages:edit", args=[self.translated_christmas_page.id]
        )
        self.assertContains(response, f'href="{edit_translation_url}"')

    @override_settings(WAGTAIL_I18N_ENABLED=False)
    def test_locale_selector_not_present_when_i18n_disabled(self):
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=[self.christmas_page.id])
        )

        self.assertNotContains(response, "Page Locale:")

        edit_translation_url = reverse(
            "wagtailadmin_pages:edit", args=[self.translated_christmas_page.id]
        )
        self.assertNotContains(response, f'href="{edit_translation_url}"')

    def test_locale_dropdown_not_present_without_permission_to_edit(self):
        # Remove user's permissions to edit French tree
        en_events_index = Page.objects.get(url_path="/home/events/")
        group = Group.objects.get(name="Moderators")
        GroupPagePermission.objects.create(
            group=group,
            page=en_events_index,
            permission_type="change",
        )
        self.user.is_superuser = False
        self.user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="wagtailadmin", codename="access_admin"
            )
        )
        self.user.groups.add(group)
        self.user.save()

        # Locale indicator should exist, but the "French" option should be hidden
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=[self.christmas_page.id])
        )

        self.assertContains(response, 'id="status-sidebar-english"')

        edit_translation_url = reverse(
            "wagtailadmin_pages:edit", args=[self.translated_christmas_page.id]
        )
        self.assertNotContains(response, f'href="{edit_translation_url}"')


class TestPageSubscriptionSettings(WagtailTestUtils, TestCase):
    def setUp(self):
        # Find root page
        self.root_page = Page.objects.get(id=2)

        # Add child page
        child_page = SimplePage(
            title="Hello world!",
            slug="hello-world",
            content="hello",
        )
        self.root_page.add_child(instance=child_page)
        child_page.save_revision().publish()
        self.child_page = SimplePage.objects.get(id=child_page.id)

        # Login
        self.user = self.login()

    def test_comment_notifications_switched_off(self):
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=[self.child_page.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<input type="checkbox" name="comment_notifications" id="id_comment_notifications">',
        )
        self.assertTrue(
            PageSubscription.objects.filter(
                page=self.child_page, user=self.user, comment_notifications=False
            ).exists()
        )

    def test_comment_notifications_switched_on(self):
        PageSubscription.objects.create(
            page=self.child_page, user=self.user, comment_notifications=True
        )

        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=[self.child_page.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<input type="checkbox" name="comment_notifications" id="id_comment_notifications" checked>',
        )

    def test_post_with_comment_notifications_switched_on(self):
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "comment_notifications": "on",
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=[self.child_page.id]), post_data
        )
        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=[self.child_page.id])
        )

        # Check the subscription
        page = Page.objects.get(
            path__startswith=self.root_page.path, slug="hello-world"
        ).specific
        subscription = page.subscribers.get()

        self.assertEqual(subscription.user, self.user)
        self.assertTrue(subscription.comment_notifications)

    def test_post_with_comment_notifications_switched_off(self):
        # Switch on comment notifications so we can test switching them off
        subscription = PageSubscription.objects.create(
            page=self.child_page, user=self.user, comment_notifications=True
        )

        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=[self.child_page.id]), post_data
        )
        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=[self.child_page.id])
        )

        # Check the subscription
        subscription.refresh_from_db()
        self.assertFalse(subscription.comment_notifications)

    @override_settings(WAGTAILADMIN_COMMENTS_ENABLED=False)
    def test_comments_disabled(self):
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=[self.child_page.id])
        )
        self.assertNotContains(response, 'data-side-panel-toggle="comments"')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            '<input type="checkbox" name="comment_notifications" id="id_comment_notifications">',
        )

    @override_settings(WAGTAILADMIN_COMMENTS_ENABLED=False)
    def test_post_comments_disabled(self):
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "comment_notifications": "on",  # Testing that this gets ignored
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=[self.child_page.id]), post_data
        )
        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=[self.child_page.id])
        )

        # Check the subscription
        self.assertFalse(PageSubscription.objects.get().comment_notifications)


class TestCommenting(WagtailTestUtils, TestCase):
    """
    Tests both the comment notification and audit logging logic of the edit page view.
    """

    def setUp(self):
        # Find root page
        self.root_page = Page.objects.get(id=2)

        # Add child page
        child_page = SimplePage(
            title="Hello world!",
            slug="hello-world",
            content="hello",
        )
        self.root_page.add_child(instance=child_page)
        child_page.save_revision().publish()
        self.child_page = SimplePage.objects.get(id=child_page.id)

        # Login
        self.user = self.login()

        # Add a couple more users
        self.subscriber = self.create_user("subscriber")
        self.non_subscriber = self.create_user("non-subscriber")
        self.non_subscriber_2 = self.create_user("non-subscriber-2")
        self.never_emailed_user = self.create_user("never-emailed")

        PageSubscription.objects.create(
            page=self.child_page, user=self.user, comment_notifications=True
        )

        PageSubscription.objects.create(
            page=self.child_page, user=self.subscriber, comment_notifications=True
        )

        # Add comment and reply on a different page for the never_emailed_user
        # They should never be notified
        comment_on_other_page = Comment.objects.create(
            page=self.root_page, user=self.never_emailed_user, text="a comment"
        )

        CommentReply.objects.create(
            user=self.never_emailed_user, comment=comment_on_other_page, text="a reply"
        )

    def assertNeverEmailedWrongUser(self):
        self.assertNotIn(
            self.never_emailed_user.email,
            [to for email in mail.outbox for to in email.to],
        )

    def add_page_editor(self, username, **kwargs):
        user = self.create_user(username, **kwargs)
        group = Group.objects.create(name=f"{username} page editors")
        group.permissions.add(
            Permission.objects.get(
                content_type__app_label="wagtailadmin", codename="access_admin"
            )
        )
        group.user_set.add(user)
        GroupPagePermission.objects.create(
            group=group, page=self.child_page, permission_type="change"
        )
        return user

    def mention(self, user, *, prefix, key):
        label = f"@{user.email}"
        text = f"{prefix}{label}"
        return text, {
            "key": key,
            "user_id": str(user.pk),
            "start": len(prefix),
            "end": len(text),
            "label": label,
        }

    def scheduler_then_raise(self, registrations):
        def schedule(*, page, editor, changes):
            before = len(connection.run_on_commit)
            real_schedule_comment_notifications(
                page=page,
                editor=editor,
                changes=changes,
            )
            registered = connection.run_on_commit[before:]
            self.assertEqual(len(registered), 1)
            registrations.extend(item[1] for item in registered)
            raise RuntimeError("scheduler failed")

        return schedule

    def comment_post_data(
        self,
        *,
        comment_text,
        comment_mentions,
        reply_text=None,
        reply_mentions=(),
        action=None,
    ):
        data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "comments-TOTAL_FORMS": "1",
            "comments-INITIAL_FORMS": "0",
            "comments-MIN_NUM_FORMS": "0",
            "comments-MAX_NUM_FORMS": "",
            "comments-0-DELETE": "",
            "comments-0-resolved": "",
            "comments-0-id": "",
            "comments-0-contentpath": "title",
            "comments-0-text": comment_text,
            "comments-0-mentions": json.dumps(comment_mentions),
            "comments-0-position": "",
            "comments-0-replies-TOTAL_FORMS": "1" if reply_text else "0",
            "comments-0-replies-INITIAL_FORMS": "0",
            "comments-0-replies-MIN_NUM_FORMS": "0",
            "comments-0-replies-MAX_NUM_FORMS": "0",
        }
        if reply_text:
            data.update(
                {
                    "comments-0-replies-0-id": "",
                    "comments-0-replies-0-DELETE": "",
                    "comments-0-replies-0-text": reply_text,
                    "comments-0-replies-0-mentions": json.dumps(reply_mentions),
                }
            )
        if action:
            data[action] = "True"
        return data

    def existing_comment_post_data(
        self,
        *,
        comment,
        reply=None,
        comment_notifications=True,
        action=None,
    ):
        self.child_page.refresh_from_db()
        data = {
            "title": self.child_page.title,
            "content": self.child_page.content,
            "slug": self.child_page.slug,
            "comments-TOTAL_FORMS": "1",
            "comments-INITIAL_FORMS": "1",
            "comments-MIN_NUM_FORMS": "0",
            "comments-MAX_NUM_FORMS": "",
            "comments-0-DELETE": "",
            "comments-0-resolved": "",
            "comments-0-id": str(comment.pk),
            "comments-0-contentpath": comment.contentpath,
            "comments-0-text": comment.text,
            "comments-0-mentions": json.dumps(comment.mentions),
            "comments-0-position": "",
            "comments-0-replies-TOTAL_FORMS": "1" if reply else "0",
            "comments-0-replies-INITIAL_FORMS": "1" if reply else "0",
            "comments-0-replies-MIN_NUM_FORMS": "0",
            "comments-0-replies-MAX_NUM_FORMS": "0",
        }
        if reply:
            data.update(
                {
                    "comments-0-replies-0-id": str(reply.pk),
                    "comments-0-replies-0-DELETE": "",
                    "comments-0-replies-0-text": reply.text,
                    "comments-0-replies-0-mentions": json.dumps(reply.mentions),
                }
            )
        if comment_notifications:
            data["comment_notifications"] = "on"
        if action:
            data[action] = "True"
        return data

    def lifecycle_snapshot(self):
        self.child_page.refresh_from_db()
        return {
            "title": self.child_page.title,
            "content": self.child_page.content,
            "live": self.child_page.live,
            "has_unpublished_changes": self.child_page.has_unpublished_changes,
            "latest_revision_id": self.child_page.latest_revision_id,
            "live_revision_id": self.child_page.live_revision_id,
            "revision_count": self.child_page.revisions.count(),
            "comments": list(
                Comment.objects.filter(page=self.child_page)
                .order_by("pk")
                .values("pk", "text", "mentions", "contentpath")
            ),
            "replies": list(
                CommentReply.objects.filter(comment__page=self.child_page)
                .order_by("pk")
                .values("pk", "text", "mentions")
            ),
            "comment_mentions": list(
                CommentMention.objects.filter(comment__page=self.child_page)
                .order_by("comment_id", "user_id")
                .values_list("comment_id", "user_id")
            ),
            "reply_mentions": list(
                CommentReplyMention.objects.filter(reply__comment__page=self.child_page)
                .order_by("reply_id", "user_id")
                .values_list("reply_id", "user_id")
            ),
            "subscriptions": list(
                PageSubscription.objects.filter(page=self.child_page)
                .order_by("user_id")
                .values_list("user_id", "comment_notifications")
            ),
            "logs": list(
                PageLogEntry.objects.filter(page=self.child_page)
                .order_by("pk")
                .values("pk", "action", "revision_id", "data")
            ),
        }

    def rollback_edit_data(self, *, name, keys, action=None):
        old_target = self.add_page_editor(
            f"{name}-old", email=f"{name}-old@example.com"
        )
        new_target = self.add_page_editor(
            f"{name}-new", email=f"{name}-new@example.com"
        )
        old_comment_text, old_comment_occurrence = self.mention(
            old_target,
            prefix="Original comment for ",
            key=keys[0],
        )
        old_reply_text, old_reply_occurrence = self.mention(
            old_target,
            prefix="Original reply for ",
            key=keys[1],
        )
        comment = Comment.objects.create(
            page=self.child_page,
            user=self.user,
            text=old_comment_text,
            mentions=[old_comment_occurrence],
            contentpath="title",
        )
        reply = CommentReply.objects.create(
            comment=comment,
            user=self.user,
            text=old_reply_text,
            mentions=[old_reply_occurrence],
        )
        CommentMention.objects.create(comment=comment, user=old_target)
        CommentReplyMention.objects.create(reply=reply, user=old_target)

        new_comment_text, new_comment_occurrence = self.mention(
            new_target,
            prefix="Changed comment for ",
            key=keys[2],
        )
        new_reply_text, new_reply_occurrence = self.mention(
            new_target,
            prefix="Changed reply for ",
            key=keys[3],
        )
        comment.text = new_comment_text
        comment.mentions = [new_comment_occurrence]
        reply.text = new_reply_text
        reply.mentions = [new_reply_occurrence]
        data = self.existing_comment_post_data(
            comment=comment,
            reply=reply,
            comment_notifications=False,
            action=action,
        )
        data.update(
            {
                "title": f"{name} changed title",
                "content": f"{name} changed content",
            }
        )
        return data

    def assert_saved_comment_pair(
        self,
        *,
        comment,
        reply,
        target,
        comment_occurrences,
        reply_occurrences,
        actions,
        recipients,
        after_log_pk=0,
    ):
        comment.refresh_from_db()
        reply.refresh_from_db()
        self.assertEqual(comment.mentions, comment_occurrences)
        self.assertEqual(reply.mentions, reply_occurrences)
        self.assertEqual(
            set(
                CommentMention.objects.filter(comment=comment).values_list(
                    "user_id", flat=True
                )
            ),
            {target.pk},
        )
        self.assertEqual(
            set(
                CommentReplyMention.objects.filter(reply=reply).values_list(
                    "user_id", flat=True
                )
            ),
            {target.pk},
        )
        self.child_page.refresh_from_db()
        revision = self.child_page.get_latest_revision()
        self.assertCountEqual(
            PageLogEntry.objects.filter(
                page=self.child_page,
                pk__gt=after_log_pk,
                action__in=actions,
            ).values_list("action", "revision_id"),
            [(action, revision.pk) for action in actions],
        )
        actual_recipients = {
            recipient for message in mail.outbox for recipient in message.to
        }
        self.assertEqual(actual_recipients, set(recipients))
        self.assertNotIn(self.user.email, actual_recipients)

    def test_save_persists_comment_and_reply_mentions_after_commit(self):
        mentioned_user = self.add_page_editor(
            "lifecycle-mentioned", email="lifecycle-mentioned@example.com"
        )
        comment_text, comment_occurrence = self.mention(
            mentioned_user,
            prefix="Comment for ",
            key="7c719462-4289-46db-bc17-54fc6b1f2561",
        )
        repeated_label = comment_occurrence["label"]
        repeated_start = len(comment_text) + len(" and ")
        comment_text = f"{comment_text} and {repeated_label}"
        repeated_occurrence = {
            "key": "66c19c57-8fb9-45a7-8c2a-b5125c838357",
            "user_id": str(mentioned_user.pk),
            "start": repeated_start,
            "end": len(comment_text),
            "label": repeated_label,
        }
        reply_text, reply_occurrence = self.mention(
            mentioned_user,
            prefix="Reply for ",
            key="53a0ca39-28b2-4fc5-b71d-379626a7f442",
        )

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=[self.child_page.pk]),
                self.comment_post_data(
                    comment_text=comment_text,
                    comment_mentions=[comment_occurrence, repeated_occurrence],
                    reply_text=reply_text,
                    reply_mentions=[reply_occurrence],
                ),
            )
            self.assertEqual(mail.outbox, [])

        self.assertRedirects(
            response,
            reverse("wagtailadmin_pages:edit", args=[self.child_page.pk]),
        )
        comment = self.child_page.wagtail_admin_comments.get()
        reply = comment.replies.get()
        self.assertEqual(comment.mentions, [comment_occurrence, repeated_occurrence])
        self.assertEqual(reply.mentions, [reply_occurrence])
        self.assertEqual(
            set(
                CommentMention.objects.filter(comment=comment).values_list(
                    "user_id", flat=True
                )
            ),
            {mentioned_user.pk},
        )
        self.assertEqual(
            set(
                CommentReplyMention.objects.filter(reply=reply).values_list(
                    "user_id", flat=True
                )
            ),
            {mentioned_user.pk},
        )
        self.assertEqual(
            {recipient for message in mail.outbox for recipient in message.to},
            {self.subscriber.email, mentioned_user.email},
        )
        self.assertNotIn(
            self.user.email,
            {recipient for message in mail.outbox for recipient in message.to},
        )
        self.child_page.refresh_from_db()
        revision = self.child_page.get_latest_revision()
        self.assertCountEqual(
            PageLogEntry.objects.filter(
                page=self.child_page,
                action__in=[
                    "wagtail.comments.create",
                    "wagtail.comments.create_reply",
                ],
            ).values_list("action", "revision_id"),
            [
                ("wagtail.comments.create", revision.pk),
                ("wagtail.comments.create_reply", revision.pk),
            ],
        )

    def test_json_save_and_overwrite_persist_comment_and_reply_mentions(self):
        first_target = self.add_page_editor(
            "json-first-target", email="json-first-target@example.com"
        )
        first_comment_text, first_comment_occurrence = self.mention(
            first_target,
            prefix="JSON comment for ",
            key="dd4e1f21-6bb2-43b1-bc09-b4684e1e4bf9",
        )
        first_reply_text, first_reply_occurrence = self.mention(
            first_target,
            prefix="JSON reply for ",
            key="ff0e0afe-cb3e-4ec5-a491-82d6491962ab",
        )
        first_log_pk = PageLogEntry.objects.filter(page=self.child_page).latest("pk").pk

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=[self.child_page.pk]),
                self.comment_post_data(
                    comment_text=first_comment_text,
                    comment_mentions=[first_comment_occurrence],
                    reply_text=first_reply_text,
                    reply_mentions=[first_reply_occurrence],
                ),
                headers={"Accept": "application/json"},
            )
            self.assertEqual(mail.outbox, [])

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertTrue(callbacks)
        comment = self.child_page.wagtail_admin_comments.get()
        reply = comment.replies.get()
        self.assertEqual(
            response.json()["comments"]["comments"][0]["mentions"],
            [first_comment_occurrence],
        )
        self.assertEqual(
            response.json()["comments"]["comments"][0]["replies"][0]["mentions"],
            [first_reply_occurrence],
        )
        self.assert_saved_comment_pair(
            comment=comment,
            reply=reply,
            target=first_target,
            comment_occurrences=[first_comment_occurrence],
            reply_occurrences=[first_reply_occurrence],
            actions={"wagtail.comments.create", "wagtail.comments.create_reply"},
            recipients={self.subscriber.email, first_target.email},
            after_log_pk=first_log_pk,
        )
        overwritten_revision = self.child_page.get_latest_revision()
        revision_count = self.child_page.revisions.count()

        second_target = self.add_page_editor(
            "json-second-target", email="json-second-target@example.com"
        )
        second_comment_text, second_comment_occurrence = self.mention(
            second_target,
            prefix="Overwritten comment for ",
            key="26def2c2-e56b-41b5-9b30-cf43c42b9c82",
        )
        second_reply_text, second_reply_occurrence = self.mention(
            second_target,
            prefix="Overwritten reply for ",
            key="c08705e1-b56c-4a68-8b41-103438e6382c",
        )
        comment.text = second_comment_text
        comment.mentions = [second_comment_occurrence]
        reply.text = second_reply_text
        reply.mentions = [second_reply_occurrence]
        data = self.existing_comment_post_data(comment=comment, reply=reply)
        data.update(
            {
                "title": "JSON overwritten title",
                "content": "JSON overwritten content",
                "overwrite_revision_id": str(overwritten_revision.pk),
            }
        )
        second_log_pk = (
            PageLogEntry.objects.filter(page=self.child_page).latest("pk").pk
        )
        mail.outbox = []

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=[self.child_page.pk]),
                data,
                headers={"Accept": "application/json"},
            )
            self.assertEqual(mail.outbox, [])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["revision_id"], overwritten_revision.pk)
        self.assertEqual(self.child_page.revisions.count(), revision_count)
        self.assertTrue(callbacks)
        self.assert_saved_comment_pair(
            comment=comment,
            reply=reply,
            target=second_target,
            comment_occurrences=[second_comment_occurrence],
            reply_occurrences=[second_reply_occurrence],
            actions={"wagtail.comments.edit", "wagtail.comments.edit_reply"},
            recipients={second_target.email},
            after_log_pk=second_log_pk,
        )

    def test_publish_persists_comment_and_reply_mentions_after_commit(self):
        target = self.add_page_editor(
            "edit-publish-target", email="edit-publish-target@example.com"
        )
        comment_text, comment_occurrence = self.mention(
            target,
            prefix="Publish comment for ",
            key="d16fea86-a168-47de-9197-680ff3beb329",
        )
        reply_text, reply_occurrence = self.mention(
            target,
            prefix="Publish reply for ",
            key="1ce115b8-4774-4678-8903-42271dacb173",
        )
        first_log_pk = PageLogEntry.objects.filter(page=self.child_page).latest("pk").pk

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=[self.child_page.pk]),
                self.comment_post_data(
                    comment_text=comment_text,
                    comment_mentions=[comment_occurrence],
                    reply_text=reply_text,
                    reply_mentions=[reply_occurrence],
                    action="action-publish",
                ),
            )
            self.assertEqual(mail.outbox, [])

        self.assertRedirects(
            response,
            reverse("wagtailadmin_explore", args=[self.root_page.pk]),
        )
        self.assertTrue(callbacks)
        self.child_page.refresh_from_db()
        self.assertTrue(self.child_page.live)
        self.assertFalse(self.child_page.has_unpublished_changes)
        self.assertEqual(self.child_page.title, "I've been edited!")
        comment = self.child_page.wagtail_admin_comments.get()
        self.assert_saved_comment_pair(
            comment=comment,
            reply=comment.replies.get(),
            target=target,
            comment_occurrences=[comment_occurrence],
            reply_occurrences=[reply_occurrence],
            actions={"wagtail.comments.create", "wagtail.comments.create_reply"},
            recipients={self.subscriber.email, target.email},
            after_log_pk=first_log_pk,
        )

    def test_publish_hook_response_commits_mentions_without_audit_or_mail(self):
        target = self.add_page_editor(
            "edit-hook-target", email="edit-hook-target@example.com"
        )
        comment_text, comment_occurrence = self.mention(
            target,
            prefix="Hook comment for ",
            key="7616f682-1648-4c2c-a3fd-b4de2f60624f",
        )
        reply_text, reply_occurrence = self.mention(
            target,
            prefix="Hook reply for ",
            key="ab8bf45b-7896-4967-b8f0-9624c45091d5",
        )
        original_revision_id = self.child_page.latest_revision_id
        original_comment_logs = PageLogEntry.objects.filter(
            page=self.child_page,
            action__startswith="wagtail.comments.",
        ).count()

        def hook_func(request, page):
            self.assertIsInstance(request, HttpRequest)
            self.assertEqual(page.pk, self.child_page.pk)
            return HttpResponse("Hook response")

        with (
            self.register_hook("before_publish_page", hook_func),
            self.captureOnCommitCallbacks(execute=True) as callbacks,
        ):
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=[self.child_page.pk]),
                self.comment_post_data(
                    comment_text=comment_text,
                    comment_mentions=[comment_occurrence],
                    reply_text=reply_text,
                    reply_mentions=[reply_occurrence],
                    action="action-publish",
                ),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"Hook response")
        self.child_page.refresh_from_db()
        self.assertEqual(self.child_page.status_string, _("live + draft"))
        self.assertNotEqual(self.child_page.latest_revision_id, original_revision_id)
        self.assertEqual(self.child_page.title, "Hello world!")
        self.assertEqual(
            self.child_page.get_latest_revision().as_object().title,
            "I've been edited!",
        )
        comment = self.child_page.wagtail_admin_comments.get()
        reply = comment.replies.get()
        self.assertEqual(comment.mentions, [comment_occurrence])
        self.assertEqual(reply.mentions, [reply_occurrence])
        self.assertEqual(
            set(
                CommentMention.objects.filter(comment=comment).values_list(
                    "user_id", flat=True
                )
            ),
            {target.pk},
        )
        self.assertEqual(
            set(
                CommentReplyMention.objects.filter(reply=reply).values_list(
                    "user_id", flat=True
                )
            ),
            {target.pk},
        )
        self.assertEqual(
            PageLogEntry.objects.filter(
                page=self.child_page,
                action__startswith="wagtail.comments.",
            ).count(),
            original_comment_logs,
        )
        self.assertFalse(
            PageSubscription.objects.get(
                page=self.child_page, user=self.user
            ).comment_notifications
        )
        self.assertEqual(callbacks, [])
        self.assertEqual(mail.outbox, [])

    def test_retained_comment_and_reply_mentions_survive_target_changes(self):
        cases = ("rename", "deactivate", "permission_loss", "delete")
        for index, target_change in enumerate(cases):
            with self.subTest(target_change=target_change):
                target = self.add_page_editor(
                    f"retained-{target_change}",
                    email=f"retained-{target_change}@example.com",
                )
                comment_text, comment_occurrence = self.mention(
                    target,
                    prefix="Retained comment for ",
                    key=f"c9474c77-0ed7-4e41-9c7f-f597a695260{index}",
                )
                reply_text, reply_occurrence = self.mention(
                    target,
                    prefix="Retained reply for ",
                    key=f"53e3ed2c-f922-4aad-ab41-e74867e31b7{index}",
                )
                comment = Comment.objects.create(
                    page=self.child_page,
                    user=self.subscriber,
                    text=comment_text,
                    mentions=[comment_occurrence],
                    contentpath="title",
                )
                reply = CommentReply.objects.create(
                    comment=comment,
                    user=self.subscriber,
                    text=reply_text,
                    mentions=[reply_occurrence],
                )
                CommentMention.objects.create(comment=comment, user=target)
                CommentReplyMention.objects.create(reply=reply, user=target)
                target_pk = target.pk

                if target_change == "rename":
                    target.email = "renamed-target@example.com"
                    target.save(update_fields=["email"])
                elif target_change == "deactivate":
                    target.is_active = False
                    target.save(update_fields=["is_active"])
                elif target_change == "permission_loss":
                    target.groups.clear()
                else:
                    target.delete()

                comment_log_count = PageLogEntry.objects.filter(
                    page=self.child_page,
                    action__startswith="wagtail.comments.",
                ).count()
                mail.outbox = []
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.post(
                        reverse("wagtailadmin_pages:edit", args=[self.child_page.pk]),
                        self.existing_comment_post_data(
                            comment=comment,
                            reply=reply,
                        ),
                        headers={"Accept": "application/json"},
                    )
                    self.assertEqual(mail.outbox, [])

                self.assertEqual(response.status_code, 200)
                comment.refresh_from_db()
                reply.refresh_from_db()
                self.assertEqual(comment.mentions, [comment_occurrence])
                self.assertEqual(reply.mentions, [reply_occurrence])
                expected_targets = set() if target_change == "delete" else {target_pk}
                self.assertEqual(
                    set(
                        CommentMention.objects.filter(comment=comment).values_list(
                            "user_id", flat=True
                        )
                    ),
                    expected_targets,
                )
                self.assertEqual(
                    set(
                        CommentReplyMention.objects.filter(reply=reply).values_list(
                            "user_id", flat=True
                        )
                    ),
                    expected_targets,
                )
                self.assertEqual(
                    PageLogEntry.objects.filter(
                        page=self.child_page,
                        action__startswith="wagtail.comments.",
                    ).count(),
                    comment_log_count,
                )
                comment_json = response.json()["comments"]["comments"][0]
                self.assertEqual(comment_json["mentions"], [comment_occurrence])
                self.assertEqual(
                    comment_json["replies"][0]["mentions"], [reply_occurrence]
                )
                if target_change == "delete":
                    self.assertNotIn(
                        str(target_pk), response.json()["comments"]["mentioned_users"]
                    )
                self.assertEqual(mail.outbox, [])

                comment.delete()

    def test_edit_and_remove_comment_and_reply_mentions_syncs_lookups(self):
        old_target = self.add_page_editor(
            "old-edit-target", email="old-edit-target@example.com"
        )
        new_target = self.add_page_editor(
            "new-edit-target", email="new-edit-target@example.com"
        )
        old_comment_text, old_comment_occurrence = self.mention(
            old_target,
            prefix="Old comment for ",
            key="b4f8b533-f11c-4522-ba35-f16533f61a7e",
        )
        old_reply_text, old_reply_occurrence = self.mention(
            old_target,
            prefix="Old reply for ",
            key="f66153cc-abf2-4157-a806-309c690f3bb4",
        )
        comment = Comment.objects.create(
            page=self.child_page,
            user=self.user,
            text=old_comment_text,
            mentions=[old_comment_occurrence],
            contentpath="title",
        )
        reply = CommentReply.objects.create(
            comment=comment,
            user=self.user,
            text=old_reply_text,
            mentions=[old_reply_occurrence],
        )
        CommentMention.objects.create(comment=comment, user=old_target)
        CommentReplyMention.objects.create(reply=reply, user=old_target)

        new_comment_text, new_comment_occurrence = self.mention(
            new_target,
            prefix="New comment for ",
            key="804aaf4c-009c-4f20-a5c9-4ce7ebc8a724",
        )
        new_reply_text, new_reply_occurrence = self.mention(
            new_target,
            prefix="New reply for ",
            key="d1f058b2-e439-462a-87eb-c4ecea193b62",
        )
        comment.text = new_comment_text
        comment.mentions = [new_comment_occurrence]
        reply.text = new_reply_text
        reply.mentions = [new_reply_occurrence]

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=[self.child_page.pk]),
                self.existing_comment_post_data(comment=comment, reply=reply),
            )

        self.assertRedirects(
            response,
            reverse("wagtailadmin_pages:edit", args=[self.child_page.pk]),
        )
        comment.refresh_from_db()
        reply.refresh_from_db()
        self.assertEqual(comment.mentions, [new_comment_occurrence])
        self.assertEqual(reply.mentions, [new_reply_occurrence])
        self.assertEqual(
            set(
                CommentMention.objects.filter(comment=comment).values_list(
                    "user_id", flat=True
                )
            ),
            {new_target.pk},
        )
        self.assertEqual(
            set(
                CommentReplyMention.objects.filter(reply=reply).values_list(
                    "user_id", flat=True
                )
            ),
            {new_target.pk},
        )
        self.assertEqual(
            {recipient for email in mail.outbox for recipient in email.to},
            {new_target.email},
        )
        for action, old_occurrence, new_occurrence in (
            (
                "wagtail.comments.edit",
                old_comment_occurrence,
                new_comment_occurrence,
            ),
            (
                "wagtail.comments.edit_reply",
                old_reply_occurrence,
                new_reply_occurrence,
            ),
        ):
            entry = PageLogEntry.objects.filter(action=action).latest("pk")
            self.assertEqual(
                entry.data["mentions"],
                {
                    "added": [
                        {
                            "key": new_occurrence["key"],
                            "user_id": str(new_target.pk),
                        }
                    ],
                    "removed": [
                        {
                            "key": old_occurrence["key"],
                            "user_id": str(old_target.pk),
                        }
                    ],
                },
            )

        comment.text = "Mention removed from comment"
        comment.mentions = []
        reply.text = "Mention removed from reply"
        reply.mentions = []
        mail.outbox = []
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=[self.child_page.pk]),
                self.existing_comment_post_data(comment=comment, reply=reply),
            )

        self.assertRedirects(
            response,
            reverse("wagtailadmin_pages:edit", args=[self.child_page.pk]),
        )
        comment.refresh_from_db()
        reply.refresh_from_db()
        self.assertEqual(comment.mentions, [])
        self.assertEqual(reply.mentions, [])
        self.assertFalse(CommentMention.objects.filter(comment=comment).exists())
        self.assertFalse(CommentReplyMention.objects.filter(reply=reply).exists())
        self.assertEqual(mail.outbox, [])
        for action, removed_occurrence in (
            ("wagtail.comments.edit", new_comment_occurrence),
            ("wagtail.comments.edit_reply", new_reply_occurrence),
        ):
            entry = PageLogEntry.objects.filter(action=action).latest("pk")
            self.assertEqual(
                entry.data["mentions"],
                {
                    "added": [],
                    "removed": [
                        {
                            "key": removed_occurrence["key"],
                            "user_id": str(new_target.pk),
                        }
                    ],
                },
            )

    def test_save_rolls_back_comment_lifecycle_when_scheduling_fails(self):
        data = self.rollback_edit_data(
            name="save-rollback",
            keys=(
                "62171aa7-ad5e-4f68-9b58-af59df3c4f38",
                "08278279-d355-4d6b-83ea-e583cd4c71fe",
                "cd66de1d-386c-459e-9222-08d3c0a2fcaa",
                "2aab5183-941d-41a5-833e-730a32925ab7",
            ),
        )
        snapshot = self.lifecycle_snapshot()
        registrations = []
        mail.outbox = []

        with (
            mock.patch(
                "wagtail.admin.views.pages.edit.schedule_comment_notifications",
                side_effect=self.scheduler_then_raise(registrations),
            ),
            self.assertRaisesMessage(RuntimeError, "scheduler failed"),
            self.captureOnCommitCallbacks(execute=True) as callbacks,
        ):
            self.client.post(
                reverse("wagtailadmin_pages:edit", args=[self.child_page.pk]),
                data,
            )

        self.assertEqual(self.lifecycle_snapshot(), snapshot)
        self.assertEqual(len(registrations), 1)
        self.assertEqual(callbacks, [])
        self.assertEqual(mail.outbox, [])

    def test_publish_rolls_back_comment_lifecycle_when_scheduling_fails(self):
        data = self.rollback_edit_data(
            name="publish-rollback",
            keys=(
                "1c70d14b-03cb-4342-b3ec-97b336d16914",
                "ec0d3027-e245-455e-8476-7dabd88dc323",
                "855c462c-6273-4f11-abd5-fee84af3236c",
                "9bc70db8-ae91-4b23-b004-01154f0a96ea",
            ),
            action="action-publish",
        )
        snapshot = self.lifecycle_snapshot()
        registrations = []
        mail.outbox = []

        with (
            mock.patch(
                "wagtail.admin.views.pages.edit.schedule_comment_notifications",
                side_effect=self.scheduler_then_raise(registrations),
            ),
            self.assertRaisesMessage(RuntimeError, "scheduler failed"),
            self.captureOnCommitCallbacks(execute=True) as callbacks,
        ):
            self.client.post(
                reverse("wagtailadmin_pages:edit", args=[self.child_page.pk]),
                data,
            )

        self.assertEqual(self.lifecycle_snapshot(), snapshot)
        self.assertEqual(len(registrations), 1)
        self.assertEqual(callbacks, [])
        self.assertEqual(mail.outbox, [])

    def test_comments_enabled_by_default(self):
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=[self.child_page.id])
        )

        self.assertEqual(response.status_code, 200)

        soup = self.get_soup(response.content)
        form = soup.select_one("[data-edit-form]")
        self.assertEqual("page-edit-form", form["id"])
        self.assertIn("w-init", form["data-controller"])
        self.assertEqual("w-comments:init", form["data-w-init-event-value"])

    @override_settings(WAGTAILADMIN_COMMENTS_ENABLED=False)
    def test_comments_disabled(self):
        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=[self.child_page.id])
        )

        self.assertEqual(response.status_code, 200)

        soup = self.get_soup(response.content)
        form = soup.select_one("[data-edit-form]")
        self.assertEqual("page-edit-form", form["id"])
        self.assertIn("w-init", form["data-controller"])
        self.assertEqual("", form["data-w-init-event-value"])

    def test_new_comment(self):
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "comments-TOTAL_FORMS": "1",
            "comments-INITIAL_FORMS": "0",
            "comments-MIN_NUM_FORMS": "0",
            "comments-MAX_NUM_FORMS": "",
            "comments-0-DELETE": "",
            "comments-0-resolved": "",
            "comments-0-id": "",
            "comments-0-contentpath": "title",
            "comments-0-text": "A test comment",
            "comments-0-position": "",
            "comments-0-replies-TOTAL_FORMS": "0",
            "comments-0-replies-INITIAL_FORMS": "0",
            "comments-0-replies-MIN_NUM_FORMS": "0",
            "comments-0-replies-MAX_NUM_FORMS": "0",
        }

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=[self.child_page.id]),
                post_data,
            )

        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=[self.child_page.id])
        )

        # Refresh so that latest_revision is correct (instead of using the cached id)
        self.child_page.refresh_from_db()

        # Check the comment was added
        comment = self.child_page.wagtail_admin_comments.get()
        self.assertEqual(comment.text, "A test comment")

        # Check notification email
        self.assertEqual(len(mail.outbox), 1)
        self.assertNeverEmailedWrongUser()
        self.assertEqual(mail.outbox[0].to, [self.subscriber.email])
        self.assertEqual(
            mail.outbox[0].subject,
            'test@email.com has updated comments on "I\'ve been edited! (simple page)"',
        )
        self.assertIn('New comments:\n - "A test comment"\n\n', mail.outbox[0].body)

        # Check audit log
        log_entry = PageLogEntry.objects.get(action="wagtail.comments.create")
        self.assertEqual(log_entry.page, self.child_page.page_ptr)
        self.assertEqual(log_entry.user, self.user)
        self.assertEqual(log_entry.revision, self.child_page.get_latest_revision())
        self.assertEqual(log_entry.data["comment"]["id"], comment.id)
        self.assertEqual(log_entry.data["comment"]["contentpath"], comment.contentpath)
        self.assertEqual(log_entry.data["comment"]["text"], comment.text)

    def test_new_comment_with_mentions_records_audit_delta(self):
        mentioned_user = self.add_page_editor(
            "mentioned-user", email="mentioned-user@example.com"
        )
        label = f"@{mentioned_user.email}"
        text = f"A test comment {label}"
        occurrence = {
            "key": "29cc6a1f-00ed-41d7-94b1-d46a947962cb",
            "user_id": str(mentioned_user.pk),
            "start": len("A test comment "),
            "end": len(text),
            "label": label,
        }

        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "comments-TOTAL_FORMS": "1",
            "comments-INITIAL_FORMS": "0",
            "comments-MIN_NUM_FORMS": "0",
            "comments-MAX_NUM_FORMS": "",
            "comments-0-DELETE": "",
            "comments-0-resolved": "",
            "comments-0-id": "",
            "comments-0-contentpath": "title",
            "comments-0-text": text,
            "comments-0-mentions": json.dumps([occurrence]),
            "comments-0-position": "",
            "comments-0-replies-TOTAL_FORMS": "0",
            "comments-0-replies-INITIAL_FORMS": "0",
            "comments-0-replies-MIN_NUM_FORMS": "0",
            "comments-0-replies-MAX_NUM_FORMS": "0",
        }

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=[self.child_page.id]),
                post_data,
            )

        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=[self.child_page.id])
        )

        comment = self.child_page.wagtail_admin_comments.get()
        self.assertEqual(comment.mentions, [occurrence])

        self.assertEqual(
            {recipient for email in mail.outbox for recipient in email.to},
            {self.subscriber.email, mentioned_user.email},
        )
        self.assertNeverEmailedWrongUser()

        log_entry = PageLogEntry.objects.get(action="wagtail.comments.create")
        self.assertEqual(
            log_entry.data["mentions"],
            {
                "added": [
                    {"key": occurrence["key"], "user_id": str(mentioned_user.pk)}
                ],
                "removed": [],
            },
        )

    def test_new_comment_json(self):
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "comments-TOTAL_FORMS": "1",
            "comments-INITIAL_FORMS": "0",
            "comments-MIN_NUM_FORMS": "0",
            "comments-MAX_NUM_FORMS": "",
            "comments-0-DELETE": "",
            "comments-0-resolved": "",
            "comments-0-id": "",
            "comments-0-contentpath": "title",
            "comments-0-text": "A test comment",
            "comments-0-position": "",
            "comments-0-replies-TOTAL_FORMS": "0",
            "comments-0-replies-INITIAL_FORMS": "0",
            "comments-0-replies-MIN_NUM_FORMS": "0",
            "comments-0-replies-MAX_NUM_FORMS": "0",
        }

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=[self.child_page.id]),
                post_data,
                headers={"Accept": "application/json"},
            )

        self.assertEqual(response.status_code, 200)

        # Refresh so that latest_revision is correct (instead of using the cached id)
        self.child_page.refresh_from_db()

        # Check the comment was added
        comment = self.child_page.wagtail_admin_comments.get()
        self.assertEqual(comment.text, "A test comment")

        # Should include serialized comments data in the response
        response_json = response.json()
        self.assertEqual(response_json["success"], True)
        self.assertEqual(response_json["pk"], self.child_page.id)
        comments_json = response_json["comments"]
        self.assertEqual(len(comments_json["comments"]), 1)
        comment_json = comments_json["comments"][0]
        self.assertEqual(comment_json["pk"], comment.pk)
        self.assertEqual(comment_json["page"], self.child_page.pk)
        self.assertEqual(comment_json["user"], str(self.user.pk))
        self.assertEqual(comment_json["text"], "A test comment")
        self.assertEqual(comment_json["contentpath"], "title")
        self.assertEqual(comments_json["user"], str(self.user.pk))
        self.assertIn(str(self.user.pk), comments_json["authors"])

        # Check notification email
        self.assertEqual(len(mail.outbox), 1)
        self.assertNeverEmailedWrongUser()
        self.assertEqual(mail.outbox[0].to, [self.subscriber.email])
        self.assertEqual(
            mail.outbox[0].subject,
            'test@email.com has updated comments on "I\'ve been edited! (simple page)"',
        )
        self.assertIn('New comments:\n - "A test comment"\n\n', mail.outbox[0].body)

        # Check audit log
        log_entry = PageLogEntry.objects.get(action="wagtail.comments.create")
        self.assertEqual(log_entry.page, self.child_page.page_ptr)
        self.assertEqual(log_entry.user, self.user)
        self.assertEqual(log_entry.revision, self.child_page.get_latest_revision())
        self.assertEqual(log_entry.data["comment"]["id"], comment.id)
        self.assertEqual(log_entry.data["comment"]["contentpath"], comment.contentpath)
        self.assertEqual(log_entry.data["comment"]["text"], comment.text)

    def test_edit_comment(self):
        comment = Comment.objects.create(
            page=self.child_page,
            user=self.user,
            text="A test comment",
            contentpath="title",
        )

        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "comments-TOTAL_FORMS": "1",
            "comments-INITIAL_FORMS": "1",
            "comments-MIN_NUM_FORMS": "0",
            "comments-MAX_NUM_FORMS": "",
            "comments-0-DELETE": "",
            "comments-0-resolved": "",
            "comments-0-id": str(comment.id),
            "comments-0-contentpath": "title",
            "comments-0-text": "Edited",
            "comments-0-position": "",
            "comments-0-replies-TOTAL_FORMS": "0",
            "comments-0-replies-INITIAL_FORMS": "0",
            "comments-0-replies-MIN_NUM_FORMS": "0",
            "comments-0-replies-MAX_NUM_FORMS": "0",
        }

        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=[self.child_page.id]), post_data
        )

        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=[self.child_page.id])
        )

        # Refresh so that latest_revision is correct (instead of using the cached id)
        self.child_page.refresh_from_db()

        # Check the comment was edited
        comment.refresh_from_db()
        self.assertEqual(comment.text, "Edited")

        # No emails should be sent for edited comments
        self.assertEqual(len(mail.outbox), 0)

        # Check audit log
        log_entry = PageLogEntry.objects.get(action="wagtail.comments.edit")
        self.assertEqual(log_entry.page, self.child_page.page_ptr)
        self.assertEqual(log_entry.user, self.user)
        self.assertEqual(log_entry.revision, self.child_page.get_latest_revision())
        self.assertEqual(log_entry.data["comment"]["id"], comment.id)
        self.assertEqual(log_entry.data["comment"]["contentpath"], comment.contentpath)
        self.assertEqual(log_entry.data["comment"]["text"], comment.text)

    def test_mention_only_comment_edit_is_audited_and_notifies_new_target(self):
        previously_mentioned_user = self.add_page_editor(
            "previous-mention", email="previous-mention@example.com"
        )
        newly_mentioned_user = self.add_page_editor(
            "new-mention", email="new-mention@example.com"
        )
        previous_label = f"@{previously_mentioned_user.email}"
        new_label = f"@{newly_mentioned_user.email}"
        text = f"{previous_label} and {new_label}"
        previous_occurrence = {
            "key": "f4cf21fd-7dad-40e0-83da-d90310d2425f",
            "user_id": str(previously_mentioned_user.pk),
            "start": 0,
            "end": len(previous_label),
            "label": previous_label,
        }
        new_occurrence = {
            "key": "29cc6a1f-00ed-41d7-94b1-d46a947962cb",
            "user_id": str(newly_mentioned_user.pk),
            "start": len(previous_label) + len(" and "),
            "end": len(text),
            "label": new_label,
        }
        comment = Comment.objects.create(
            page=self.child_page,
            user=self.user,
            text=text,
            mentions=[previous_occurrence],
            contentpath="title",
        )

        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "comments-TOTAL_FORMS": "1",
            "comments-INITIAL_FORMS": "1",
            "comments-MIN_NUM_FORMS": "0",
            "comments-MAX_NUM_FORMS": "",
            "comments-0-DELETE": "",
            "comments-0-resolved": "",
            "comments-0-id": str(comment.id),
            "comments-0-contentpath": "title",
            "comments-0-text": text,
            "comments-0-mentions": json.dumps([previous_occurrence, new_occurrence]),
            "comments-0-position": "",
            "comments-0-replies-TOTAL_FORMS": "0",
            "comments-0-replies-INITIAL_FORMS": "0",
            "comments-0-replies-MIN_NUM_FORMS": "0",
            "comments-0-replies-MAX_NUM_FORMS": "0",
        }

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=[self.child_page.id]),
                post_data,
            )

        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=[self.child_page.id])
        )

        self.assertEqual(
            [email.to for email in mail.outbox], [[newly_mentioned_user.email]]
        )
        self.assertNeverEmailedWrongUser()

        comment.refresh_from_db()
        self.assertEqual(comment.mentions, [previous_occurrence, new_occurrence])
        log_entry = PageLogEntry.objects.get(action="wagtail.comments.edit")
        self.assertEqual(
            log_entry.data["mentions"],
            {
                "added": [
                    {
                        "key": new_occurrence["key"],
                        "user_id": str(newly_mentioned_user.pk),
                    }
                ],
                "removed": [],
            },
        )

    def test_new_comment_with_inaccessible_mention_is_rejected(self):
        label = f"@{self.never_emailed_user.email}"
        text = f"A test comment {label}"
        occurrence = {
            "key": "29cc6a1f-00ed-41d7-94b1-d46a947962cb",
            "user_id": str(self.never_emailed_user.pk),
            "start": len("A test comment "),
            "end": len(text),
            "label": label,
        }
        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "comments-TOTAL_FORMS": "1",
            "comments-INITIAL_FORMS": "0",
            "comments-MIN_NUM_FORMS": "0",
            "comments-MAX_NUM_FORMS": "",
            "comments-0-DELETE": "",
            "comments-0-resolved": "",
            "comments-0-id": "",
            "comments-0-contentpath": "title",
            "comments-0-text": text,
            "comments-0-mentions": json.dumps([occurrence]),
            "comments-0-position": "",
            "comments-0-replies-TOTAL_FORMS": "0",
            "comments-0-replies-INITIAL_FORMS": "0",
            "comments-0-replies-MIN_NUM_FORMS": "0",
            "comments-0-replies-MAX_NUM_FORMS": "0",
        }

        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=[self.child_page.id]), post_data
        )

        self.assertEqual(
            response.context["form"].formsets["comments"].errors,
            [{"mentions": ["Enter a valid mention list."]}],
        )
        self.assertFalse(self.child_page.wagtail_admin_comments.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_json_rejection_serializes_unsaved_comment_and_reply_state(self):
        mentioned_user = self.add_page_editor(
            "json-rejected-target", email="json-rejected-target@example.com"
        )
        comment_text, comment_occurrence = self.mention(
            mentioned_user,
            prefix="Rejected comment for ",
            key="cf40a7ed-79f5-457a-8697-01fbb031223a",
        )
        reply_text, reply_occurrence = self.mention(
            mentioned_user,
            prefix="Rejected reply for ",
            key="25b4709f-9220-4a5e-a8ac-af4c811efdd8",
        )

        with mock.patch(
            "wagtail.admin.forms.comments.page_mention_candidates",
            return_value=type(mentioned_user).objects.none(),
        ):
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=[self.child_page.pk]),
                self.comment_post_data(
                    comment_text=comment_text,
                    comment_mentions=[comment_occurrence],
                    reply_text=reply_text,
                    reply_mentions=[reply_occurrence],
                ),
                headers={"Accept": "application/json"},
            )

        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertEqual(response_data["success"], False)
        self.assertEqual(response_data["error_code"], "validation_error")
        self.assertEqual(
            response_data["error_message"],
            "There are validation errors, click save to highlight them.",
        )
        self.assertEqual(
            set(response_data),
            {"success", "error_code", "error_message", "comments"},
        )
        comment_data = response_data["comments"]["comments"][0]
        reply_data = comment_data["replies"][0]
        self.assertEqual(response_data["comments"]["mentioned_users"], {})
        self.assertIsNone(comment_data["pk"])
        self.assertEqual(comment_data["text"], comment_text)
        self.assertEqual(comment_data["mentions"], [comment_occurrence])
        self.assertEqual(comment_data["mention_error"], "Enter a valid mention list.")
        self.assertIsNone(reply_data["pk"])
        self.assertEqual(reply_data["text"], reply_text)
        self.assertEqual(reply_data["mentions"], [reply_occurrence])
        self.assertEqual(reply_data["mention_error"], "Enter a valid mention list.")
        self.assertFalse(self.child_page.wagtail_admin_comments.exists())

    def test_json_structural_errors_serialize_existing_sanitized_mentions(self):
        mentioned_user = self.add_page_editor(
            "json-structural-target", email="json-structural-target@example.com"
        )
        comment_text, comment_occurrence = self.mention(
            mentioned_user,
            prefix="Stored comment for ",
            key="777feade-1380-4699-a6e6-abca9bbd58aa",
        )
        reply_text, reply_occurrence = self.mention(
            mentioned_user,
            prefix="Stored reply for ",
            key="9d9ed399-1952-4925-af9a-3ea0e4903f22",
        )
        comment = Comment.objects.create(
            page=self.child_page,
            user=self.user,
            text=comment_text,
            mentions=[comment_occurrence],
            contentpath="title",
        )
        reply = CommentReply.objects.create(
            comment=comment,
            user=self.user,
            text=reply_text,
            mentions=[reply_occurrence],
        )
        post_data = self.existing_comment_post_data(comment=comment, reply=reply)
        post_data["comments-0-mentions"] = json.dumps(
            [{"private-comment-payload": "do not return"}]
        )
        post_data["comments-0-replies-0-mentions"] = json.dumps(
            [{"private-reply-payload": "do not return"}]
        )

        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=[self.child_page.pk]),
            post_data,
            headers={"Accept": "application/json"},
        )

        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertEqual(response_data["success"], False)
        self.assertEqual(response_data["error_code"], "validation_error")
        self.assertEqual(
            response_data["error_message"],
            "There are validation errors, click save to highlight them.",
        )
        comment_data = response_data["comments"]["comments"][0]
        reply_data = comment_data["replies"][0]
        self.assertEqual(comment_data["pk"], comment.pk)
        self.assertEqual(comment_data["mentions"], [comment_occurrence])
        self.assertEqual(comment_data["mention_error"], "Enter a valid mention list.")
        self.assertEqual(reply_data["pk"], reply.pk)
        self.assertEqual(reply_data["mentions"], [reply_occurrence])
        self.assertEqual(reply_data["mention_error"], "Enter a valid mention list.")
        serialized_response = json.dumps(response_data)
        self.assertNotIn("private-comment-payload", serialized_response)
        self.assertNotIn("private-reply-payload", serialized_response)

    def test_edit_another_users_comment(self):
        comment = Comment.objects.create(
            page=self.child_page,
            user=self.subscriber,
            text="A test comment",
            contentpath="title",
        )

        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "comments-TOTAL_FORMS": "1",
            "comments-INITIAL_FORMS": "1",
            "comments-MIN_NUM_FORMS": "0",
            "comments-MAX_NUM_FORMS": "",
            "comments-0-DELETE": "",
            "comments-0-resolved": "",
            "comments-0-id": str(comment.id),
            "comments-0-contentpath": "title",
            "comments-0-text": "Edited",
            "comments-0-position": "",
            "comments-0-replies-TOTAL_FORMS": "0",
            "comments-0-replies-INITIAL_FORMS": "0",
            "comments-0-replies-MIN_NUM_FORMS": "0",
            "comments-0-replies-MAX_NUM_FORMS": "0",
        }

        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=[self.child_page.id]), post_data
        )

        self.assertEqual(
            response.context["form"].formsets["comments"].errors,
            [{"__all__": ["You cannot edit another user's comment."]}],
        )

        # Refresh so that latest_revision is correct (instead of using the cached id)
        self.child_page.refresh_from_db()

        # Check the comment was not edited
        comment.refresh_from_db()
        self.assertNotEqual(comment.text, "Edited")

        # Check no log entry was created
        self.assertFalse(
            PageLogEntry.objects.filter(action="wagtail.comments.edit").exists()
        )

    def test_resolve_comment(self):
        comment = Comment.objects.create(
            page=self.child_page,
            user=self.non_subscriber,
            text="A test comment",
            contentpath="title",
        )

        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "comments-TOTAL_FORMS": "1",
            "comments-INITIAL_FORMS": "1",
            "comments-MIN_NUM_FORMS": "0",
            "comments-MAX_NUM_FORMS": "",
            "comments-0-DELETE": "",
            "comments-0-resolved": "on",
            "comments-0-id": str(comment.id),
            "comments-0-contentpath": "title",
            "comments-0-text": "A test comment",
            "comments-0-position": "",
            "comments-0-replies-TOTAL_FORMS": "0",
            "comments-0-replies-INITIAL_FORMS": "0",
            "comments-0-replies-MIN_NUM_FORMS": "0",
            "comments-0-replies-MAX_NUM_FORMS": "0",
        }

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=[self.child_page.id]),
                post_data,
            )

        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=[self.child_page.id])
        )

        # Refresh so that latest_revision is correct (instead of using the cached id)
        self.child_page.refresh_from_db()

        # Check the comment was resolved
        comment.refresh_from_db()
        self.assertTrue(comment.resolved_at)
        self.assertEqual(comment.resolved_by, self.user)

        # Check notification email
        self.assertEqual(len(mail.outbox), 2)
        self.assertNeverEmailedWrongUser()
        messages_by_recipient = {email.to[0]: email for email in mail.outbox}
        self.assertEqual(
            set(messages_by_recipient),
            {self.non_subscriber.email, self.subscriber.email},
        )
        # The non subscriber created the comment, so should also get an email
        non_subscriber_message = messages_by_recipient[self.non_subscriber.email]
        self.assertEqual(
            non_subscriber_message.subject,
            'test@email.com has updated comments on "I\'ve been edited! (simple page)"',
        )
        self.assertIn(
            'Resolved comments:\n - "A test comment"\n\n',
            non_subscriber_message.body,
        )
        subscriber_message = messages_by_recipient[self.subscriber.email]
        self.assertEqual(
            subscriber_message.subject,
            'test@email.com has updated comments on "I\'ve been edited! (simple page)"',
        )
        self.assertIn(
            'Resolved comments:\n - "A test comment"\n\n',
            subscriber_message.body,
        )

        # Check audit log
        log_entry = PageLogEntry.objects.get(action="wagtail.comments.resolve")
        self.assertEqual(log_entry.page, self.child_page.page_ptr)
        self.assertEqual(log_entry.user, self.user)
        self.assertEqual(log_entry.revision, self.child_page.get_latest_revision())
        self.assertEqual(log_entry.data["comment"]["id"], comment.id)
        self.assertEqual(log_entry.data["comment"]["contentpath"], comment.contentpath)
        self.assertEqual(log_entry.data["comment"]["text"], comment.text)

    def test_delete_comment(self):
        comment = Comment.objects.create(
            page=self.child_page,
            user=self.user,
            text="A test comment",
            contentpath="title",
        )

        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "comments-TOTAL_FORMS": "1",
            "comments-INITIAL_FORMS": "1",
            "comments-MIN_NUM_FORMS": "0",
            "comments-MAX_NUM_FORMS": "",
            "comments-0-DELETE": "on",
            "comments-0-resolved": "",
            "comments-0-id": str(comment.id),
            "comments-0-contentpath": "title",
            "comments-0-text": "A test comment",
            "comments-0-position": "",
            "comments-0-replies-TOTAL_FORMS": "0",
            "comments-0-replies-INITIAL_FORMS": "0",
            "comments-0-replies-MIN_NUM_FORMS": "0",
            "comments-0-replies-MAX_NUM_FORMS": "0",
        }

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=[self.child_page.id]),
                post_data,
            )

        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=[self.child_page.id])
        )

        # Refresh so that latest_revision is correct (instead of using the cached id)
        self.child_page.refresh_from_db()

        # Check the comment was deleted
        self.assertFalse(self.child_page.wagtail_admin_comments.exists())

        # Check notification email
        self.assertEqual(len(mail.outbox), 1)
        self.assertNeverEmailedWrongUser()
        self.assertEqual(mail.outbox[0].to, [self.subscriber.email])
        self.assertEqual(
            mail.outbox[0].subject,
            'test@email.com has updated comments on "I\'ve been edited! (simple page)"',
        )
        self.assertIn('Deleted comments:\n - "A test comment"\n\n', mail.outbox[0].body)

        # Check audit log
        log_entry = PageLogEntry.objects.get(action="wagtail.comments.delete")
        self.assertEqual(log_entry.page, self.child_page.page_ptr)
        self.assertEqual(log_entry.user, self.user)
        self.assertEqual(log_entry.revision, self.child_page.get_latest_revision())
        self.assertEqual(log_entry.data["comment"]["id"], comment.id)
        self.assertEqual(log_entry.data["comment"]["contentpath"], comment.contentpath)
        self.assertEqual(log_entry.data["comment"]["text"], comment.text)

    def test_new_reply(self):
        comment = Comment.objects.create(
            page=self.child_page,
            user=self.non_subscriber,
            text="A test comment",
            contentpath="title",
        )

        reply = CommentReply.objects.create(
            comment=comment, user=self.non_subscriber_2, text="an old reply"
        )

        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "comments-TOTAL_FORMS": "1",
            "comments-INITIAL_FORMS": "1",
            "comments-MIN_NUM_FORMS": "0",
            "comments-MAX_NUM_FORMS": "",
            "comments-0-DELETE": "",
            "comments-0-resolved": "",
            "comments-0-id": str(comment.id),
            "comments-0-contentpath": "title",
            "comments-0-text": "A test comment",
            "comments-0-position": "",
            "comments-0-replies-TOTAL_FORMS": "2",
            "comments-0-replies-INITIAL_FORMS": "1",
            "comments-0-replies-MIN_NUM_FORMS": "0",
            "comments-0-replies-MAX_NUM_FORMS": "",
            "comments-0-replies-0-id": str(reply.id),
            "comments-0-replies-0-text": "an old reply",
            "comments-0-replies-1-id": "",
            "comments-0-replies-1-text": "a new reply",
        }

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("wagtailadmin_pages:edit", args=[self.child_page.id]),
                post_data,
            )

        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=[self.child_page.id])
        )

        # Refresh so that latest_revision is correct (instead of using the cached id)
        self.child_page.refresh_from_db()

        # Check the comment reply was added
        comment.refresh_from_db()
        self.assertEqual(comment.replies.last().text, "a new reply")

        # Check notification email
        self.assertEqual(len(mail.outbox), 3)
        self.assertNeverEmailedWrongUser()

        recipients = [mail.to for mail in mail.outbox]
        # The other non subscriber replied in the thread, so should get an email
        self.assertIn([self.non_subscriber_2.email], recipients)

        # The non subscriber created the comment, so should get an email
        self.assertIn([self.non_subscriber.email], recipients)

        self.assertIn([self.subscriber.email], recipients)
        self.assertEqual(
            mail.outbox[2].subject,
            'test@email.com has updated comments on "I\'ve been edited! (simple page)"',
        )
        self.assertIn(
            '  New replies to: "A test comment"\n   - "a new reply"',
            mail.outbox[2].body,
        )

        # Check audit log
        log_entry = PageLogEntry.objects.get(action="wagtail.comments.create_reply")
        self.assertEqual(log_entry.page, self.child_page.page_ptr)
        self.assertEqual(log_entry.user, self.user)
        self.assertEqual(log_entry.revision, self.child_page.get_latest_revision())
        self.assertEqual(log_entry.data["comment"]["id"], comment.id)
        self.assertEqual(log_entry.data["comment"]["contentpath"], comment.contentpath)
        self.assertEqual(log_entry.data["comment"]["text"], comment.text)
        self.assertNotEqual(log_entry.data["reply"]["id"], reply.id)
        self.assertEqual(log_entry.data["reply"]["text"], "a new reply")

    def test_edit_reply(self):
        comment = Comment.objects.create(
            page=self.child_page,
            user=self.non_subscriber,
            text="A test comment",
            contentpath="title",
        )

        reply = CommentReply.objects.create(
            comment=comment, user=self.user, text="an old reply"
        )

        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "comments-TOTAL_FORMS": "1",
            "comments-INITIAL_FORMS": "1",
            "comments-MIN_NUM_FORMS": "0",
            "comments-MAX_NUM_FORMS": "",
            "comments-0-DELETE": "",
            "comments-0-resolved": "",
            "comments-0-id": str(comment.id),
            "comments-0-contentpath": "title",
            "comments-0-text": "A test comment",
            "comments-0-position": "",
            "comments-0-replies-TOTAL_FORMS": "1",
            "comments-0-replies-INITIAL_FORMS": "1",
            "comments-0-replies-MIN_NUM_FORMS": "0",
            "comments-0-replies-MAX_NUM_FORMS": "",
            "comments-0-replies-0-id": str(reply.id),
            "comments-0-replies-0-text": "an edited reply",
        }

        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=[self.child_page.id]), post_data
        )

        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=[self.child_page.id])
        )

        # Refresh so that latest_revision is correct (instead of using the cached id)
        self.child_page.refresh_from_db()

        # Check the comment reply was edited
        reply.refresh_from_db()
        self.assertEqual(reply.text, "an edited reply")

        # Check no notification was sent
        self.assertEqual(len(mail.outbox), 0)

        # Check audit log
        log_entry = PageLogEntry.objects.get(action="wagtail.comments.edit_reply")
        self.assertEqual(log_entry.page, self.child_page.page_ptr)
        self.assertEqual(log_entry.user, self.user)
        self.assertEqual(log_entry.revision, self.child_page.get_latest_revision())
        self.assertEqual(log_entry.data["comment"]["id"], comment.id)
        self.assertEqual(log_entry.data["comment"]["contentpath"], comment.contentpath)
        self.assertEqual(log_entry.data["comment"]["text"], comment.text)
        self.assertEqual(log_entry.data["reply"]["id"], reply.id)
        self.assertEqual(log_entry.data["reply"]["text"], "an edited reply")

    def test_delete_reply(self):
        comment = Comment.objects.create(
            page=self.child_page,
            user=self.non_subscriber,
            text="A test comment",
            contentpath="title",
        )

        reply = CommentReply.objects.create(
            comment=comment, user=self.user, text="an old reply"
        )

        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "comments-TOTAL_FORMS": "1",
            "comments-INITIAL_FORMS": "1",
            "comments-MIN_NUM_FORMS": "0",
            "comments-MAX_NUM_FORMS": "",
            "comments-0-DELETE": "",
            "comments-0-resolved": "",
            "comments-0-id": str(comment.id),
            "comments-0-contentpath": "title",
            "comments-0-text": "A test comment",
            "comments-0-position": "",
            "comments-0-replies-TOTAL_FORMS": "1",
            "comments-0-replies-INITIAL_FORMS": "1",
            "comments-0-replies-MIN_NUM_FORMS": "0",
            "comments-0-replies-MAX_NUM_FORMS": "",
            "comments-0-replies-0-id": str(reply.id),
            "comments-0-replies-0-text": "an old reply",
            "comments-0-replies-0-DELETE": "on",
        }

        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=[self.child_page.id]), post_data
        )

        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=[self.child_page.id])
        )

        # Refresh so that latest_revision is correct (instead of using the cached id)
        self.child_page.refresh_from_db()

        # Check the comment reply was deleted
        self.assertFalse(comment.replies.exists())

        # Check no notification was sent
        self.assertEqual(len(mail.outbox), 0)

        # Check audit log
        log_entry = PageLogEntry.objects.get(action="wagtail.comments.delete_reply")
        self.assertEqual(log_entry.page, self.child_page.page_ptr)
        self.assertEqual(log_entry.user, self.user)
        self.assertEqual(log_entry.revision, self.child_page.get_latest_revision())
        self.assertEqual(log_entry.data["comment"]["id"], comment.id)
        self.assertEqual(log_entry.data["comment"]["contentpath"], comment.contentpath)
        self.assertEqual(log_entry.data["comment"]["text"], comment.text)
        self.assertEqual(log_entry.data["reply"]["id"], reply.id)
        self.assertEqual(log_entry.data["reply"]["text"], reply.text)

    def test_updated_comments_notifications_profile_setting(self):
        # Users can disable commenting notifications globally from account settings
        profile = UserProfile.get_for_user(self.subscriber)
        profile.updated_comments_notifications = False
        profile.save()

        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "comments-TOTAL_FORMS": "1",
            "comments-INITIAL_FORMS": "0",
            "comments-MIN_NUM_FORMS": "0",
            "comments-MAX_NUM_FORMS": "",
            "comments-0-DELETE": "",
            "comments-0-resolved": "",
            "comments-0-id": "",
            "comments-0-contentpath": "title",
            "comments-0-text": "A test comment",
            "comments-0-position": "",
            "comments-0-replies-TOTAL_FORMS": "0",
            "comments-0-replies-INITIAL_FORMS": "0",
            "comments-0-replies-MIN_NUM_FORMS": "0",
            "comments-0-replies-MAX_NUM_FORMS": "0",
        }

        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=[self.child_page.id]), post_data
        )

        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=[self.child_page.id])
        )

        # Check the comment was added
        comment = self.child_page.wagtail_admin_comments.get()
        self.assertEqual(comment.text, "A test comment")

        # This time, no emails should be submitted because the only subscriber has disabled these emails globally
        self.assertEqual(len(mail.outbox), 0)

    def test_updated_comments_notifications_active_users_only(self):
        # subscriber is inactive
        self.subscriber.is_active = False
        self.subscriber.save()

        post_data = {
            "title": "I've been edited!",
            "content": "Some content",
            "slug": "hello-world",
            "comments-TOTAL_FORMS": "1",
            "comments-INITIAL_FORMS": "0",
            "comments-MIN_NUM_FORMS": "0",
            "comments-MAX_NUM_FORMS": "",
            "comments-0-DELETE": "",
            "comments-0-resolved": "",
            "comments-0-id": "",
            "comments-0-contentpath": "title",
            "comments-0-text": "A test comment",
            "comments-0-position": "",
            "comments-0-replies-TOTAL_FORMS": "0",
            "comments-0-replies-INITIAL_FORMS": "0",
            "comments-0-replies-MIN_NUM_FORMS": "0",
            "comments-0-replies-MAX_NUM_FORMS": "0",
        }

        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=[self.child_page.id]), post_data
        )

        self.assertRedirects(
            response, reverse("wagtailadmin_pages:edit", args=[self.child_page.id])
        )

        # Check the comment was added
        comment = self.child_page.wagtail_admin_comments.get()
        self.assertEqual(comment.text, "A test comment")

        # No emails should be submitted because subscriber is inactive
        self.assertEqual(len(mail.outbox), 0)

    def test_comment_mention_suggestions(self):
        mentioned_user = self.add_page_editor(
            "mentionable",
            email="mentionable@example.com",
            first_name="Mention",
            last_name="Able",
        )
        self.add_page_editor("not-matching", email="not-matching@example.com")
        self.create_user(
            "inaccessible-mention",
            email="inaccessible-mention@example.com",
            first_name="Mention",
            last_name="Noaccess",
        )

        response = self.client.get(
            reverse(
                "wagtailadmin_pages:comment_mention_suggestions",
                args=[self.child_page.id],
            ),
            {"q": "mention"},
        )

        self.assertEqual(response.status_code, 200)
        expected_result = {
            "id": str(mentioned_user.pk),
            "label": "@mentionable@example.com",
            "email": "mentionable@example.com",
        }
        username = str(mentioned_user.get_username())
        normalized_username = re.sub(r"\s+", " ", username).strip()
        if normalized_username and normalized_username not in {
            expected_result["email"],
            expected_result["label"].removeprefix("@"),
        }:
            expected_result["username"] = username
        self.assertEqual(
            response.json(),
            {"results": [expected_result]},
        )

    def test_comment_mention_suggestions_require_page_edit_permission(self):
        self.client.logout()
        user = self.create_user("not-an-editor", password="password")
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="wagtailadmin", codename="access_admin"
            )
        )
        self.login(user)

        response = self.client.get(
            reverse(
                "wagtailadmin_pages:comment_mention_suggestions",
                args=[self.child_page.id],
            ),
            {"q": "mention"},
            headers={"x-requested-with": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 403)


class TestCommentOutput(WagtailTestUtils, TestCase):
    """
    Test that the correct set of comments is output on the edit page view
    """

    def setUp(self):
        # Find root page
        self.root_page = Page.objects.get(id=2)

        # Add child page
        self.child_page = StreamPage(
            title="Hello world!",
            body=[
                {
                    "id": "234",
                    "type": "product",
                    "value": {"name": "Cuddly toy", "price": "$9.95"},
                },
            ],
        )
        self.root_page.add_child(instance=self.child_page)
        self.child_page.save_revision().publish()

        # Login
        self.user = self.login()

    def test_only_comments_with_valid_paths_are_shown(self):
        # add some comments on self.child_page
        Comment.objects.create(
            user=self.user,
            page=self.child_page,
            text="A test comment",
            contentpath="title",
        )
        Comment.objects.create(
            user=self.user,
            page=self.child_page,
            text="A comment on a field that doesn't exist",
            contentpath="sillytitle",
        )
        Comment.objects.create(
            user=self.user,
            page=self.child_page,
            text="This is quite expensive",
            contentpath="body.234.price",
        )
        Comment.objects.create(
            user=self.user,
            page=self.child_page,
            text="A comment on a block that doesn't exist",
            contentpath="body.234.colour",
        )

        response = self.client.get(
            reverse("wagtailadmin_pages:edit", args=[self.child_page.id])
        )
        soup = self.get_soup(response.content)
        comments_data_json = soup.select_one("#comments-data").string
        comments_data = json.loads(comments_data_json)
        comment_text = [comment["text"] for comment in comments_data["comments"]]
        comment_text.sort()
        self.assertEqual(comment_text, ["A test comment", "This is quite expensive"])

    def test_comments_with_deep_contentpath_on_custom_fields(self):
        page = CommentableJSONPage(
            title="Commentable JSON Page",
            slug="commentable-json-page",
            commentable_body={
                "header": {
                    "title": "Comments are Welcome",
                },
            },
            uncommentable_body={
                "title": "No feedback here",
            },
            stream_body=[
                {
                    "id": "1",
                    "type": "text",
                    "value": "This allows comments",
                }
            ],
        )
        self.root_page.add_child(instance=page)

        Comment.objects.create(
            page=page,
            user=self.user,
            text="1. Comment on an existing JSON path in commentable JSONField",
            contentpath="commentable_body.header.title",
        )
        Comment.objects.create(
            page=page,
            user=self.user,
            text="2. Comment on a non-existing JSON path in commentable JSONField",
            contentpath="commentable_body.header.not_valid",
        )
        Comment.objects.create(
            page=page,
            user=self.user,
            text="3. Comment on an existing JSON path in base JSONField",
            contentpath="uncommentable_body.title",
        )
        Comment.objects.create(
            page=page,
            user=self.user,
            text="4. Comment on a non-existing JSON path in base JSONField",
            contentpath="uncommentable_body.not_valid",
        )
        Comment.objects.create(
            page=page,
            user=self.user,
            text="5. Comment on the top-level of a base JSONField",
            contentpath="uncommentable_body",
        )

        response = self.client.get(reverse("wagtailadmin_pages:edit", args=[page.id]))
        soup = self.get_soup(response.content)
        comments_data_json = soup.select_one("#comments-data").string
        comments_data = json.loads(comments_data_json)
        comment_text = [comment["text"] for comment in comments_data["comments"]]
        comment_text.sort()

        self.assertEqual(
            comment_text,
            [
                # Custom fields can define which paths are valid for comments
                "1. Comment on an existing JSON path in commentable JSONField",
                # Comments directly on the top-level (the field itself) are always valid
                "5. Comment on the top-level of a base JSONField",
            ],
        )


class TestPublishUnpublishPublish(WagtailTestUtils, TestCase):
    def setUp(self):
        self.root_page = Page.objects.get(id=2)
        # Initial version must be saved and published
        self.page = self.root_page.add_child(
            instance=StandardIndex(
                title="Test page for issue 13332",
                slug="issue-13332",
                live=False,
            )
        )
        self.page.save_revision().publish()
        self.user = self.login()

    def test_publish_unpublish_republish_with_inlines(self):
        # Publish new version and add an inline
        advert = Advert.objects.create(text="Hello World")
        post_data = {
            "title": self.page.title,
            "slug": self.page.slug,
            "advert_placements-TOTAL_FORMS": "1",
            "advert_placements-INITIAL_FORMS": "0",
            "advert_placements-MIN_NUM_FORMS": "0",
            "advert_placements-MAX_NUM_FORMS": "1000",
            "advert_placements-0-id": "",
            "advert_placements-0-advert": advert.id,
            "advert_placements-0-colour": "Red",
            "action-publish": "Publish",
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.page.id,)), post_data
        )
        self.assertRedirects(
            response, reverse("wagtailadmin_explore", args=(self.root_page.id,))
        )
        self.page.refresh_from_db()
        self.assertTrue(self.page.live)
        self.assertQuerySetEqual(
            self.page.advert_placements.all().values_list("colour", flat=True),
            ["Red"],
        )

        # Unpublish page
        response = self.client.post(
            reverse("wagtailadmin_pages:unpublish", args=(self.page.id,))
        )
        self.assertRedirects(
            response,
            reverse("wagtailadmin_explore", args=(self.root_page.id,)),
        )
        self.page.refresh_from_db()
        self.assertFalse(self.page.live)

        # Republish page with same inline
        # advert_placements-0-id is intentionally empty as a regression test for #13332, existing
        # data saved in inlines inside revisions will not have a pk associated with it, so we need
        # to ensure republishing still works as expected. For this case - there should be just one
        # inline item.
        post_data = {
            "title": self.page.title,
            "slug": self.page.slug,
            "advert_placements-TOTAL_FORMS": "1",
            "advert_placements-INITIAL_FORMS": "1",
            "advert_placements-MIN_NUM_FORMS": "0",
            "advert_placements-MAX_NUM_FORMS": "1000",
            "advert_placements-0-id": "",
            "advert_placements-0-advert": advert.id,
            "advert_placements-0-colour": "Red",
            "action-publish": "Publish",
        }
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(self.page.id,)), post_data
        )
        self.assertRedirects(
            response, reverse("wagtailadmin_explore", args=(self.root_page.id,))
        )
        self.page.refresh_from_db()
        self.assertTrue(self.page.live)
        self.assertQuerySetEqual(
            self.page.advert_placements.all().values_list("colour", flat=True),
            ["Red"],
        )
