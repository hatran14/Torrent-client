import peer
import logging
from bcoding import bdecode, bencode
import socket

MAX_PEERS_TRY_CONNECT = 30
MAX_PEERS_CONNECTED = 8

class SockAddr:
    def __init__(self, ip, port, allowed=True):
        self.ip = ip
        self.port = port
        self.allowed = allowed

    def __hash__(self):
        return "%s:%d" % (self.ip, self.port)

class Tracker(object):
    def __init__(self, torrent):
        self.torrent = torrent
        self.threads_list = []
        self.connected_peers = {}
        self.dict_sock_addr = {}

    def get_peers_from_trackers(self, try_connect = True, listen_port = 1234):
        for i, tracker in enumerate(self.torrent.announce_list):
            if len(self.dict_sock_addr) >= MAX_PEERS_TRY_CONNECT:
                break

            tracker_url = tracker[0]
            try:
                self.scraper(self.torrent, tracker_url, listen_port)
            except Exception as e:
                logging.error("Scraping failed: %s " % e.__str__())

        if try_connect:
            self.try_peer_connect()

        return self.connected_peers

    def try_peer_connect(self):
        logging.debug("Trying to connect to %d peer(s)" % len(self.dict_sock_addr))
        
        for _, sock_addr in self.dict_sock_addr.items():
            if len(self.connected_peers) >= MAX_PEERS_CONNECTED:
                break
            new_peer = peer.Peer(int(self.torrent.number_of_pieces), sock_addr.ip, sock_addr.port, self.torrent.name)
            if new_peer.hash() not in self.connected_peers:
                if new_peer.connect():
                    self.connected_peers[new_peer.hash()] = new_peer
        
        logging.debug('Connected to %d/%d peers' % (len(self.connected_peers), MAX_PEERS_CONNECTED))

    def scraper(self, torrent, tracker, listen_port):
        params = {
            'info_hash': torrent.info_hash,
            'peer_id': torrent.peer_id,
            'uploaded': 0,
            'downloaded': 0,
            'port': listen_port,
            'left': torrent.total_length,
            'event': 'started'
        }

        try:
            server_addr = tracker.split(":")
            server_socket = socket.socket()
            server_socket.connect((server_addr[0], int(server_addr[1])))
            server_socket.sendall(bencode(params))
            answer_tracker = server_socket.recv(1024)
            list_peers = bdecode(answer_tracker)
            # server_socket.close()
            
            for p in list_peers['peers']:
                s = SockAddr(p['ip'], p['port'])
                self.dict_sock_addr[s.__hash__()] = s
        
        except Exception as e:
            logging.exception("Scraping failed: %s" % e.__str__())

if __name__ == '__main__':
    from torrent import Torrent
    torrent = Torrent().load_from_path("test/test.torrent")
    Tracker(torrent).get_peers_from_trackers()