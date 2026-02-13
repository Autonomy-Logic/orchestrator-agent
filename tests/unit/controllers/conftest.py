"""Fixtures for controller unit tests.

Importing from the controllers package triggers the @topic decorator chain,
which calls log_info at decoration time.  The logger lazily creates file
handlers under /var/orchestrator/logs — a path that does not exist in CI.

Setting the guard flag before any controller module is collected prevents
the file-system access entirely.
"""

import tools.logger as _logger

_logger._file_handlers_initialized = True
