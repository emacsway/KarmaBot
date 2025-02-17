import asyncio
import random

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.filters import Command, CommandObject
from aiogram.utils.text_decorations import html_decoration as hd

from app.filters import (BotHasPermissions, HasPermissions, HasTargetFilter,
                         TargetHasPermissions)
from app.models.config import Config
from app.models.db import Chat, User
from app.services.moderation import (ban_user, delete_moderator_event,
                                     get_duration, ro_user, warn_user)
from app.services.remove_message import delete_message, remove_kb
from app.services.user_info import get_user_info
from app.utils.exceptions import ModerationError, TimedeltaParseError
from app.utils.log import Logger

from . import keyboards as kb

logger = Logger(__name__)
router = Router(name=__name__)


@router.message(
    F.chat.type.in_(["group", "supergroup"]),
    F.reply_to_message,
    Command('report', 'admin', 'spam', prefix="/!@"),
)
async def report(message: types.Message, bot: Bot):
    logger.info("user {user} report for message {message}", user=message.from_user.id, message=message.message_id)
    answer_template = "Спасибо за сообщение. Мы обязательно разберёмся. "
    admins_mention = await get_mentions_admins(message.chat, bot)
    await message.reply(answer_template + admins_mention + " ")


@router.message(
    F.chat.type == "private",
    Command('report', 'admin', 'spam', prefix="/!@"),
)
async def report_private(message: types.Message):
    await message.reply("Вы можете жаловаться на сообщения пользователей только в группах.")


async def get_mentions_admins(
    chat: types.Chat,
    bot: Bot,
    ignore_anonymous: bool = True,
):
    admins = await bot.get_chat_administrators(chat.id)
    random.shuffle(admins)  # чтобы попадались разные админы
    admins_mention = ""
    for admin in admins:
        if need_notify_admin(admin, ignore_anonymous):
            admins_mention += hd.link("&#8288;", admin.user.url)
    return admins_mention


def need_notify_admin(
    admin: types.ChatMemberAdministrator | types.ChatMemberOwner,
    ignore_anonymous: bool = True,
):
    """
    Проверяет, нужно ли уведомлять администратора о жалобе.

    :param admin: Администратор, которого нужно проверить.
    :param ignore_anonymous: Игнорировать ли анонимных администраторов.
    """
    if admin.user.is_bot or (ignore_anonymous and admin.is_anonymous):
        return False
    return admin.can_delete_messages or admin.can_restrict_members or admin.status == "creator"


@router.message(
    F.chat.type.in_(["group", "supergroup"]),
    HasTargetFilter(),
    Command(commands=["ro", "mute"], prefix="!"),
    HasPermissions(can_restrict_members=True),
    ~TargetHasPermissions(),
    BotHasPermissions(can_restrict_members=True),
)
async def cmd_ro(message: types.Message, user: User, target: User, chat: Chat, bot: Bot):
    try:
        duration, comment = get_duration(message.text)
    except TimedeltaParseError as e:
        return await message.reply(f"Не могу распознать время. {hd.quote(e.text)}")

    try:
        success_text = await ro_user(chat, target, user, duration, comment, bot)
    except ModerationError as e:
        logger.error("Failed to restrict chat member: {error!r}", error=e)
    else:
        await message.reply(success_text)


@router.message(
    F.chat.type.in_(["group", "supergroup"]),
    Command(commands=["ro", "mute"], prefix="!"),
    HasPermissions(can_restrict_members=True),
    ~BotHasPermissions(can_restrict_members=True),
)
async def cmd_ro_no_bot_permissions(message: types.Message):
    await message.reply("Мне нужны соответствующие права, чтобы запрещать писать пользователям в группе.")


@router.message(
    F.chat.type == "private",
    Command(commands=["ro", "mute"], prefix="!"),
)
async def cmd_ro_private(message: types.Message):
    await message.reply("Вы можете запрещать писать пользователям только в группах.")


