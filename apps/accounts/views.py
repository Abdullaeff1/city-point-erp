from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordResetConfirmView, PasswordResetView
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.accounts.forms import ForcedSetPasswordForm, InviteSetPasswordForm, PortalPasswordResetForm
from apps.accounts.invite import consume_invite, get_valid_invite
from apps.accounts.models import Role


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        if request.user.must_set_password:
            return redirect("accounts:force_set_password")
        return redirect("post_login")
    error = ""
    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=email, password=password)
        if user is None:
            error = _("E-poçt və ya şifrə yanlışdır.")
        else:
            login(request, user)
            if user.must_set_password:
                return redirect("accounts:force_set_password")
            return redirect("post_login")
    return render(request, "accounts/login.html", {"error": error})


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def post_login(request):
    if request.user.must_set_password:
        return redirect("accounts:force_set_password")
    if request.user.role == Role.RESIDENT_USER:
        return redirect("portal:home")
    if request.user.role == Role.SECURITY:
        return redirect("security:home")
    return redirect("erp:dashboard")


@require_http_methods(["GET", "POST"])
def invite_accept(request, token):
    invite = get_valid_invite(token)
    if not invite:
        return render(
            request,
            "accounts/invite_invalid.html",
            status=400,
        )
    user = invite.user
    form = InviteSetPasswordForm(user)
    error = ""
    if request.method == "POST":
        form = InviteSetPasswordForm(user, request.POST)
        if form.is_valid():
            try:
                consume_invite(token, form.cleaned_data["new_password1"])
            except ValueError:
                return render(request, "accounts/invite_invalid.html", status=400)
            login(request, user)
            return redirect("post_login")
        error = _("Şifrə tələblərinə uyğun deyil.")
    return render(
        request,
        "accounts/invite_set_password.html",
        {
            "form": form,
            "error": error,
            "email": user.email,
            "company": user.resident_company,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def force_set_password(request):
    if not request.user.must_set_password:
        return redirect("post_login")
    form = ForcedSetPasswordForm(request.user)
    error = ""
    if request.method == "POST":
        form = ForcedSetPasswordForm(request.user, request.POST)
        if form.is_valid():
            user = request.user
            user.set_password(form.cleaned_data["new_password1"])
            user.must_set_password = False
            user.save(update_fields=["password", "must_set_password"])
            login(request, user)
            return redirect("post_login")
        error = _("Şifrə tələblərinə uyğun deyil.")
    return render(
        request,
        "accounts/force_set_password.html",
        {"form": form, "error": error},
    )


class PortalPasswordResetView(PasswordResetView):
    template_name = "accounts/password_reset.html"
    email_template_name = "accounts/password_reset_email.txt"
    subject_template_name = "accounts/password_reset_subject.txt"
    form_class = PortalPasswordResetForm
    success_url = reverse_lazy("accounts:password_reset_done")
    extra_email_context = None


def password_reset_done(request):
    return render(request, "accounts/password_reset_done.html")


class PortalPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    form_class = InviteSetPasswordForm
    success_url = reverse_lazy("accounts:password_reset_complete")

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.user
        if user.must_set_password:
            user.must_set_password = False
            user.save(update_fields=["must_set_password"])
        return response


def password_reset_complete(request):
    return render(request, "accounts/password_reset_complete.html")
