from django import forms
from django.contrib.auth.password_validation import validate_password
from accounts.models import WebUser


class RegisterForm(forms.Form):
    email = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "you@example.com"}))
    display_name = forms.CharField(label="Имя", max_length=150, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Как к вам обращаться"}))
    password1 = forms.CharField(label="Пароль", widget=forms.PasswordInput(attrs={"class": "form-control"}))
    password2 = forms.CharField(label="Повтор пароля", widget=forms.PasswordInput(attrs={"class": "form-control"}))

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if WebUser.objects.filter(email=email).exists():
            raise forms.ValidationError("Этот email уже зарегистрирован.")
        return email

    def clean(self):
        cd = super().clean()
        p1, p2 = cd.get("password1"), cd.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Пароли не совпадают.")
        if p1:
            validate_password(p1)
        return cd


class LoginForm(forms.Form):
    email = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "you@example.com"}))
    password = forms.CharField(label="Пароль", widget=forms.PasswordInput(attrs={"class": "form-control"}))


class ChangePasswordForm(forms.Form):
    old_password = forms.CharField(label="Текущий пароль", widget=forms.PasswordInput(attrs={"class": "form-control"}))
    new_password1 = forms.CharField(label="Новый пароль", widget=forms.PasswordInput(attrs={"class": "form-control"}))
    new_password2 = forms.CharField(label="Повтор нового пароля", widget=forms.PasswordInput(attrs={"class": "form-control"}))

    def clean(self):
        cd = super().clean()
        if cd.get("new_password1") != cd.get("new_password2"):
            self.add_error("new_password2", "Пароли не совпадают.")
        if cd.get("new_password1"):
            validate_password(cd["new_password1"])
        return cd
