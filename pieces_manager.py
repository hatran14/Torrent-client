import piece
import bitstring
import logging
from pubsub import pub
from threading import Thread, Event, Lock

class PiecesManager(Thread):
    def __init__(self, torrent):
        Thread.__init__(self)
        self.torrent = torrent
        self.number_of_pieces = int(torrent.number_of_pieces)
        self.bitfield = bitstring.BitArray(self.number_of_pieces)
        self.pieces = self._generate_pieces()
        self.files = self._load_files()
        self.complete_pieces = 0
        self.event = Event()
        self.lock = Lock()
        self.queue = []
        self.num_threads = 0

        for file in self.files:
            id_piece = file['idPiece']
            self.pieces[id_piece].files.append(file)

        # events
        pub.subscribe(self.receive_block_piece, f"{self.torrent.name}.Piece")
        pub.subscribe(self.update_bitfield, f"{self.torrent.name}.PieceCompleted")

    def update_bitfield(self, piece_index):
        if piece_index >= 0 and piece_index < self.number_of_pieces:
            self.bitfield[piece_index] = 1

    def receive_block_piece(self, piece):
        piece_index, piece_offset, piece_data = piece

        if piece_index < 0 or piece_index >= self.number_of_pieces:
            return

        if self.pieces[piece_index].is_full:
            logging.debug("Receive piece {} again".format(piece_index))
            return

        self.pieces[piece_index].set_block(piece_offset, piece_data)

        if self.pieces[piece_index].are_all_blocks_full():
            self.lock.acquire()
            self.queue.append(piece_index)
            self.lock.release()
            self.event.set()

    def get_block(self, piece_index, block_offset, block_length):
        for piece in self.pieces:
            if piece_index == piece.piece_index:
                if piece.is_full:
                    return piece.get_block(block_offset, block_length)
                else:
                    break

        return None

    def all_pieces_completed(self):
        return (self.complete_pieces == self.number_of_pieces)

    def _generate_pieces(self):
        pieces = []
        start = 0
        end = 20
        last_piece = self.number_of_pieces - 1

        for i in range(self.number_of_pieces - 1):
            start = i * 20
            end = start + 20
            pieces.append(piece.Piece(i, self.torrent.piece_length, self.torrent.pieces[start:end], self.torrent.name))
        
        # Handle last piece
        piece_length = self.torrent.total_length - (self.number_of_pieces - 1) * self.torrent.piece_length
        pieces.append(piece.Piece(self.number_of_pieces - 1, piece_length, self.torrent.pieces[last_piece * 20:], self.torrent.name))

        return pieces

    def _load_files(self):
        files = []
        piece_offset = 0
        piece_size_used = 0

        for f in self.torrent.file_names:
            current_size_file = f["length"]
            file_offset = 0

            while current_size_file > 0:
                id_piece = int(piece_offset / self.torrent.piece_length)
                piece_size = self.pieces[id_piece].piece_size - piece_size_used

                if current_size_file - piece_size < 0:
                    file = {"length": current_size_file,
                            "idPiece": id_piece,
                            "fileOffset": file_offset,
                            "pieceOffset": piece_size_used,
                            "path": f["path"]
                            }
                    piece_offset += current_size_file
                    file_offset += current_size_file
                    piece_size_used += current_size_file
                    current_size_file = 0

                else:
                    current_size_file -= piece_size
                    file = {"length": piece_size,
                            "idPiece": id_piece,
                            "fileOffset": file_offset,
                            "pieceOffset": piece_size_used,
                            "path": f["path"]
                            }
                    piece_offset += piece_size
                    file_offset += piece_size
                    piece_size_used = 0

                files.append(file)
        return files
    
    def unsub(self):
        pub.unsubscribe(self.receive_block_piece, f'{self.torrent.name}.Piece')
        pub.unsubscribe(self.update_bitfield, f'{self.torrent.name}.PieceCompleted')

    def run(self):
        while self.number_of_pieces != self.complete_pieces:
            self.event.wait()
            
            while len(self.queue) and self.num_threads < 4:
                self.lock.acquire()
                piece_index = self.queue.pop(0)
                self.num_threads += 1
                self.lock.release()
                t = Thread(target=self.set_piece_to_full, args=(piece_index,))
                t.daemon = True
                t.start()

    def set_piece_to_full(self, piece_index):
        if self.pieces[piece_index].set_to_full():
            self.lock.acquire()
            self.complete_pieces += 1
            self.lock.release()
            self.pieces[piece_index].clear()
        
        self.lock.acquire()
        self.num_threads -= 1
        self.lock.release()