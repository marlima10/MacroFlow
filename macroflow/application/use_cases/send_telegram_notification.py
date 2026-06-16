class SendTelegramNotification:
    def __init__(self, notifier):
        self.notifier = notifier

    def execute_async(self, config, message, on_result=None):
        if not config.enabled:
            return
        self.notifier.send_async(config.bot_token, config.chat_id, message, on_result)

    def test_async(self, config, message, on_result=None):
        self.notifier.send_async(config.bot_token, config.chat_id, message, on_result)
