"""Private file storage for security plans (outside public MEDIA_ROOT)."""

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivatePlanStorage(FileSystemStorage):
    """Files under PRIVATE_MEDIA_ROOT — never served via /media/."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("location", str(settings.PRIVATE_MEDIA_ROOT))
        kwargs.setdefault("base_url", None)
        super().__init__(*args, **kwargs)

    def url(self, name):
        # Force callers to use authenticated views; no public URL.
        raise ValueError("Private plan files have no public URL")


private_plan_storage = PrivatePlanStorage()
