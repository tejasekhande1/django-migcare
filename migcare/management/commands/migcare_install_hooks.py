"""
``migcare_install_hooks`` — install or remove the django-migcare git hooks.

Usage::

    python manage.py migcare_install_hooks          # install post-checkout hook
    python manage.py migcare_install_hooks --remove # remove the hook
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Install or remove the django-migcare git post-checkout hook that "
        "warns about ghost migrations after branch switches."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--remove",
            action="store_true",
            help="Remove the django-migcare block from the post-checkout hook.",
        )
        parser.add_argument(
            "--project-root",
            dest="project_root",
            default=None,
            help=(
                "Path to the project root (must be inside a git repo). "
                "Defaults to the current working directory."
            ),
        )

    def handle(self, *args, **options):
        from migcare.git_hooks import install, remove

        root = Path(options["project_root"]) if options["project_root"] else Path.cwd()

        if options["remove"]:
            changed = remove(root)
            if changed:
                self.stdout.write(
                    self.style.SUCCESS("django-migcare post-checkout hook removed.")
                )
            else:
                self.stdout.write("django-migcare hook was not installed — nothing to remove.")
            return

        try:
            hook_path = install(root)
        except FileNotFoundError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"django-migcare post-checkout hook installed at:\n  {hook_path}\n\n"
                "After a `git checkout` / `git switch`, migcare_check will run "
                "automatically and warn you about ghost migrations."
            )
        )
