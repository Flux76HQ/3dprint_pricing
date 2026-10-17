"""Apply database migrations. Run by the container entrypoint before the server starts."""
from app.config import load_config
from app.db import run_migrations

done = run_migrations(load_config().database_url)
print(f"Migrations applied: {', '.join(done) if done else 'none (up to date)'}")
