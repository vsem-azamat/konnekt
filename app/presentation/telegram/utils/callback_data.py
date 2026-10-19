from aiogram.filters.callback_data import CallbackData


class BlacklistConfirm(CallbackData, prefix="blconfirm"):
    user_id: int
    chat_id: int
    message_id: int
    revoke: int = 0
    mark_spam: int = 0


class UnblockUser(CallbackData, prefix="unblock"):
    user_id: int


class BlacklistPagination(CallbackData, prefix="blpage"):
    page: int
    query: str = ""
