from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.generic.base import View

from wagtail.admin.comment_mentions import (
    comments_available_for_page_model,
    future_page_mention_candidates,
    page_mention_candidates,
    resolve_creatable_page_model,
    search_mention_candidates,
)
from wagtail.exceptions import PageClassNotFoundError
from wagtail.models import Page


class PageCommentMentionSuggestionsView(View):
    def dispatch(self, request, page_id, **kwargs):
        page = get_object_or_404(Page, pk=page_id)
        page_class = page.specific_class
        if page_class is None:
            content_type = page.cached_content_type
            raise PageClassNotFoundError(
                f"The page '{page}' cannot provide comment mention suggestions because "
                f"the model class used to create it ({content_type.app_label}."
                f"{content_type.model}) can no longer be found in the codebase."
            )
        self.page = page.specific
        if not self.page.permissions_for_user(request.user).can_edit():
            raise PermissionDenied
        if not comments_available_for_page_model(type(self.page)):
            raise Http404
        self.candidates = page_mention_candidates(self.page)
        return super().dispatch(request, page_id=page_id, **kwargs)

    def get(self, request, **kwargs):
        return JsonResponse(
            {
                "results": search_mention_candidates(
                    self.candidates,
                    request.GET.get("q", ""),
                )
            }
        )


class CreatePageCommentMentionSuggestionsView(View):
    def dispatch(
        self,
        request,
        content_type_app_name,
        content_type_model_name,
        parent_page_id,
        **kwargs,
    ):
        self.parent_page = get_object_or_404(Page, pk=parent_page_id).specific
        self.page_model = resolve_creatable_page_model(
            request=request,
            parent_page=self.parent_page,
            app_label=content_type_app_name,
            model_name=content_type_model_name,
        )
        if not comments_available_for_page_model(self.page_model):
            raise Http404
        self.candidates = future_page_mention_candidates(
            parent_page=self.parent_page,
            owner=request.user,
        )
        return super().dispatch(
            request,
            content_type_app_name=content_type_app_name,
            content_type_model_name=content_type_model_name,
            parent_page_id=parent_page_id,
            **kwargs,
        )

    def get(self, request, **kwargs):
        return JsonResponse(
            {
                "results": search_mention_candidates(
                    self.candidates,
                    request.GET.get("q", ""),
                )
            }
        )
