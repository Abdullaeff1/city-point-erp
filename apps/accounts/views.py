from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordResetConfirmView, PasswordResetView
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts.forms import ForcedSetPasswordForm, InviteSetPasswordForm, PortalPasswordResetForm
from apps.accounts.impersonation import (
    actor_can_switch_roles,
    get_impersonator,
    resolve_role_user,
    start_impersonation,
    stop_impersonation,
)
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
@require_POST
def switch_role(request, role: str):
    """One-click preview as a staff role (admin / superuser only)."""
    if not actor_can_switch_roles(request):
        raise PermissionDenied(_("Rol dəyişmək yalnız admin üçündür."))
    if role not in {c.value for c in Role}:
        raise PermissionDenied(_("Naməlum rol."))

    impersonator = get_impersonator(request)
    target = resolve_role_user(role)
    if not target:
        messages.error(request, _("Bu rol üçün aktiv istifadəçi tapılmadı."))
        return redirect("post_login")

    # Clicking Admin while previewing → restore original admin session
    if impersonator and target.pk == impersonator.pk:
        stop_impersonation(request)
        messages.success(request, _("Admin hesabına qayıtdınız."))
        return redirect("post_login")

    if target.pk == request.user.pk:
        return redirect("post_login")

    try:
        start_impersonation(request, target)
    except PermissionError as exc:
        raise PermissionDenied(str(exc)) from exc

    messages.info(
        request,
        _("Rol önizləmə: %(role)s (%(email)s)")
        % {"role": target.get_role_display(), "email": target.email},
    )
    return redirect("post_login")


@login_required
@require_POST
def stop_role_preview(request):
    if not get_impersonator(request):
        return redirect("post_login")
    stop_impersonation(request)
    messages.success(request, _("Admin hesabına qayıtdınız."))
    return redirect("post_login")


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
