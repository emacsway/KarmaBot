import pytest
from aiogram import types

from .common import CONF_CAN_BE_SAME, CONF_CANT_BE_SAME, filter_check
from .fixtures import (
    get_channel_message_no_mentions,
    get_channel_message_with_mention,
    get_channel_message_with_text_mention,
    get_from_user,
    get_message_with_mention,
    get_message_with_reply,
    get_message_with_reply_to_channel,
    get_message_with_text_mention,
    get_parts,
)


@pytest.mark.parametrize("phrase", get_parts())
def test_auto_reply(phrase: list[str]):
    user = get_from_user(321, "Kripke")
    msg = get_message_with_reply(user, user, " ".join(phrase))
    check_msg_auto_target(user, msg)


@pytest.mark.parametrize("phrase", get_parts())
def test_auto_mention(phrase: list[str]):
    user = get_from_user(321, "Kripke")
    msg = get_message_with_mention(user, user, phrase)
    check_msg_auto_target(user, msg)


@pytest.mark.parametrize("phrase", get_parts())
def test_auto_text_mention(phrase: list[str]):
    user = get_from_user(321, first_name="Barry")
    msg = get_message_with_text_mention(user, user, phrase)
    check_msg_auto_target(user, msg)


def check_msg_auto_target(user: dict, msg: types.Message):
    filter_rez = filter_check(msg, CONF_CANT_BE_SAME)
    assert filter_rez == {}, f"msg text {{{msg.text}}} user: {{{user}}}"
    filter_rez = filter_check(msg, CONF_CAN_BE_SAME)
    assert filter_rez != {}, f"msg text {{{msg.text}}} user: {{{user}}}"
    target_user = types.User(**user)
    founded_user = filter_rez["target"]
    if founded_user.id is None:
        assert (
            founded_user.username == target_user.username
        ), f"msg text {{{msg.text}}} user: {{{user}}}"
    else:
        assert are_users_equals(
            founded_user, target_user
        ), f"msg text {{{msg.text}}} user: {{{user}}}"


def are_users_equals(expected: types.User, actual: types.User) -> bool:
    return all(
        [
            expected.id == actual.id,
            expected.is_bot == actual.is_bot,
            expected.username == actual.username,
            expected.first_name == actual.first_name,
            expected.last_name == actual.last_name,
        ]
    )


# Tests for automatically forwarded channel messages


def test_reply_to_channel_message_with_text_mention():
    """When replying to forwarded channel message with text_mention, extract first mention."""
    author = get_from_user(100, "Alice")
    target = get_from_user(200, first_name="Bob")

    # Create simple channel message
    channel_msg = get_channel_message_no_mentions("Check out Bob's great work")

    # Reply with karma trigger and text_mention
    from .fixtures.targets import get_entity_text_mention
    reply_text = "++ Bob"
    entities = [get_entity_text_mention(3, target)]  # "Bob" starts at position 3
    reply_msg = get_message_with_reply_to_channel(author, channel_msg, reply_text, entities)

    filter_result = filter_check(reply_msg, CONF_CANT_BE_SAME)
    assert filter_result != {}, "Should find target user from reply mention"
    assert filter_result["target"].id == target["id"], "Should target the mentioned user"


def test_reply_to_channel_message_with_mention():
    """When replying to forwarded channel message with @mention, extract username."""
    author = get_from_user(100, "Alice")
    target = get_from_user(200, username="bob_username", first_name="Bob")

    # Create simple channel message
    channel_msg = get_channel_message_no_mentions("Check out great work")

    # Reply with karma trigger and @mention
    from .fixtures.targets import get_entity_mention
    reply_text = "++ @bob_username"
    entities = [get_entity_mention(3, 13)]  # "@bob_username" starts at position 3, length 13
    reply_msg = get_message_with_reply_to_channel(author, channel_msg, reply_text, entities)

    filter_result = filter_check(reply_msg, CONF_CANT_BE_SAME)
    assert filter_result != {}, "Should find target user from @mention in reply"
    assert filter_result["target"].username == target["username"]


def test_reply_to_channel_message_no_mentions():
    """When reply to channel has no mentions, karma change should be ignored."""
    author = get_from_user(100, "Alice")

    channel_msg = get_channel_message_no_mentions("Great article about AI")
    reply_msg = get_message_with_reply_to_channel(author, channel_msg, "++")

    filter_result = filter_check(reply_msg, CONF_CANT_BE_SAME)
    assert filter_result == {}, "Should not find target when no mentions in reply"


def test_reply_to_channel_message_multiple_mentions():
    """When reply has multiple mentions, use FIRST one."""
    author = get_from_user(100, "Alice")
    first_target = get_from_user(200, first_name="Bob")
    second_target = get_from_user(300, first_name="Charlie")

    # Create simple channel message
    channel_msg = get_channel_message_no_mentions("Great work by team")

    # Reply with multiple mentions - first_target mentioned first
    from .fixtures.targets import get_entity_text_mention
    reply_text = "++ Bob and Charlie"
    entities = [
        get_entity_text_mention(3, first_target),   # "Bob" at position 3
        get_entity_text_mention(11, second_target)  # "Charlie" at position 11
    ]
    reply_msg = get_message_with_reply_to_channel(author, channel_msg, reply_text, entities)

    filter_result = filter_check(reply_msg, CONF_CANT_BE_SAME)
    assert filter_result != {}, "Should find target user"
    assert (
        filter_result["target"].id == first_target["id"]
    ), "Should use first mention when multiple mentions exist"


def test_reply_to_regular_message_still_works():
    """Ensure regular replies still work as before (backward compatibility)."""
    author = get_from_user(100, "Alice")
    target = get_from_user(200, "Bob")

    regular_msg = get_message_with_reply(author, target, "++")

    filter_result = filter_check(regular_msg, CONF_CANT_BE_SAME)
    assert filter_result != {}, "Regular reply should still work"
    assert filter_result["target"].id == target["id"], "Regular reply should target message author"
