from django.contrib.auth.backends import ModelBackend
from accounts.models import WebUser


class EmailBackend(ModelBackend):
    def authenticate(self, request, username=None, email=None, password=None, **kwargs):
        login = email or username
        if not login:
            return None
        try:
            user = WebUser.objects.get(email__iexact=login)
        except WebUser.DoesNotExist:
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    def get_user(self, user_id):
        try:
            return WebUser.objects.get(pk=user_id)
        except WebUser.DoesNotExist:
            return None
