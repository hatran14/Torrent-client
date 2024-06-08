import logging
from struct import pack, unpack

# HandShake - String identifier of the protocol for BitTorrent V1
import bitstring

HANDSHAKE_PSTR_V1 = b"BitTorrent protocol"
HANDSHAKE_PSTR_LEN = len(HANDSHAKE_PSTR_V1)
LENGTH_PREFIX = 4


class WrongMessageException(Exception):
    pass


class MessageDispatcher:
    def __init__(self, payload):
        self.payload = payload

    def dispatch(self):
        try:
            payload_length, message_id, = unpack(">IB", self.payload[:5])
        except Exception as e:
            logging.warning("Error when unpacking message : %s" % e.__str__())
            return None

        map_id_to_message = {
            4: Have,
            5: BitField,
            6: Request,
            7: Piece,
        }

        if message_id not in list(map_id_to_message.keys()):
            raise WrongMessageException("Wrong message id")

        return map_id_to_message[message_id].from_bytes(self.payload)

"""
    Bittorrent messages
"""

class Message:
    def to_bytes(self):
        raise NotImplementedError()

    @classmethod
    def from_bytes(cls, payload):
        raise NotImplementedError()

class Handshake:
    """
        Handshake = <pstrlen><pstr><reserved><info_hash><peer_id>
            - pstrlen = length of pstr (1 byte)
            - pstr = string identifier of the protocol: "BitTorrent protocol" (19 bytes)
            - reserved = 8 reserved bytes indicating extensions to the protocol (8 bytes)
            - info_hash = hash of the value of the 'info' key of the torrent file (20 bytes)
            - peer_id = unique identifier of the Peer (20 bytes)

        Total length = payload length = 49 + len(pstr) = 68 bytes (for BitTorrent v1)
    """
    payload_length = 68
    total_length = payload_length

    def __init__(self, info_hash, peer_id=b'-ZZ0007-000000000000'):
        super(Handshake, self).__init__()
        assert len(info_hash) == 20
        assert len(peer_id) < 255
        self.peer_id = peer_id
        self.info_hash = info_hash

    def to_bytes(self):
        reserved = b'\x00' * 8
        handshake = pack(">B{}s8s20s20s".format(HANDSHAKE_PSTR_LEN),
                        HANDSHAKE_PSTR_LEN,
                        HANDSHAKE_PSTR_V1,
                        reserved,
                        self.info_hash,
                        self.peer_id)
        return handshake

    @classmethod
    def from_bytes(cls, payload):
        pstrlen, = unpack(">B", payload[:1])
        pstr, reserved, info_hash, peer_id = unpack(">{}s8s20s20s".format(pstrlen), payload[1:cls.total_length])

        if pstr != HANDSHAKE_PSTR_V1:
            raise ValueError("Invalid string identifier of the protocol")

        return Handshake(info_hash, peer_id)


class KeepAlive:
    """
        KEEP_ALIVE = <length>
            - payload length = 0 (4 bytes)
    """
    payload_length = 0
    total_length = 4

    def __init__(self):
        super(KeepAlive, self).__init__()

    def to_bytes(self):
        return pack(">I", self.payload_length)

    @classmethod
    def from_bytes(cls, payload):
        payload_length = unpack(">I", payload[:cls.total_length])

        if payload_length != 0:
            raise WrongMessageException("Not a Keep Alive message")

        return KeepAlive()


class Have:
    """
        HAVE = <length><message_id><piece_index>
            - payload length = 5 (4 bytes)
            - message_id = 4 (1 byte)
            - piece_index = zero based index of the piece (4 bytes)
    """
    message_id = 4

    payload_length = 5
    total_length = 4 + payload_length

    def __init__(self, piece_index):
        super(Have, self).__init__()
        self.piece_index = piece_index

    def to_bytes(self):
        pack(">IBI", self.payload_length, self.message_id, self.piece_index)

    @classmethod
    def from_bytes(cls, payload):
        payload_length, message_id, piece_index = unpack(">IBI", payload[:cls.total_length])
        if message_id != cls.message_id:
            raise WrongMessageException("Not a Have message")

        return Have(piece_index)


