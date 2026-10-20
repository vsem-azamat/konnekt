from aiogram import Router

from app.presentation.telegram.middlewares import (
    admin as admin_middlewares,
)
from app.presentation.telegram.middlewares import (
    chat_type as chat_type_middlewares,
)

from . import admin, captcha, events, groups, moderation, pending_actions, service, start

router = Router()

# The moderation routers carry their own guards — see that package's docstring,
# where the split between chat-scoped and global commands is explained.
admin.admin_router.message.middleware(chat_type_middlewares.ChatTypeMiddleware(["group", "supergroup"]))
admin.admin_router.message.middleware(admin_middlewares.SuperAdminMiddleware())
groups.groups_router.message.middleware(chat_type_middlewares.ChatTypeMiddleware(["group", "supergroup"]))
# `!json` dumps a message's internals, which is a debugging tool, not moderation.
service.router.message.middleware(admin_middlewares.SuperAdminMiddleware())

router.include_router(moderation.moderation_router)
router.include_router(pending_actions.pending_actions_router)
router.include_router(captcha.router)
router.include_router(start.router)
router.include_router(admin.admin_router)
router.include_router(groups.groups_router)
router.include_router(service.router)
# channel_review_router is NOT included here — bot.py adds it, so that the
# identity sending review messages is the one holding their callbacks
router.include_router(events.router)
