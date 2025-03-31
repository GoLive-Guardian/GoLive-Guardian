from __future__ import annotations
from bot import GoLiveGuardian
from logging.handlers import RotatingFileHandler
from utils.db import MongoClient

import asyncio
import contextlib
import discord
import logging
import sys


try:
    import uvloop
    loop_factory = uvloop.new_event_loop

except ImportError:
    loop_factory = asyncio.new_event_loop


class RemoveNoise(logging.Filter):
    def __init__(self, name="discord.state"):
        super().__init__(name=name)
    
    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelname == 'WARNING' and 'referencing an unknown' in record.msg:
            return False
        return True


@contextlib.contextmanager
def setup_logging():
    log = logging.getLogger()

    try:
        discord.utils.setup_logging()
        # __enter__
        max_bytes = 32 * 1024 * 1024  # 32 MiB
        logging.getLogger('discord').setLevel(logging.INFO)
        logging.getLogger('discord.http').setLevel(logging.WARNING)
        logging.getLogger('discord.state').addFilter(RemoveNoise())

        # log.setLevel(logging.INFO)
        handler = RotatingFileHandler(filename='guardian.log', encoding='utf-8', mode='w', maxBytes=max_bytes, backupCount=5)
        dt_fmt = '%Y-%m-%d %H:%M:%S'
        fmt = logging.Formatter('[{asctime}] [{levelname:<7}] {name}: {message}', dt_fmt, style='{')
        handler.setFormatter(fmt)
        log.addHandler(handler)

        yield
    finally:
        # __exit__
        handlers = log.handlers[:]
        for hdlr in handlers:
            hdlr.close()
            log.removeHandler(hdlr)


async def start():
    log = logging.getLogger()

    try:
        pool = MongoClient()
        await pool.task

    except RuntimeError:
        click.echo('Could not connect to MongoDB. Exiting...', file=sys.stderr)
        log.exception('Could not connect to MongoDB. Exiting...')
        return

    async with GoLiveGuardian() as bot:
        bot.pool = pool
        await bot.start()
    

def main():
    try:
        with setup_logging():
            if sys.version_info >= (3, 11):
                with asyncio.Runner(debug=True, loop_factory=loop_factory) as runner:
                    runner.run(start())
            else:
                asyncio.run(start())

    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()