class BitField:
    """
        BITFIELD = <length><message id><bitfield>
            - payload length = 1 + bitfield_size (4 bytes)
            - message id = 5 (1 byte)
            - bitfield = bitfield representing downloaded pieces (bitfield_size bytes)
    """
    message_id = 5

    # Unknown until given a bitfield
    payload_length = -1
    total_length = -1

    def __init__(self, bitfield):  # bitfield is a bitstring.BitArray
        super(BitField, self).__init__()
        self.bitfield = bitfield
        self.bitfield_as_bytes = bitfield.tobytes()
        self.bitfield_length = len(self.bitfield_as_bytes)

        self.payload_length = 1 + self.bitfield_length
        self.total_length = 4 + self.payload_length

    def to_bytes(self):
        return pack(">IB{}s".format(self.bitfield_length),
                    self.payload_length,
                    self.message_id,
                    self.bitfield_as_bytes)

    @classmethod
    def from_bytes(cls, payload):
        payload_length, message_id = unpack(">IB", payload[:5])
        bitfield_length = payload_length - 1

        if message_id != cls.message_id:
            raise WrongMessageException("Not a BitField message")

        raw_bitfield, = unpack(">{}s".format(bitfield_length), payload[5:5 + bitfield_length])
        bitfield = bitstring.BitArray(bytes=bytes(raw_bitfield))

        return BitField(bitfield)


class Request:
    """
        REQUEST = <length><message id><piece index><block offset><block length>
            - payload length = 13 (4 bytes)
            - message id = 6 (1 byte)
            - piece index = zero based piece index (4 bytes)
            - block offset = zero based of the requested block (4 bytes)
            - block length = length of the requested block (4 bytes)
    """
    message_id = 6

    payload_length = 13
    total_length = 4 + payload_length

    def __init__(self, piece_index, block_offset, block_length):
        super(Request, self).__init__()

        self.piece_index = piece_index
        self.block_offset = block_offset
        self.block_length = block_length

    def to_bytes(self):
        return pack(">IBIII",
                    self.payload_length,
                    self.message_id,
                    self.piece_index,
                    self.block_offset,
                    self.block_length)

    @classmethod
    def from_bytes(cls, payload):
        payload_length, message_id, piece_index, block_offset, block_length = unpack(">IBIII",
                                                                                    payload[:cls.total_length])
        if message_id != cls.message_id:
            raise WrongMessageException("Not a Request message")

        return Request(piece_index, block_offset, block_length)


class Piece:
    """
        PIECE = <length><message id><piece index><block offset><block>
        - length = 9 + block length (4 bytes)
        - message id = 7 (1 byte)
        - piece index =  zero based piece index (4 bytes)
        - block offset = zero based of the requested block (4 bytes)
        - block = block as a bytestring or bytearray (block_length bytes)
    """
    message_id = 7

    payload_length = -1
    total_length = -1

    def __init__(self, block_length, piece_index, block_offset, block):
        super(Piece, self).__init__()

        self.block_length = block_length
        self.piece_index = piece_index
        self.block_offset = block_offset
        self.block = block

        self.payload_length = 9 + block_length
        self.total_length = 4 + self.payload_length

    def to_bytes(self):
        return pack(">IBII{}s".format(self.block_length),
                    self.payload_length,
                    self.message_id,
                    self.piece_index,
                    self.block_offset,
                    self.block)

    @classmethod
    def from_bytes(cls, payload):
        block_length = len(payload) - 13
        payload_length, message_id, piece_index, block_offset, block = unpack(">IBII{}s".format(block_length),
                                                                            payload[:13 + block_length])

        if message_id != cls.message_id:
            raise WrongMessageException("Not a Piece message")

        return Piece(block_length, piece_index, block_offset, block)