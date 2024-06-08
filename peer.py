import socket
import struct
import bitstring
from pubsub import pub
import logging
import message
import errno
import select
from threading import Thread, Lock, Event
from block import BLOCK_SIZE

class Peer(Thread):
    def __init__(self, number_of_pieces, ip, port, topic):
        Thread.__init__(self)
        self.last_call = False
        self.has_handshaked = False
        self.healthy = False
        self.read_buffer = b''
        self.socket = None
        self.ip = ip
        self.port = port
        self.number_of_pieces = number_of_pieces
        self.bit_field = bitstring.BitArray(number_of_pieces)
        self.is_active = True
        self.topic = topic

        self.event = Event()
        self.lock = Lock()

    def hash(self):
        return "%s:%d" % (self.ip, self.port)

    def connect(self):
        try:
            self.socket = socket.socket()
            self.socket.connect((self.ip, self.port))
            self.socket.setblocking(False)
            logging.debug("Connected to peer ip: {} - port: {}".format(self.ip, self.port))
            self.healthy = True

        except Exception as e:
            logging.debug("Failed to connect to peer (ip: %s - port: %s - %s)" % (self.ip, self.port, e.__str__()))
            return False

        return True

    def send_to_peer(self, msg):
        # Use select to wait until the socket is writable
        _, writable_sockets, _ = select.select([], [self.socket], [])
        if self.socket in writable_sockets:
            try:
                self.socket.send(msg)
                return 0
            except socket.error as e:
                if e.errno == errno.WSAEWOULDBLOCK:
                    logging.debug("Socket not ready")
                    return 1
                else:
                    self.healthy = False
                    logging.error("Failed to send to peer : %s" % e.__str__())
                    return -1
    
    def is_eligible(self):
        if self.last_call:
            self.last_call = False
            return False
        self.last_call = True
        return True

    def has_piece(self, index):
        return self.bit_field[index]

    def handle_have(self, have):
        """
        :type have: message.Have
        """
        logging.debug('handle_have - ip: %s - piece: %s' % (self.ip, have.piece_index))
        self.bit_field[have.piece_index] = True

    def handle_bitfield(self, bitfield):
        """
        :type bitfield: message.BitField
        """
        logging.debug('handle_bitfield - %s - %s' % (self.ip, bitfield.bitfield))
        self.bit_field = bitfield.bitfield
    
    def handle_request(self, request):
        """
        :type request: message.Request
        """
        logging.debug('handle_request - %s' % self.ip)
        pub.sendMessage(f'{self.topic}.PeerRequestsPiece', request=request, peer=self)

    def handle_piece(self, message):
        """
        :type message: message.Piece
        """
        pub.sendMessage(f'{self.topic}.Piece', piece=(message.piece_index, message.block_offset, message.block))

    def _handle_handshake(self):
        try:
            handshake_message = message.Handshake.from_bytes(self.read_buffer)
            self.has_handshaked = True
            self.read_buffer = self.read_buffer[handshake_message.total_length:]
            logging.debug('handle_handshake - %s' % self.ip)
            return True

        except Exception:
            logging.exception("First message should always be a handshake message")
            self.healthy = False

        return False

    def _handle_keep_alive(self):
        try:
            keep_alive = message.KeepAlive.from_bytes(self.read_buffer)
            logging.debug('handle_keep_alive - %s' % self.ip)
        except message.WrongMessageException:
            return False
        except Exception:
            logging.exception("Error KeepALive, (need at least 4 bytes : {})".format(len(self.read_buffer)))
            return False

        self.read_buffer = self.read_buffer[keep_alive.total_length:]
        return True

    def get_messages(self):
        """
        All of the remaining messages in the protocol take the form of <length prefix><message ID><payload>. 
        The length prefix is a four byte big-endian value. 
        The message ID is a single decimal byte. 
        The payload is message dependent
        """
        while self.is_active:
            self.event.wait()
            while len(self.read_buffer) > 4 and self.healthy:
                if (not self.has_handshaked and self._handle_handshake()) or self._handle_keep_alive():
                    continue

                payload_length, = struct.unpack(">I", self.read_buffer[:4])
                total_length = payload_length + 4

                if len(self.read_buffer) < total_length:
                    break
                else:
                    payload = self.read_buffer[:total_length]
                    self.lock.acquire()
                    self.read_buffer = self.read_buffer[total_length:]
                    self.lock.release()

                try:
                    received_message = message.MessageDispatcher(payload).dispatch()
                    if received_message:
                        self._process_new_message(received_message)
                except message.WrongMessageException as e:
                    logging.exception(e.__str__())

    def run(self):
        t = Thread(target=self.get_messages)
        t.daemon = True
        t.start()

        while self.is_active:
            read_list, _, _ = select.select([self.socket], [], [])
            if self.socket in read_list:
                data = []
                while 1:
                    try:
                        buff = self.socket.recv(BLOCK_SIZE)
                        if len(buff) <= 0:
                            break
                        data.append(buff)
                    except socket.error as e:
                        err = e.args[0]
                        if err != errno.EAGAIN and err != errno.EWOULDBLOCK:
                            logging.debug("Wrong errno {}".format(err))
                            self.stop()
                        break
                    except Exception:
                        logging.exception("Recv failed")
                        break
                
                self.lock.acquire()
                self.read_buffer += (b''.join(data))
                self.lock.release()
                self.event.set()

    def _process_new_message(self, new_message: message.Message):
        if isinstance(new_message, message.Handshake) or isinstance(new_message, message.KeepAlive):
            logging.error("Handshake or KeepALive should have already been handled")

        elif isinstance(new_message, message.Have):
            self.handle_have(new_message)

        elif isinstance(new_message, message.BitField):
            self.handle_bitfield(new_message)

        elif isinstance(new_message, message.Request):
            self.handle_request(new_message)

        elif isinstance(new_message, message.Piece):
            self.handle_piece(new_message)

        else:
            logging.error("Unknown message")

    def stop(self):
        self.is_active = False
