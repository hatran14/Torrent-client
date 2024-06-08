import hashlib
import math
import time
import logging
from pubsub import pub
from block import Block, BLOCK_SIZE, State
from threading import Thread

class Piece:
    def __init__(self, piece_index: int, piece_size: int, piece_hash: str, topic: str):
        self.piece_index: int = piece_index
        self.piece_size: int = piece_size
        self.piece_hash: str = piece_hash
        self.is_full: bool = False
        self.files = []
        self.raw_data: bytes = b''
        self.number_of_blocks: int = int(math.ceil(float(piece_size) / BLOCK_SIZE))
        self.blocks: list[Block] = []
        self.number_of_full_blocks = 0
        self.topic = topic

        self._init_blocks()

    def update_block_status(self):  # if block is pending for too long : set it free
        for i, block in enumerate(self.blocks):
            if block.state == State.PENDING and (time.time() - block.last_seen) > 120:
                self.blocks[i] = Block()

    def set_block(self, offset, data):
        index = int(offset / BLOCK_SIZE)

        if index < 0 or index >= self.number_of_blocks:
            return

        if not self.is_full and not self.blocks[index].state == State.FULL:
            self.blocks[index].data = data
            self.blocks[index].state = State.FULL
            self.number_of_full_blocks += 1

    def get_block(self, block_offset, block_length):
        return self.raw_data[block_offset:block_length]

    def get_empty_block(self):
        if self.is_full:
            return None

        for block_index, block in enumerate(self.blocks):
            if block.state == State.FREE:
                self.blocks[block_index].state = State.PENDING
                self.blocks[block_index].last_seen = time.time()
                return self.piece_index, block_index * BLOCK_SIZE, block.block_size

        return None

    def are_all_blocks_full(self):
        return (self.number_of_blocks == self.number_of_full_blocks)

    def set_to_full(self):
        self.raw_data = self._merge_blocks()

        if not self._valid_blocks(self.raw_data):
            self._init_blocks()
            return False

        self.is_full = True
        pub.sendMessage(f"{self.topic}.PieceCompleted", piece_index=self.piece_index)
        logging.debug("Set piece {} to full".format(self.piece_index))
        self._write_piece_on_disk()
        return True

    def _init_blocks(self):
        self.blocks = []

        if self.number_of_blocks > 1:
            for i in range(self.number_of_blocks):
                self.blocks.append(Block())

            # Last block of last piece, the special block
            if (self.piece_size % BLOCK_SIZE) > 0:
                self.blocks[self.number_of_blocks - 1].block_size = self.piece_size % BLOCK_SIZE

        else:
            self.blocks.append(Block(block_size=int(self.piece_size)))

    def _write_piece_on_disk(self):
        for file in self.files:
            path_file = file["path"]
            file_offset = file["fileOffset"]
            piece_offset = file["pieceOffset"]
            length = file["length"]

            try:
                with open(path_file, 'r+b') as f:  # Already existing file
                    f.seek(file_offset)
                    f.write(self.raw_data[piece_offset:piece_offset + length])
            except IOError:
                try:
                    with open(path_file, 'wb') as f:  # New file
                        f.seek(file_offset)
                        f.write(self.raw_data[piece_offset:piece_offset + length])
                except IOError:
                    logging.exception("Can't write to file")
                    return
            except Exception:
                logging.exception("Can't write to file")
                return

    def _read_piece_on_disk(self):
        piece = []
        for file in self.files:
            path_file = file["path"]
            file_offset = file["fileOffset"]
            length = file["length"]

            try:
                f = open(path_file, 'r+b')  # Already existing file
                f.seek(file_offset)
                piece.append(f.read(length))
            except Exception:
                logging.exception("Can't read file")
        
        return b''.join(piece)

    def _merge_blocks(self):
        buf = []

        for block in self.blocks:
            buf.append(block.data)

        return b''.join(buf)

    def _valid_blocks(self, piece_raw_data):
        hashed_piece_raw_data = hashlib.sha1(piece_raw_data).digest()

        if hashed_piece_raw_data == self.piece_hash:
            return True

        logging.warning("Error Piece Hash")
        logging.debug("{} : {}".format(hashed_piece_raw_data, self.piece_hash))
        return False
    
    def clear(self):
        self.raw_data: bytes = b''
        for block in self.blocks:
            block.data = b''
