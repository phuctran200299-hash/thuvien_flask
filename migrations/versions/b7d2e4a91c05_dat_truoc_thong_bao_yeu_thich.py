"""Dat truoc sach, thong bao, tu sach yeu thich

Revision ID: b7d2e4a91c05
Revises: 81565560a0d3
Create Date: 2026-10-08 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7d2e4a91c05'
down_revision = '81565560a0d3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('reservations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('book_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['book_id'], ['books.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('reservations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_reservations_book_id'), ['book_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_reservations_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_reservations_user_id'), ['user_id'], unique=False)

    op.create_table('notifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('message', sa.Unicode(length=500), nullable=False),
    sa.Column('link', sa.String(length=255), nullable=True),
    sa.Column('dedup_key', sa.String(length=100), nullable=True),
    sa.Column('is_read', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notifications_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_notifications_dedup_key'), ['dedup_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_notifications_user_id'), ['user_id'], unique=False)

    op.create_table('favorites',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('book_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['book_id'], ['books.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'book_id', name='uq_favorite_user_book')
    )
    with op.batch_alter_table('favorites', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_favorites_book_id'), ['book_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_favorites_user_id'), ['user_id'], unique=False)

    # Cài đặt mới cho CSDL đã có dữ liệu (CSDL mới sẽ được thêm khi chạy flask seed)
    settings = sa.table('settings', sa.column('key', sa.String), sa.column('value', sa.UnicodeText),
                        sa.column('type', sa.String), sa.column('description', sa.Unicode))
    conn = op.get_bind()
    has_settings = conn.execute(sa.select(sa.func.count()).select_from(settings)).scalar()
    exists = conn.execute(sa.select(sa.func.count()).select_from(settings)
                          .where(settings.c.key == 'remind_before_days')).scalar()
    if has_settings and not exists:
        op.bulk_insert(settings, [{'key': 'remind_before_days', 'value': '2', 'type': 'number',
                                   'description': 'Nhắc hạn trả trước bao nhiêu ngày'}])


def downgrade():
    op.execute("DELETE FROM settings WHERE [key] = 'remind_before_days'")
    with op.batch_alter_table('favorites', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_favorites_user_id'))
        batch_op.drop_index(batch_op.f('ix_favorites_book_id'))
    op.drop_table('favorites')
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notifications_user_id'))
        batch_op.drop_index(batch_op.f('ix_notifications_dedup_key'))
        batch_op.drop_index(batch_op.f('ix_notifications_created_at'))
    op.drop_table('notifications')
    with op.batch_alter_table('reservations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_reservations_user_id'))
        batch_op.drop_index(batch_op.f('ix_reservations_status'))
        batch_op.drop_index(batch_op.f('ix_reservations_book_id'))
    op.drop_table('reservations')
