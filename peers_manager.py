from threading import Thread, Event, Lock
from pubsub import pub
import logging
import message
import peer
import random
import time

class PeersManager(Thread):
    def __init__(self, torrent, pieces_manager):
        Thread.__init__(self)
        self.peers = []
        self.torrent = torrent
        self.pieces_manager = pieces_manager
        self.pieces_by_peer = [[0, []] for _ in range(pieces_manager.number_of_pieces)]
        self.is_active = True
        self.event = Event()
        self.lock = Lock()
        self.queue = []
        self.num_threads = 0

        # Events
        pub.subscribe(self.peer_requests_piece, f"{self.torrent.name}.PeerRequestsPiece")
        pub.subscribe(self.peers_bitfield, f"{self.torrent.name}.updatePeersBitfield")

    def peer_requests_piece(self, request=None, peer=None):
        if not request or not peer:
            logging.error("empty request/peer message")

        piece_index, block_offset, block_length = request.piece_index, request.block_offset, request.block_length

        if piece_index < 0 or piece_index >= self.pieces_manager.number_of_pieces:
            return
        
        self.lock.acquire()
        self.queue.append((request, peer))
        self.lock.release()
        self.event.set()

    def peers_bitfield(self, bitfield=None):
        for i in range(len(self.pieces_by_peer)):
            if bitfield[i] == 1 and peer not in self.pieces_by_peer[i][1] and self.pieces_by_peer[i][0]:
                self.pieces_by_peer[i][1].append(peer)
                self.pieces_by_peer[i][0] = len(self.pieces_by_peer[i][1])

    def get_peers_having_piece(self, index):
        ready_peers = []

        for peer in self.peers:
            if peer.has_piece(index) and peer.healthy:
                ready_peers.append(peer)

        return ready_peers

    def run(self):
        while self.is_active:
            self.event.wait()

            while len(self.queue) and self.num_threads < 3:
                self.lock.acquire()
                request, peer = self.queue.pop(0)
                self.num_threads += 1
                self.lock.release()
                t = Thread(target=self.send_piece_to_peer, args=(request, peer,))
                t.daemon = True
                t.start()
                
    def send_piece_to_peer(self, request, peer):
        piece_index, block_offset, block_length = request.piece_index, request.block_offset, request.block_length
        piece = self.pieces_manager.pieces[piece_index]._read_piece_on_disk()                
        block = piece[block_offset : block_offset + block_length]
        if block:
            piece = message.Piece(block_length, piece_index, block_offset, block).to_bytes()
            code = peer.send_to_peer(piece)
            while code == 1:
                time.sleep(2)
                code = peer.send_to_peer(piece)
            if code == 0:
                logging.info("Sent piece index {} to peer : {}".format(request.piece_index, peer.ip))
        self.lock.acquire()
        self.num_threads -= 1
        self.lock.release()

    def _do_handshake(self, peer):
        try:
            handshake = message.Handshake(self.torrent.info_hash)
            peer.send_to_peer(handshake.to_bytes())
            logging.info("new peer added : %s" % peer.ip)
            return True

        except Exception:
            logging.exception("Error when sending Handshake message")

        return False

    def add_peers(self, peers):
        for peer in peers:
            if peer not in self.peers:
                if self._do_handshake(peer):
                    peer.start()
                    self.peers.append(peer)
                else:
                    print("Error _do_handshake")

    def remove_peer(self, peer):
        if peer in self.peers:
            try:
                peer.stop()
                peer.socket.close()
                logging.debug("remove_peer: %s" % peer.ip)
            except Exception:
                logging.exception("remove_peer failed: %s" % peer.ip)

            self.peers.remove(peer)

    def get_peer_by_socket(self, socket):
        for peer in self.peers:
            if socket == peer.socket:
                return peer

        raise Exception("Peer not present in peer_list")

    def unsub(self):
        pub.unsubscribe(self.peer_requests_piece, f'{self.torrent.name}.PeerRequestsPiece')
        pub.unsubscribe(self.peers_bitfield, f'{self.torrent.name}.updatePeersBitfield')