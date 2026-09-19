from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class InviteSetPasswordForm(SetPasswordForm):
    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        self.fields["new_password1"].widget.attrs.update({"class": "cp-input", "autocomplete": "new-password"})
        self.fields["new_password2"].widget.attrs.update({"class": "cp-input", "autocomplete": "new-password"})


class ForcedSetPasswordForm(SetPasswordForm):
    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        self.fields["new_password1"].widget.attrs.update({"class": "cp-input", "autocomplete": "new-password"})
        self.fields["new_password2"].widget.attrs.update({"class": "cp-input", "autocomplete": "new-password"})


class PortalPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(
        label=_("E-poçt"),
        max_length=254,
        widget=forms.EmailInput(attrs={"class": "cp-input", "autocomplete": "email"}),
    )

    def get_users(self, email):
        email = email.strip().lower()
        return User.objects.filter(email__iexact=email, is_active=True)
