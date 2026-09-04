from django.db import models


class Document(models.Model):
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to="documents/%Y/%m/", blank=True)
    file_type = models.CharField(max_length=16, default="PDF")
    version = models.CharField(max_length=32, blank=True)
    size_label = models.CharField(max_length=32, blank=True)
    company = models.ForeignKey(
        "residents.ResidentCompany",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    space = models.ForeignKey(
        "property.Space", null=True, blank=True, on_delete=models.SET_NULL, related_name="documents"
    )
    published_at = models.DateField()

    class Meta:
        ordering = ["-published_at"]

    def __str__(self):
        return self.title
