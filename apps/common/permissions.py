from rest_framework.permissions import BasePermission

from apps.accounts.constants import UserRole


class IsClient(BasePermission):
    message = "Доступно только клиентам."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.role == UserRole.CLIENT)


class IsMaster(BasePermission):
    """Мастер или админ. Админ намеренно проходит везде, где проходит мастер."""

    message = "Доступно только сотрудникам сервиса."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.role in (UserRole.MASTER, UserRole.ADMIN)
        )


class IsAdmin(BasePermission):
    """Только администратор.

    Отдельно от IsMaster: сводная аналитика по всей сети — выручка, воронка,
    остатки — это не то, что нужно мастеру у подъёмника, и не то, что стоит
    показывать всем сотрудникам подряд.
    """

    message = "Доступно только администратору."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.role == UserRole.ADMIN)
