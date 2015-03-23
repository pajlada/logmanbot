import json
import time
import argparse
import re
import sys

import irc.client
import irc.logging

class LogBot(irc.client.SimpleIRCClient):
    cdata = {}
    flush_interval = 5

    def __init__(self, config):
        irc.client.SimpleIRCClient.__init__(self)

        parser = argparse.ArgumentParser()
        irc.logging.add_arguments(parser)
        args = parser.parse_args()
        irc.logging.setup(args)

        self.channels = config['main']['channels'].split(',')
        self.server = config['main']['server']
        self.port = int(config['main']['port'])
        self.nickname = config['main']['nickname']
        self.password = config['main']['password']
        self.reconnection_interval = 5

    def privmsg(self, target, message):
        self.connection.privmsg(target, message)

    def on_welcome(self, chatconn, event):
        for channel in self.channels:
            if irc.client.is_channel(channel):
                chatconn.join(channel)

                self.reopen(channel)

    def reopen(self, channel):
        if channel in self.cdata:
            self.cdata[channel]['msg_fh'].close()
        else:
            self.cdata[channel] = {}

        date_str = self._date_str()
        self.cdata[channel]['date'] = date_str
        self.cdata[channel]['msg_lastflush'] = 0
        self.cdata[channel]['msg_fh'] = open('logs/{0}-{1}.log'.format(date_str, channel), 'a')
        self.cdata[channel]['join_lastflush'] = 0
        self.cdata[channel]['join_fh'] = open('logs/joins/{0}-{1}.log'.format(date_str, channel), 'a')

        print('[{0} {1}] Opened log files for channel {2}'.format(self._date_str(), self._time_str(), channel))

    def _check_date(self, channel):
        if not self.cdata[channel]['date'] == self._date_str():
            self.reopen(channel)

    def write_msg(self, channel, str, flush=True):
        self._check_date(channel)

        self.cdata[channel]['msg_fh'].write(str + "\n")

        if flush and time.time() - self.cdata[channel]['msg_lastflush'] > self.flush_interval:
            self.cdata[channel]['msg_fh'].flush()
            self.cdata[channel]['msg_lastflush'] = time.time()

    def write_join(self, channel, str, flush=True):
        self._check_date(channel)

        self.cdata[channel]['join_fh'].write(str + "\n")

        if flush and time.time() - self.cdata[channel]['join_lastflush'] > self.flush_interval:
            self.cdata[channel]['join_fh'].flush()
            self.cdata[channel]['join_lastflush'] = time.time()

    def connect(self):
        print('Connecting to the Twitch IRC server...')
        try:
            irc.client.SimpleIRCClient.connect(self, self.server, self.port, self.nickname, self.password, self.nickname)
        except irc.client.ServerConnectionError:
            pass

    def _connected_checker(self):
        if not self.connection.is_connected():
            self.connection.execute_delayed(self.reconnection_interval,
                                            self._connected_checker)

            self.connect()

    def on_disconnect(self, chatconn, event):
        print('Disconnected... {0}'.format('|'.join(event.arguments)))
        self.connection.execute_delayed(self.reconnection_interval,
                                        self._connected_checker)

    def _time_str(self):
        return time.strftime('%H:%M:%S', time.gmtime())

    def _date_str(self):
        return time.strftime('%Y-%m-%d', time.gmtime())

    def on_pubmsg(self, chatconn, event):
        self.write_msg(event.target, '{0} <{1}> {2}'.format(self._time_str(), event.source.user, event.arguments[0]))

        if event.source.user == 'pajlada' and event.arguments[0] == '!logping':
            self.privmsg(event.target, 'pajlada, PONG')

    def on_join(self, chatconn, event):
        self.write_join(event.target, '{0} JOIN {1}'.format(self._time_str(), event.source.user))

    def on_part(self, chatconn, event):
        self.write_join(event.target, '{0} PART {1}'.format(self._time_str(), event.source.user))

    def quit(self):
        if self.connection.is_connected():
            self.connection.quit("bye")

        for channel_name, channel in self.cdata.items():
            channel['msg_fh'].close()
            channel['join_fh'].close()
