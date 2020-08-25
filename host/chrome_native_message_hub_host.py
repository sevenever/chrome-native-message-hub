#! /usr/bin/python3
import os
import sys
import asyncio
from asyncio import events
import struct
import json
import logging
import logging.handlers
import functools

MAX_MESSAGE_LEN = 1024 * 64

def setup_syslog():
    sysname = os.uname().sysname
    if sysname == 'Darwin':
        address = '/var/run/syslog'
    elif sysname == 'Linux':
        address = '/dev/log'
    else:
        raise OSNotSupportedError('{} is not supported'.format(sysname))
    logging.basicConfig(
            handlers=[logging.handlers.SysLogHandler(address=address, facility='local1')],
            level=logging.DEBUG)
setup_syslog()

class Client(object):
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer

# copied from asyncio.streams
class FlowControlMixin(asyncio.protocols.Protocol):
    """Reusable flow control logic for StreamWriter.drain().

    This implements the protocol methods pause_writing(),
    resume_writing() and connection_lost().  If the subclass overrides
    these it must call the super methods.

    StreamWriter.drain() must wait for _drain_helper() coroutine.
    """

    def __init__(self, loop=None):
        if loop is None:
            self._loop = events.get_event_loop()
        else:
            self._loop = loop
        self._paused = False
        self._drain_waiter = None
        self._connection_lost = False

    def pause_writing(self):
        assert not self._paused
        self._paused = True
        if self._loop.get_debug():
            logging.debug("%r pauses writing", self)

    def resume_writing(self):
        assert self._paused
        self._paused = False
        if self._loop.get_debug():
            logging.debug("%r resumes writing", self)

        waiter = self._drain_waiter
        if waiter is not None:
            self._drain_waiter = None
            if not waiter.done():
                waiter.set_result(None)

    def connection_lost(self, exc):
        self._connection_lost = True
        # Wake up the writer if currently paused.
        if not self._paused:
            return
        waiter = self._drain_waiter
        if waiter is None:
            return
        self._drain_waiter = None
        if waiter.done():
            return
        if exc is None:
            waiter.set_result(None)
        else:
            waiter.set_exception(exc)

    async def _drain_helper(self):
        if self._connection_lost:
            raise ConnectionResetError('Connection lost')
        if not self._paused:
            return
        waiter = self._drain_waiter
        assert waiter is None or waiter.cancelled()
        waiter = self._loop.create_future()
        self._drain_waiter = waiter
        await waiter

    def _get_close_waiter(self, stream):
        raise NotImplementedError

class InvalidMessageHeaderError(Exception):
    def __init__(self, msg_l):
        self.msg_l = msg_l

def send_err(writer, code, msg):
    writer.write(f'{{"code": {code}, "error": "{msg}"}}'.encode())

async def read_a_messagae(reader):
    data = await reader.readexactly(4)
    msg_l = struct.unpack('!I', data)[0]
    if msg_l > MAX_MESSAGE_LEN:
        raise InvalidMessageHeaderError
    data = await reader.readexactly(msg_l)
    return json.loads(data.decode())

def write_a_message(writer, json_obj):
    data = json.dumps(json_obj).encode()
    msg_l = len(data)
    if msg_l > MAX_MESSAGE_LEN:
        logging.warning('writing a message exceed max: %d', msg_l)
    writer.write(struct.pack('=I', msg_l))
    writer.write(data)

async def handle_client(reader, writer, stdout_writer, clients):
    addr = writer.get_extra_info('peername')
    logging.info('client %s connected.', addr)
    client = Client(reader, writer)

    try:
        # first msg should register extensionId/hostId pair
        j= await read_a_messagae(reader)
        if not 'registers' in j:
            send_err(writer, 4, 'first message should register a list of extensionId/hostId pairs')
            return
        for register in j['registers']:
            if not 'extensionId' in register:
                send_err(writer, 8, 'invalid register: no extensionId')
                return
            if not 'hostId' in register:
                send_err(writer, 8, 'invalid register: no hostId')
                return
            key = '-'.join((register['extensionId'], register['hostId']))
            # key = register['extensionId']
            if key in clients:
                logging.warning('replacing register %s with %s', key, addr)
                clients[key].writer.close()
            clients[key] = client
        while True:
            j = await read_a_messagae(reader)
            if not 'extensionId' in j:
                send_err(writer, 5, 'no extensionId in json')
                continue
            if not 'hostId' in j:
                send_err(writer, 6, 'no hostId in json')
                continue
            if not 'message' in j:
                send_err(writer, 7, 'no message in json')
                continue
            write_a_message(stdout_writer, j)
            await stdout_writer.drain()
    except ConnectionError as ce:
        logging.warning('connection error in %s: %s', addr, str(ce))
        return
    except asyncio.IncompleteReadError:
        return
    except InvalidMessageHeaderError as msg_hdr_err:
        send_err(writer, 1, "invalid message length: {}".format(msg_hdr_err.msg_l))
        return
    except UnicodeError:
        send_err(writer, 2, "failed to decode message")
        return
    except json.JSONDecodeError as jde:
        send_err(writer, 3, "failed to parse json message: {}".format(jde.msg))
        return
    finally:
        if client:
            for key in list(clients):
                if clients[key] == client:
                    del clients[key]
        writer.close()
        try:
            await writer.wait_closed()
        except:
            pass

async def handle_stdin(stdin_reader, server, clients):
    try:
        while True:
            data = await stdin_reader.readexactly(4)
            msg_l = struct.unpack('=I', data)[0]
            logging.debug('message length from chrome: %d', msg_l)
            data = await stdin_reader.readexactly(msg_l)
            try:
                msg = data.decode()
                logging.debug('message from chrome:%s', msg)
                j = json.loads(msg)
            except UnicodeError:
                logging.error('failed to decode message from chrome:%s', data.hex())
                continue
            except json.JSONDecodeError:
                logging.error('failed to parse json message:%s', msg)
                continue

            if not 'extensionId' in j:
                logging.warning('no extensionId in json from chrome')
                continue
            if not 'hostId' in j:
                logging.warning('no hostId in json from chrome')
                continue
            if not 'message' in j:
                logging.warning('no message in json from chrome')
                continue
            # find the client, send message
            key = '-'.join((j['extensionId'], j['hostId']))
            # key = j['extensionId']
            if not key in clients:
                logging.debug('no client registered for %s', key)
                continue
            client = clients[key]
            write_a_message(client.writer, j['message'])
            await client.writer.drain()
    except asyncio.IncompleteReadError as incomplete_err:
        # EOF read
        logging.info('EOF from chrome, shutdown')
        server.close()
        # shutdown and close all connections
        aws = set()
        for key in list(clients):
            client = clients[key]
            client.writer.close()
            aws.add(client.writer.wait_closed())
        asyncio.wait(aws)

async def main():
    '''
    start server
    '''
    loop = asyncio.get_event_loop()
    stdin_reader = asyncio.StreamReader(loop=loop)
    stdin_protocol = asyncio.StreamReaderProtocol(stdin_reader)
    await loop.connect_read_pipe(lambda: stdin_protocol, sys.stdin)
    wt, wp = await loop.connect_write_pipe(lambda: FlowControlMixin(loop=loop), sys.stdout)
    stdout_writer = asyncio.StreamWriter(wt, wp, None, loop)

    clients={}
    server = await asyncio.start_server(
        functools.partial(handle_client, stdout_writer=stdout_writer, clients=clients),
        '127.0.0.1',
        31888)

    async with server:
        await asyncio.wait({server.serve_forever(), handle_stdin(stdin_reader, server, clients)})

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
