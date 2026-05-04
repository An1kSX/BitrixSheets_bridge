
from app.core.config import settings
from app.core.logger import ModuleLogger

from .client import AsyncGoogleSheets


logger = ModuleLogger(
	module_name=__name__,
	to_console=settings.to_console,
	to_file=settings.to_file,
	log_level=settings.log_level
).get_logger()


class GoogleSheetsRepository:
    def __init__(self):
        pass