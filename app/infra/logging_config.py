from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_FILE = PROJECT_ROOT / "logs" / "backend.log"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_backend_logging(
    log_file: str | Path = DEFAULT_LOG_FILE,
    level: int | str = logging.INFO,
    force: bool = False,
) -> Path:
    """Configure console and file logging for the backend process."""
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT)
    root_logger = logging.getLogger()

    if force:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            handler.close()
    elif any(getattr(handler, "_clinical_cds_handler", False) for handler in root_logger.handlers):
        return log_path

    root_logger.setLevel(level)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler._clinical_cds_handler = True  # type: ignore[attr-defined]

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler._clinical_cds_handler = True  # type: ignore[attr-defined]

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    logging.getLogger("clinical_cds").info("event=logging_configured log_file=%s", log_path)
    return log_path
