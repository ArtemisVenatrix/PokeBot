from discord.ext import commands
import logging
from sqlalchemy.orm import sessionmaker, Session
import traceback


class MyBot(commands.Bot):
    def __init__(self, command_prefix, intents, session: sessionmaker):
        super().__init__(command_prefix, intents=intents)
        self.Session = session
        self.logger = logging.getLogger("discord")

    def getSession(self) -> Session:
        return self.Session()

    def logError(self, exc: Exception) -> None:
        self.logger.error("".join(traceback.format_exception(exc)))
        traceback.print_exception(exc)

    def logInfo(self, msg: str) -> None:
        self.logger.info(msg)
        print(msg)

    def logWarning(self, msg: str) -> None:
        self.logger.warning(msg)
        print(msg)