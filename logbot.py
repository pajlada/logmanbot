import json
import time
import argparse
import re
import sys
import os
import pymysql
import threading

import irc.client
import irc.logging

class LogBot(irc.client.SimpleIRCClient):
    channel_queue = []
    channels_joined = 0
    channel_limit = 40
    channel_limit_wait = 20

    connected_channels = {}

    cdata = {}
    flush_interval = 5

    def info(self, str):
        print('[{0} {1}] {2}'.format(self._date_str(), self._time_str(), str))

    def join_channels(self):
        for channel in self.channel_queue:
            if self.channels_joined > self.channel_limit:
                self.info('Reached channel join limit ({0}), sleeping for {1} seconds...'.format(self.channel_limit, self.channel_limit_wait))
                time.sleep(self.channel_limit_wait)
                self.channels_joined = 0

            self.join(channel)

        self.channel_queue.clear()

    def join(self, channel):
        self.info('Joining {0}'.format(channel))
        self.connection.join(channel)
        self.reopen(channel)
        self.channels_joined += 1

    def part(self, channel):
        self.info('Leaving {0}'.format(channel))

        self.connection.part(channel)

        if channel in self.cdata:
            self.cdata[channel]['msg_fh'].close()
            self.cdata[channel]['join_fh'].close()
            del self.cdata[channel]

    def __init__(self, config):
        irc.client.SimpleIRCClient.__init__(self)

        parser = argparse.ArgumentParser()
        irc.logging.add_arguments(parser)
        args = parser.parse_args()
        irc.logging.setup(args)

        self.server = config['main']['server']
        self.port = int(config['main']['port'])
        self.nickname = config['main']['nickname']
        self.password = config['main']['password']
        self.reconnection_interval = 5

        self.sqlconn = pymysql.connect(unix_socket=config['sql']['unix_socket'], user=config['sql']['user'], passwd=config['sql']['passwd'], db=config['sql']['db'], charset='utf8')
        self.sqlconn.autocommit(True)

        if not os.path.exists('logs'):
            os.makedirs('logs')

        if not os.path.exists('logs/joins'):
            os.makedirs('logs/joins')

    def privmsg(self, target, message):
        self.connection.privmsg(target, message)

    # Step 1. Fetch all channels from the database
    # Step 2. If we are currently connected to any channels,
    #         check each of those if they are in the new channel list.
    #         If the channel is not in the new channel list, leave it.
    #         If the channel IS in the new channel list, remove it from
    #         the list.
    # Step 3. Join all new channels
    def reload_channels(self):
        self.info('Reloading channels...')
        cursor = self.sqlconn.cursor()

        cursor.execute('SELECT `channel` FROM `channels` WHERE `enabled` = 1')

        for channel in cursor:
            self.channel_queue.append(channel[0])

        for channel in self.cdata:
            if channel not in self.channel_queue:
                self.part(channel)
            else:
                self.channel_queue.remove(channel)

        channel_thread = threading.Thread(target=self.join_channels)
        channel_thread.start()

    def on_welcome(self, chatconn, event):
        self.info('on_welcome!')
        self.reload_channels()

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

        self.info('Opened log files for channel {0}'.format(channel))

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
        self.info('Connecting to the Twitch IRC server...')
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
        self.info('Disconnected... {0}'.format('|'.join(event.arguments)))
        self.connection.execute_delayed(self.reconnection_interval,
                                        self._connected_checker)

    def _time_str(self):
        return time.strftime('%H:%M:%S', time.gmtime())

    def _date_str(self):
        return time.strftime('%Y-%m-%d', time.gmtime())

    def on_action(self, chatconn, event):
        self.on_pubmsg(chatconn, event)

    def on_pubmsg(self, chatconn, event):
        #self.info('Message received in {0}'.format(event.target))
        self.write_msg(event.target, '{0} <{1}> {2}'.format(self._time_str(), event.source.user, event.arguments[0]))

        if event.source.user == 'pajlada':
            if event.arguments[0] == '!logping':
                self.privmsg(event.target, 'pajlada, PONG')
            elif event.arguments[0] == '!logreload':
                self.privmsg(event.target, 'pajlada, reloading channels...')
                self.reload_channels()

    def on_join(self, chatconn, event):
        self.write_join(event.target, '{0} JOIN {1}'.format(self._time_str(), event.source.user))

    def on_part(self, chatconn, event):
        if event.target in self.cdata:
            self.write_join(event.target, '{0} PART {1}'.format(self._time_str(), event.source.user))

    def quit(self):
        if self.connection.is_connected():
            self.connection.quit("bye")

        for channel_name, channel in self.cdata.items():
            channel['msg_fh'].close()
            channel['join_fh'].close()
