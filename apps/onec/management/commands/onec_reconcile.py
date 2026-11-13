import json
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.common.exceptions import DomainError
from apps.onec.models import WorkplaceOrder
from apps.onec.services.reconciliation import reconcile
from apps.onec.services.workplace import snapshot


class Command(BaseCommand):
    help = "Посмотреть расчёт 1С или записать результат ручной сверки оборудования"

    def add_arguments(self, parser):
        parser.add_argument("booking_id", type=UUID)
        parser.add_argument(
            "--outcome", choices=("not-charged", "bank-confirmed", "no-receipt", "receipt")
        )
        parser.add_argument("--actor", type=UUID)
        parser.add_argument("--checkout-id", type=UUID)
        parser.add_argument("--revision", type=int)
        parser.add_argument("--evidence", default="")
        parser.add_argument("--bank-reference", default="")
        parser.add_argument("--receipt-number", default="")
        parser.add_argument("--shift", default="")

    def handle(self, *args, **options):
        try:
            order = WorkplaceOrder.objects.get(booking_id=options["booking_id"])
            if options["outcome"] is None:
                result = {**snapshot(order), "events": order.events}
            else:
                if not all(
                    options[key] is not None for key in ("actor", "checkout_id", "revision")
                ):
                    raise CommandError("Нужны --actor, --checkout-id, --revision и --evidence")
                user = User.objects.get(pk=options["actor"])
                result = reconcile(
                    user,
                    order.booking_id,
                    checkout_id=options["checkout_id"],
                    revision=options["revision"],
                    outcome=options["outcome"],
                    evidence=options["evidence"],
                    bank_reference=options["bank_reference"],
                    receipt={"number": options["receipt_number"], "shift": options["shift"]},
                )
        except (WorkplaceOrder.DoesNotExist, User.DoesNotExist, DomainError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
