from modules.ai.provider import (
    AIProvider
)


class AIService:
    @staticmethod
    def execute(prompt,):
        result = (AIProvider.generate(prompt))
        return result