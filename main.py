#!/usr/bin/env python3

import sys
import configparser
import time
import signal

from logbot import LogBot

thismodule = sys.modules[__name__]
config = configparser.ConfigParser()

res = config.read('config.ini')

if len(res) == 0:
    print('config.ini missing. Check out config.example.ini for the relevant data')
    sys.exit(0)

if not 'main' in config:
    print('Missing section [main] in config.ini')
    sys.exit(0)

def main():

    bot = LogBot(config)

    bot.connect()

    try:
        bot.start()
    except KeyboardInterrupt:
        bot.quit()
        pass

if __name__ == "__main__":
    main()
