import os


def isolated_env(url: str, **extra: str) -> dict[str, str]:
    """Environment for test subprocesses so only `url` can be the database target.

    POSTGRES_HOST takes precedence over DATABASE_URL in Settings, so it is blanked.
    Real environment variables also outrank values in a `.env` file, so a `.env` in the
    subprocess's working directory cannot redirect the database either. Scope: this
    blocks unintended *database* settings only; the `.env` file may still be read for
    other, unrelated settings.
    """
    return {
        **os.environ,
        "DATABASE_URL": url,
        "POSTGRES_HOST": "",
        "PYTHONDONTWRITEBYTECODE": "1",
        **extra,
    }
