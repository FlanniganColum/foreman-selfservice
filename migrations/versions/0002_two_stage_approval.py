"""Add server owners and stage-specific approvals.

Existing pending requests retain their pending_approval status. They require
an owner assignment before they can advance to Linux review.
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_two_stage_approval"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("auth_identities", sa.Column("authenticated_username", sa.String(255)))
    with op.batch_alter_table("servers") as batch:
        batch.add_column(sa.Column("technical_owner_id", sa.Integer(), sa.ForeignKey("users.id", name="fk_servers_technical_owner_id_users")))
        batch.add_column(sa.Column("business_owner_id", sa.Integer(), sa.ForeignKey("users.id", name="fk_servers_business_owner_id_users")))
    op.create_index("ix_servers_technical_owner_id", "servers", ["technical_owner_id"])
    op.create_index("ix_servers_business_owner_id", "servers", ["business_owner_id"])
    op.add_column("deployment_requests", sa.Column("submitted_form_data", sa.JSON()))
    op.execute("UPDATE deployment_requests SET submitted_form_data = form_data")
    op.add_column("approvals", sa.Column("stage", sa.String(16), nullable=False, server_default="owner"))


def downgrade():
    op.drop_column("approvals", "stage")
    op.drop_column("deployment_requests", "submitted_form_data")
    op.drop_index("ix_servers_business_owner_id", table_name="servers")
    op.drop_index("ix_servers_technical_owner_id", table_name="servers")
    with op.batch_alter_table("servers") as batch:
        batch.drop_column("business_owner_id")
        batch.drop_column("technical_owner_id")
    op.drop_column("auth_identities", "authenticated_username")
