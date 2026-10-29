"""Drop eight tables no code has read since the channel and agent features left.

Nothing in the repository maps, migrates or queries them: they predate the
squashed initial schema and stayed in production when it was adopted. The five
that held rows (channel_posts 366, channel_sources 50, cost_events 3, channels 2,
agent_conversations 1) were exported on 2026-10-29 before this ran: a data-only
pg_dump and one CSV per table, kept outside the database. The other three were
empty, and the upgrade refuses to run if one of them is not, since nothing was
saved from it.

A fresh database never had them; the upgrade drops only what exists. The
downgrade recreates the structure as production had it, empty; the rows come
back from the export.

Revision ID: b6e1f4a8c203
Revises: a4c9e2f70b18
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6e1f4a8c203"
down_revision: str | None = "a4c9e2f70b18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ARCHIVED = ("channel_posts", "channel_sources", "channels", "cost_events", "agent_conversations")
UNSAVED = ("ad_leads", "agent_decisions", "agent_escalations")

# As pg_dump --schema-only printed them from production, less the pgvector column.
_SCHEMA = (
    """CREATE TABLE ad_leads (
    id integer NOT NULL,
    chat_id bigint NOT NULL,
    user_id bigint NOT NULL,
    snippet character varying,
    reached_via character varying(8) DEFAULT 'failed'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    link_clicked_at timestamp without time zone,
    ping_chat_id bigint,
    ping_message_id integer
)""",
    """CREATE SEQUENCE ad_leads_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1""",
    """ALTER SEQUENCE ad_leads_id_seq OWNED BY ad_leads.id""",
    """CREATE TABLE agent_conversations (
    user_id bigint NOT NULL,
    messages json NOT NULL,
    message_count integer DEFAULT 0 NOT NULL,
    last_active_at timestamp without time zone NOT NULL,
    created_at timestamp without time zone NOT NULL
)""",
    """CREATE TABLE agent_decisions (
    id integer NOT NULL,
    event_type character varying(32) NOT NULL,
    chat_id bigint NOT NULL,
    message_id bigint,
    target_user_id bigint NOT NULL,
    reporter_id bigint,
    message_text character varying,
    action character varying(32) NOT NULL,
    reason character varying NOT NULL,
    confidence double precision,
    admin_override character varying(32),
    created_at timestamp without time zone
)""",
    """CREATE SEQUENCE agent_decisions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1""",
    """ALTER SEQUENCE agent_decisions_id_seq OWNED BY agent_decisions.id""",
    """CREATE TABLE agent_escalations (
    id integer NOT NULL,
    decision_id integer,
    chat_id bigint NOT NULL,
    target_user_id bigint NOT NULL,
    message_text character varying,
    suggested_action character varying(32) NOT NULL,
    reason character varying NOT NULL,
    admin_message_id bigint,
    admin_chat_id bigint,
    status character varying(16) DEFAULT 'pending'::character varying NOT NULL,
    resolved_action character varying(32),
    resolved_by bigint,
    resolved_at timestamp without time zone,
    timeout_at timestamp without time zone NOT NULL,
    created_at timestamp without time zone
)""",
    """CREATE SEQUENCE agent_escalations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1""",
    """ALTER SEQUENCE agent_escalations_id_seq OWNED BY agent_escalations.id""",
    """CREATE TABLE channel_posts (
    id integer NOT NULL,
    channel_id bigint,
    external_id character varying NOT NULL,
    source_url character varying,
    title character varying NOT NULL,
    post_text character varying NOT NULL,
    telegram_message_id bigint,
    status character varying(16) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    source_items json,
    review_message_id bigint,
    review_chat_id bigint,
    admin_feedback character varying,
    image_url character varying,
    image_urls json,
    embedding_model character varying(64),
    scheduled_at timestamp without time zone,
    scheduled_telegram_id bigint,
    published_at timestamp without time zone,
    reply_chain_message_ids json,
    image_candidates json,
    image_phashes json,
    review_album_message_ids json,
    pre_critic_text character varying
)""",
    """CREATE SEQUENCE channel_posts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1""",
    """ALTER SEQUENCE channel_posts_id_seq OWNED BY channel_posts.id""",
    """CREATE TABLE channel_sources (
    id integer NOT NULL,
    channel_id bigint,
    url character varying NOT NULL,
    source_type character varying(16) NOT NULL,
    title character varying,
    language character varying(8),
    enabled boolean NOT NULL,
    relevance_score double precision NOT NULL,
    error_count integer NOT NULL,
    last_fetched_at timestamp without time zone,
    last_error character varying,
    added_by character varying(16) NOT NULL,
    created_at timestamp without time zone NOT NULL
)""",
    """CREATE SEQUENCE channel_sources_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1""",
    """ALTER SEQUENCE channel_sources_id_seq OWNED BY channel_sources.id""",
    """CREATE TABLE channels (
    id integer NOT NULL,
    telegram_id bigint,
    username character varying,
    name character varying NOT NULL,
    description character varying DEFAULT ''::character varying NOT NULL,
    language character varying(8) DEFAULT 'ru'::character varying NOT NULL,
    review_chat_id bigint,
    max_posts_per_day integer DEFAULT 3 NOT NULL,
    posting_schedule json,
    discovery_query character varying DEFAULT ''::character varying NOT NULL,
    source_discovery_query character varying DEFAULT ''::character varying NOT NULL,
    daily_posts_count integer DEFAULT 0 NOT NULL,
    daily_count_date character varying(10),
    last_source_discovery_at timestamp without time zone,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    modified_at timestamp without time zone DEFAULT now() NOT NULL,
    footer_template character varying,
    publish_schedule json,
    critic_enabled boolean
)""",
    """CREATE SEQUENCE channels_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1""",
    """ALTER SEQUENCE channels_id_seq OWNED BY channels.id""",
    """CREATE TABLE cost_events (
    id integer NOT NULL,
    occurred_at timestamp without time zone NOT NULL,
    model character varying(128) NOT NULL,
    operation character varying(64) NOT NULL,
    prompt_tokens integer DEFAULT 0 NOT NULL,
    completion_tokens integer DEFAULT 0 NOT NULL,
    total_tokens integer DEFAULT 0 NOT NULL,
    cache_read_tokens integer DEFAULT 0 NOT NULL,
    cache_write_tokens integer DEFAULT 0 NOT NULL,
    cost_usd double precision DEFAULT '0'::double precision NOT NULL,
    cache_savings_usd double precision DEFAULT '0'::double precision NOT NULL,
    channel_id character varying(64)
)""",
    """CREATE SEQUENCE cost_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1""",
    """ALTER SEQUENCE cost_events_id_seq OWNED BY cost_events.id""",
    """ALTER TABLE ONLY ad_leads ALTER COLUMN id SET DEFAULT nextval('ad_leads_id_seq'::regclass)""",
    """ALTER TABLE ONLY agent_decisions ALTER COLUMN id SET DEFAULT nextval('agent_decisions_id_seq'::regclass)""",
    """ALTER TABLE ONLY agent_escalations ALTER COLUMN id SET DEFAULT nextval('agent_escalations_id_seq'::regclass)""",
    """ALTER TABLE ONLY channel_posts ALTER COLUMN id SET DEFAULT nextval('channel_posts_id_seq'::regclass)""",
    """ALTER TABLE ONLY channel_sources ALTER COLUMN id SET DEFAULT nextval('channel_sources_id_seq'::regclass)""",
    """ALTER TABLE ONLY channels ALTER COLUMN id SET DEFAULT nextval('channels_id_seq'::regclass)""",
    """ALTER TABLE ONLY cost_events ALTER COLUMN id SET DEFAULT nextval('cost_events_id_seq'::regclass)""",
    """ALTER TABLE ONLY ad_leads
    ADD CONSTRAINT ad_leads_pkey PRIMARY KEY (id)""",
    """ALTER TABLE ONLY agent_conversations
    ADD CONSTRAINT agent_conversations_pkey PRIMARY KEY (user_id)""",
    """ALTER TABLE ONLY agent_decisions
    ADD CONSTRAINT agent_decisions_pkey PRIMARY KEY (id)""",
    """ALTER TABLE ONLY agent_escalations
    ADD CONSTRAINT agent_escalations_pkey PRIMARY KEY (id)""",
    """ALTER TABLE ONLY channel_posts
    ADD CONSTRAINT channel_posts_pkey PRIMARY KEY (id)""",
    """ALTER TABLE ONLY channel_sources
    ADD CONSTRAINT channel_sources_pkey PRIMARY KEY (id)""",
    """ALTER TABLE ONLY channels
    ADD CONSTRAINT channels_pkey PRIMARY KEY (id)""",
    """ALTER TABLE ONLY cost_events
    ADD CONSTRAINT cost_events_pkey PRIMARY KEY (id)""",
    """ALTER TABLE ONLY channel_posts
    ADD CONSTRAINT uq_channel_post_channel_external UNIQUE (channel_id, external_id)""",
    """ALTER TABLE ONLY channel_sources
    ADD CONSTRAINT uq_channel_source_channel_url UNIQUE (channel_id, url)""",
    """CREATE INDEX ix_ad_leads_created_at ON ad_leads USING btree (created_at)""",
    """CREATE INDEX ix_agent_conversations_last_active_at ON agent_conversations USING btree (last_active_at)""",
    """CREATE INDEX ix_agent_decisions_chat_id ON agent_decisions USING btree (chat_id)""",
    """CREATE INDEX ix_agent_decisions_target_user_id ON agent_decisions USING btree (target_user_id)""",
    """CREATE INDEX ix_agent_escalations_chat_id ON agent_escalations USING btree (chat_id)""",
    """CREATE INDEX ix_agent_escalations_decision_id ON agent_escalations USING btree (decision_id)""",
    """CREATE INDEX ix_agent_escalations_status ON agent_escalations USING btree (status)""",
    """CREATE INDEX ix_agent_escalations_target_user_id ON agent_escalations USING btree (target_user_id)""",
    """CREATE INDEX ix_channel_posts_channel_id ON channel_posts USING btree (channel_id)""",
    """CREATE INDEX ix_channel_posts_external_id ON channel_posts USING btree (external_id)""",
    """CREATE INDEX ix_channel_posts_status ON channel_posts USING btree (status)""",
    """CREATE INDEX ix_channel_sources_channel_id ON channel_sources USING btree (channel_id)""",
    """CREATE INDEX ix_channel_sources_url ON channel_sources USING btree (url)""",
    """CREATE UNIQUE INDEX ix_channels_telegram_id ON channels USING btree (telegram_id)""",
    """CREATE INDEX ix_cost_events_occurred_at ON cost_events USING btree (occurred_at)""",
    """CREATE INDEX ix_cost_events_operation ON cost_events USING btree (operation)""",
)


def upgrade() -> None:
    bind = op.get_bind()
    present = set(sa.inspect(bind).get_table_names())
    for table in UNSAVED:
        if table in present and bind.scalar(sa.select(sa.exists().select_from(sa.table(table)))):
            raise RuntimeError(f"{table} has rows that were never exported; export them before dropping it")
    for table in ARCHIVED + UNSAVED:
        if table in present:
            op.drop_table(table)


def downgrade() -> None:
    for statement in _SCHEMA:
        op.execute(statement)
    # Only where the extension is installed, as it was in production.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regtype('vector') IS NOT NULL THEN
                ALTER TABLE channel_posts ADD COLUMN embedding vector(768);
                CREATE INDEX ix_channel_posts_embedding ON channel_posts
                    USING hnsw (embedding vector_cosine_ops) WHERE (embedding IS NOT NULL);
            END IF;
        END $$
        """
    )
