from rest_framework import serializers


class HistoryItemSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["user", "assistant"])
    text = serializers.CharField(max_length=1000, allow_blank=True)


class AssistantAskSerializer(serializers.Serializer):
    service_point = serializers.UUIDField()
    chat = serializers.UUIDField(
        required=False, allow_null=True, default=None,
        help_text="Разговор из прошлого ответа. Пусто — новый разговор",
    )
    # Пустое и слишком длинное проверяет сервис — со своими кодами ошибок.
    message = serializers.CharField(
        max_length=2000, allow_blank=True, help_text="Что с машиной, своими словами"
    )
    history = HistoryItemSerializer(
        many=True, required=False, default=list,
        help_text="Прошлые сообщения этого разговора: на сервере текст не хранится",
    )


class AssistantStatusSerializer(serializers.Serializer):
    available = serializers.BooleanField(help_text="Показывать ли кнопку подсказчика")
    messages_left_today = serializers.IntegerField()
    messages_per_chat = serializers.IntegerField()


class SuggestedCategorySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    allow_on_site = serializers.BooleanField()


class SuggestedServiceSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class AssistantAnswerSerializer(serializers.Serializer):
    """Ответ подсказчика. Цен нет — их нет и в каталоге, который видит модель."""

    chat = serializers.UUIDField()
    reply = serializers.CharField()
    category = SuggestedCategorySerializer(allow_null=True, help_text="Предложенная категория")
    service = SuggestedServiceSerializer(allow_null=True, help_text="Предложенная услуга")
    on_site = serializers.BooleanField(
        help_text="Предложено «мастер подберёт на месте» в категории"
    )
    handoff = serializers.CharField(
        help_text="Не пусто — дальше с мастером: "
        "chat_limit, daily_limit, budget, unavailable, nothing"
    )
    messages_left = serializers.IntegerField(help_text="Сколько ещё сообщений в этом разговоре")
    phone = serializers.CharField(help_text="Телефон точки — для «позвонить мастеру»")
