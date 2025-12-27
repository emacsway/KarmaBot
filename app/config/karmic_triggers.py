PLUS = "+"
PLUS_WORDS = frozenset(
    {
        "спасибо",
        "спс",
        "спасибочки",
        "спасибки",
        "благодарю",
        "пасиба",
        "пасеба",
        "посеба",
        "благодарочка",
        "thx",
        "мерси",
        "выручил",
        "сяп",
        "сяб",
        "сенк",
        "сенкс",
        "сяпки",
        "сябки",
        "сенью",
        "благодарствую",
        "thank",
        "thanks",
        "класс",
    }
)
PLUS_TRIGGERS = frozenset({PLUS, *PLUS_WORDS})
PLUS_EMOJI = frozenset(
    {
        "👍",
        "🙏", "🤝", "👏", "💯", "🏆", "😍", "🤩", "🔥", "💥", "❤‍🔥", "❤", "📝", "✍",
    }
)
MINUS = "-"
MINUS_TRIGGERS = frozenset(
    {
        MINUS,
    }
)
MINUS_EMOJI = frozenset(
    {
        "👎",
        "💔", "🤮", "💩",
    }
)
