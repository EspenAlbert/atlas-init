_dry_run = False


def is_dry_run():
    return _dry_run


def set_dry_run(dry_run: bool):
    global _dry_run
    _dry_run = dry_run
