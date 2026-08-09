"""Side-effect-only import of every module's SQLAlchemy models, so
Base.metadata is fully populated wherever this module is imported first.

Required for cross-module foreign keys (e.g. AuditEvent.organization_id ->
organizations.id) to resolve correctly. The FastAPI app process imports
every module's router/service anyway so this happens implicitly there, but
narrower entry points — a Temporal worker whose activity only touches
governance.models, a one-off script, Alembic's env.py — must import this
module explicitly first, or SQLAlchemy raises NoReferencedTableError the
moment it tries to sort tables for a flush() that spans modules."""

from content_studio.modules.analytics import models as _analytics_models  # noqa: F401
from content_studio.modules.billing import models as _billing_models  # noqa: F401
from content_studio.modules.commerce import models as _commerce_models  # noqa: F401
from content_studio.modules.creation import models as _creation_models  # noqa: F401
from content_studio.modules.governance import models as _governance_models  # noqa: F401
from content_studio.modules.identity import models as _identity_models  # noqa: F401
from content_studio.modules.marketing import models as _marketing_models  # noqa: F401
from content_studio.modules.publishing import models as _publishing_models  # noqa: F401
