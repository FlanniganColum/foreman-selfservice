from alembic import context
from flask import current_app
config=context.config
target_db=current_app.extensions["migrate"].db
config.set_main_option("sqlalchemy.url",str(target_db.engine.url).replace("%","%%"))
target_metadata=target_db.metadata
def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"),target_metadata=target_metadata,literal_binds=True,compare_type=True)
    with context.begin_transaction(): context.run_migrations()
def run_migrations_online():
    with target_db.engine.connect() as connection:
        context.configure(connection=connection,target_metadata=target_metadata,compare_type=True)
        with context.begin_transaction(): context.run_migrations()
if context.is_offline_mode(): run_migrations_offline()
else: run_migrations_online()
