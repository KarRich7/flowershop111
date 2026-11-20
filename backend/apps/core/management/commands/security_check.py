from django.core.management.base import BaseCommand

from apps.core.security import run_checks

ICONS = {"critical": "✖", "warning": "!", "info": "i"}


class Command(BaseCommand):
    help = "Проверка безопасности установки (что настроить перед запуском для покупателей). Код выхода 1 — есть критичное."

    def add_arguments(self, parser):
        parser.add_argument("--quiet", action="store_true", help="Только важные замечания и предупреждения (для журнала запуска)")

    def handle(self, *args, quiet=False, **opts):
        r = run_checks()
        mode = "боевой (PRODUCTION)" if r["production"] else "тестовый стенд"
        items = [i for i in r["items"] if not quiet or i["level"] != "info"]
        if quiet and not items:
            return
        self.stdout.write(f"Проверка безопасности. Режим: {mode}")
        if not items:
            self.stdout.write(self.style.SUCCESS("Замечаний нет"))
        for i in items:
            style = {"critical": self.style.ERROR, "warning": self.style.WARNING}.get(i["level"], str)
            self.stdout.write(style(f"[{ICONS[i['level']]}] {i['title']}"))
            if i["detail"]:
                self.stdout.write(f"    {i['detail']}")
            if i["fix"]:
                self.stdout.write(f"    → {i['fix']}")
        self.stdout.write(f"Критичных: {r['critical']}, предупреждений: {r['warnings']}")
        if r["critical"]:
            raise SystemExit(1)