@router.message(
    F.chat.type.in_(["group", "supergroup"]),
    HasTargetFilter(),
    Command(commands=["ban"], prefix="!"),
    HasPermissions(can_restrict_members=True),
    ~TargetHasPermissions(),
    BotHasPermissions(can_restrict_members=True),
)
async def cmd_ban(message: types.Message, user: User, target: User, chat: Chat, bot: Bot):
    try:
        duration, comment = get_duration(message.text)
    except TimedeltaParseError as e:
        return await message.reply(f"Не могу распознать время. {hd.quote(e.text)}")

    try:
        success_text = await ban_user(chat, target, user, duration, comment, bot)
    except ModerationError as e:
        logger.error("Failed to kick chat member: {error!r}", error=e, exc_info=e)
    else:
        await message.reply(success_text)


@router.message(
    F.chat.type.in_(["group", "supergroup"]),
    Command(commands=["ban"], prefix="!"),
    HasPermissions(can_restrict_members=True),
    ~BotHasPermissions(can_restrict_members=True),
)
async def cmd_ban_no_bot_permissions(message: types.Message):
    await message.reply("Мне нужны соответствующие права, чтобы блокировать пользователей в группе.")


@router.message(
    F.chat.type == "private",
    Command(commands=["ban"], prefix="!"),
)
async def cmd_ban_private(message: types.Message):
    await message.reply("Вы можете блокировать пользователей только в группах.")


@router.message(
    F.chat.type.in_(["group", "supergroup"]),
    HasTargetFilter(),
    Command(commands=["w", "warn"], prefix="!"),
    HasPermissions(can_restrict_members=True),
)
async def cmd_warn(message: types.Message, chat: Chat, target: User, user: User, config: Config, command: CommandObject):
    comment = command.args or ""

    moderator_event = await warn_user(
        moderator=user,
        target_user=target,
        chat=chat,
        comment=comment
    )

    text = "Пользователь {user} получил официальное предупреждение от модератора".format(
        user=target.mention_link,
    )
    msg = await message.reply(
        text,
        reply_markup=kb.get_kb_warn_cancel(user=user, moderator_event=moderator_event)
    )

    asyncio.create_task(remove_kb(msg, config.time_to_cancel_actions))


@router.message(
    F.chat.type == "private",
    Command(commands=["w", "warn"], prefix="!"),
)
async def cmd_warn_private(message: types.Message):
    await message.reply("Вы можете выдавать предупреждения пользователям только в группах.")


@router.message(
    F.chat.type == "private",
    Command("info", prefix='!'),
)
async def get_info_about_user_private(message: types.Message):
    await message.reply("Вы можете запрашивать информацию о пользователях только в группах.")


@router.message(
    F.chat.type.in_(["group", "supergroup"]),
    Command("info", prefix='!'),
    HasTargetFilter(can_be_same=True),
)
async def get_info_about_user(message: types.Message, chat: Chat, target: User, config: Config, bot: Bot):
    info = await get_user_info(target, chat, config.date_format)
    target_karma = await target.get_karma(chat)
    if target_karma is None:
        target_karma = "пока не имеет кармы"
    information = f"Данные на {target.mention_link} ({target_karma}):\n" + "\n".join(info)
    try:
        await bot.send_message(
            message.from_user.id,
            information,
            disable_web_page_preview=True
        )
    except TelegramUnauthorizedError:
        me = await bot.me()
        await message.reply(
            f'{message.from_user.mention_html()}, напишите мне в личку '
            f'<a href="https://t.me/{me.username}?start">/start</a> и повторите команду.'
        )
    finally:
        await delete_message(message)


@router.message(
    F.chat.type.in_(["group", "supergroup"]),
    Command(commands=["ro", "mute", "ban", "warn", "w"], prefix="!"),
    BotHasPermissions(can_delete_messages=True),
)
async def cmd_unhandled(message: types.Message):
    """
    Событие не было обработано ни одним из обработчиков.

    Это может произойти, если пользователь не имеет прав на выполнение одной из команд,
    либо если происходит попытка применить ограничения на администратора, себя или бота.
    """
    await delete_message(message)


@router.callback_query(kb.WarnCancelCb.filter())
async def cancel_warn(callback_query: types.CallbackQuery, callback_data: kb.WarnCancelCb):
    from_user = callback_query.from_user
    if callback_data.user_id != from_user.id:
        return await callback_query.answer("Эта кнопка не для Вас", cache_time=3600)
    await delete_moderator_event(callback_data.moderator_event_id, moderator=from_user)
    await callback_query.answer("Предупреждение было отменено", show_alert=True)
    await callback_query.message.delete()
