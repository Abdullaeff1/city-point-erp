"""Language selection for every portal."""

from django.conf import settings
from django.middleware.locale import LocaleMiddleware
from django.utils import translation
from django.utils.translation import check_for_language


class DefaultAzerbaijaniLocaleMiddleware(LocaleMiddleware):
    """Start in Azerbaijani. Another language is used only after an explicit choice."""

    def process_request(self, request):
        language = settings.LANGUAGE_CODE
        chosen = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)
        if chosen and check_for_language(chosen):
            try:
                language = translation.get_supported_language_variant(chosen)
            except LookupError:
                language = settings.LANGUAGE_CODE
        translation.activate(language)
        request.LANGUAGE_CODE = translation.get_language()
