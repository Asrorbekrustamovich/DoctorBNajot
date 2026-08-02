#!/usr/bin/env python
"""Django management entrypoint for EduMed HIS."""
import os
import sys


def main() -> None:
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django o'rnatilmagan. `pip install -r requirements.txt` bajaring "
            "va virtual environment faollashtirilganini tekshiring."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
