import socket
# from torrent import Torrent
from bcoding import bdecode, bencode
import requests
import hashlib
from struct import pack, unpack
import math
import time

CHOKE_ID = 0
UNCHOKE_ID = 1
INTERESTED_ID = 2
NOT_INTERESTED_ID = 3
HAVE_ID = 4
BITFIELD_ID = 5
REQUEST_ID = 6
PIECE_ID = 7
CANCEL_ID = 8
BLOCK_SIZE = 2**14  # 16KB


class MetaInfo:
    def __init__(self, data):
        self.announce = data["announce"]
        self.announce_list = self.get_announce_list(data)
        self.info = data["info"]
        self.length = None
        self.files = None
        self.piece_length = self.info["piece length"]
        self.pieces = self.info["pieces"]
        self.info_hash = hashlib.sha1(bencode(data['info'])).digest()
        self.info_hash_hex = self.info_hash.hex()
        self.peer_id = self.generate_peer_id()

        # handle single file or multi files
        self.handle_multi_files()

    def get_piece_hashes(self):
        return [self.pieces[i: i + 20] for i in range(0, len(self.pieces), 20)]

    def get_announce_list(self, data):
        announce_list = []

        if 'announce-list' in data:
            for tracker_list in data['announce-list']:
                announce_list.append(tracker_list[0])
        else:
            announce_list.append(data['announce'])

        return announce_list

    def handle_multi_files(self):
        if 'files' in self.info:
            self.files = self.info['files']
            self.length = sum([file['length'] for file in self.files])

        else:
            self.files = [{'length': self.length, 'path': [self.info['name']]}]
            self.length = self.info['length']

    def generate_peer_id(self):
        seed = str(time.time())
        return hashlib.sha1(seed.encode('utf-8')).digest()


class Tracker:
    def __init__(self, announce_list):
        self.announce_list = announce_list
        self.peers = []

    def connect(self, info_hash, peer_id, port, uploaded, downloaded, left):
        params = {
            'info_hash': info_hash,
            'peer_id': peer_id,
            'port': port,
            'uploaded': uploaded,
            'downloaded': downloaded,
            'left': left,
            'compact': 1,
            'event': 'started'  # Notify the tracker that we started downloading
        }
        for tracker_url in self.announce_list:
            if tracker_url.startswith("udp"):
                print("UDP trackers are not supported yet.")
                continue
            print("Connecting to tracker:", tracker_url)
            try:
                response = requests.get(tracker_url, params=params, timeout=5)
                if response.status_code == 200:
                    print("Connected to tracker successfully.")
                    content = bdecode(response.content)
                    # print()
                    self.get_peers_from_tracker_response(content['peers'])
            except Exception as e:
                print("Error connecting to tracker:", tracker_url, e)
                continue

    def handle_udp_tracker(self, tracker_url):
        pass

    def get_peers_from_tracker_response(self, peers_data):
        if isinstance(peers_data, list):
            for peer in peers_data:
                ip = peer['ip']
                port = peer['port']
                if (ip, port) not in self.peers:
                    self.peers.append(
                        (peer['ip'], peer['port']))
            return

        for i in range(0, len(peers_data), 6):
            try:
                ip = ".".join(str(byte) for byte in peers_data[i:i+4])
                port = int.from_bytes(peers_data[i+4:i+6], byteorder='big')
            except Exception as e:
                print(e)

            print(ip, port, 'hihi')
            if (ip, port) not in self.peers:
                self.peers.append((ip, port))


class Peer:
    def __init__(self, ip, port, info_hash):
        self.ip = ip
        self.port = port
        self.peer_id = None
        self.info_hash = info_hash
        self.socket = None
        self.bitfield = None
        self.am_choking = True
        self.am_interested = False
        self.peer_choking = True
        self.peer_interested = False
        self.handshake = None
        self.peer_socket = None

    def connect(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.socket.connect((self.ip, self.port))
            self.socket.settimeout(5)
        except socket.timeout:
            print(f"Connection timed out after 5 seconds for peer {
                  self.ip}:{self.port}")
        except Exception as e:
            print("Error connecting to peer:", self.ip, self.port, e)
            return
        finally:
            pass
        self.handshake = self.create_handshake()
        self.socket.sendall(self.handshake)
        response = self.socket.recv(68)
        # Kiểm tra phản hồi handshake
        if response[:20] != self.handshake[:20] or response[28:48] != self.info_hash:
            raise ValueError("Invalid handshake response")
        self.peer_id = response[48:]
        print("Handshake successful with peer:",
              self.ip, self.port, self.peer_id)
        print("Connected to peer:", self.ip, self.port, self.peer_id)

    def create_handshake(self):
        protocol = b"BitTorrent protocol"
        reserved = b"\x00" * 8
        protocol_length = pack('>B', len(protocol))
        handshake = protocol_length + protocol + \
            reserved + self.info_hash + self.peer_id
        return handshake

    def send_message(self, message_id, payload=None):
        if payload is None:
            message_length = pack('>I', 1)
            message = message_length + pack('>B', message_id)
            self.socket.sendall(message)

        else:
            message_length = pack('>I', 5 + len(payload))
            message = message_length + pack('>B', message_id) + payload
            self.socket.sendall(message)

    def receive_message(self):
        message_length = self.socket.recv(4)
        message_length = unpack('>I', message_length)[0]
        message_id = self.socket.recv(1)
        message_id = unpack('>B', message_id)[0]

        if message_id == CHOKE_ID:
            print("Received CHOKE message from peer.")
            self.peer_choking = True

        elif message_id == UNCHOKE_ID:
            print("Received UNCHOKE message from peer.")
            self.peer_choking = False

        elif message_id == INTERESTED_ID:
            print("Received INTERESTED message from peer.")
            self.peer_interested = True

        elif message_id == NOT_INTERESTED_ID:
            print("Received NOT INTERESTED message from peer.")
            self.peer_interested = False

        elif message_id == HAVE_ID:
            piece_index = self.socket.recv(4)
            piece_index = unpack('>I', piece_index)[0]
            print("Received HAVE message from peer. Piece index:", piece_index)

        elif message_id == BITFIELD_ID:
            bitfield_length = message_length - 1
            bitfield = self.socket.recv(bitfield_length)
            self.bitfield = bitfield
            print("Received BITFIELD message from peer. Bitfield:", bitfield)

        elif message_id == REQUEST_ID:
            piece_index = self.socket.recv(4)
            piece_index = unpack('>I', piece_index)[0]
            block_offset = self.socket.recv(4)
            block_offset = unpack('>I', block_offset)[0]
            block_length = self.socket.recv(4)
            block_length = unpack('>I', block_length)[0]
            print("Received REQUEST message from peer. Piece index:", piece_index,
                  "Block offset:", block_offset, "Block length:", block_length)

        elif message_id == PIECE_ID:
            piece_index = self.socket.recv(4)
            piece_index = unpack('>I', piece_index)[0]
            block_offset = self.socket.recv(4)
            block_offset = unpack('>I', block_offset)[0]
            block_length = message_length - 8
            block_data = self.socket.recv(block_length)
            print("Received PIECE message from peer. Piece index:", piece_index,
                  "Block offset:", block_offset, "Block length:", block_length)

        elif message_id == CANCEL_ID:
            piece_index = self.socket.recv(4)
            piece_index = unpack('>I', piece_index)[0]
            block_offset = self.socket.recv(4)
            block_offset = unpack('>I', block_offset)[0]
            block_length = self.socket.recv(4)
            block_length = unpack('>I', block_length)[0]
            print("Received CANCEL message from peer. Piece index:", piece_index,
                  "Block offset:", block_offset, "Block length:", block_length)

        else:
            print("Received unknown message from peer. Message ID:", message_id)


# class Piece:
#     def __init__(self, piece_index, piece_length):
#         self.piece_index = piece_index
#         self.piece_length = piece_length
#         self.blocks = [Block(i, BLOCK_SIZE) for i in range(
#             0, math.ceil(piece_length / BLOCK_SIZE))]
#         self.is_full = False

#     def update_block_status(self):
#         for block in self.blocks:
#             if block.state == State.EMPTY:
#                 block.state = State.REQUESTED
#                 return

#     def get_empty_block(self):
#         for i, block in enumerate(self.blocks):
#             if block.state == State.EMPTY:
#                 return (self.piece_index, i * BLOCK_SIZE, min(BLOCK_SIZE, self.piece_length - i * BLOCK_SIZE))
#         self.is_full = True
#         return None

def read_meta_info(path):
    with open(path, "rb") as f:
        data = bdecode(f.read())
        return data


def download():
    meta_info = MetaInfo(read_meta_info(
        "./Stein.C..Django.5.Cookbook..70+.problem.solving.techniques,...2024.torrent"))
    tracker = Tracker(meta_info.announce_list)
    tracker.connect(meta_info.info_hash, meta_info.peer_id,
                    6881, 0, 0, meta_info.length)

    peers = tracker.peers
    print(peers)
    # Connect to each peer
    for ip, port in peers:
        print("Connecting to peer:", ip, port)
        peer = Peer(ip, port, meta_info.info_hash)
        try:
            peer.connect()
            # Handle the peer connection here (e.g., send/receive messages)
            # ...
        except Exception as e:
            print(f"Error connecting to peer {ip}:{port} - {e}")

    # class Downloader:
    #     def __init__(self, torrent):
    #         self.torrent = torrent
    #         self.tracker_url_list = self.torrent.announce_list  # Use the first tracker URL
    #         self.peer_id = self.torrent.peer_id
    #         self.info_hash = self.torrent.info_hash
    #         self.peer_port = 6881  # Default peer port
    #         self.connected_peers = []
    #         self.peers = []
    #         self.connected_peers = []

    #     def connect_to_tracker(self):
    #         params = {
    #             'info_hash': self.info_hash,
    #             'peer_id': self.peer_id,
    #             'port': self.peer_port,
    #             'uploaded': 0,
    #             'downloaded': 0,
    #             'left': self.torrent.total_length,
    #             'compact': 1,
    #             'event': 'started'  # Notify the tracker that we started downloading
    #         }

    #         for tracker_url in self.tracker_url_list:
    #             if tracker_url.startswith("udp"):
    #                 print("UDP trackers are not supported yet.")
    #                 continue
    #             print("Connecting to tracker:", tracker_url)
    #             try:
    #                 response = requests.get(tracker_url, params=params, timeout=5)
    #                 if response.status_code == 200:
    #                     print("Connected to tracker successfully.")
    #                     content = bdecode(response.content)
    #                     self.get_peers_from_tracker_response(content['peers'])
    #                 else:
    #                     print("Failed to con  nect to tracker:", tracker_url)
    #                     continue
    #             except Exception as e:
    #                 print("Error connecting to tracker:", tracker_url, e)
    #                 continue

    #         print("Found", len(self.peers), "peers from tracker.")
    #         print("Peers:", self.peers)

    #     def get_peers_from_tracker_response(self, peers_data):
    #         if isinstance(peers_data, list):
    #             for peer in peers_data:
    #                 ip = peer['ip']
    #                 port = peer['port']
    #                 peer_id = peer['peer id']
    #                 if (ip, port, peer_id) not in self.peers:
    #                     self.peers.append(
    #                         (peer['ip'], peer['port'], peer['peer id']))
    #             return

    #         for i in range(0, len(peers_data), 6):
    #             ip = ".".join(str(byte) for byte in peers_data[i:i+4])
    #             port = int.from_bytes(peers_data[i+4:i+6], byteorder='big')
    #             peer_id = peers_data[i+6:i+26].decode('utf-8')
    #             if (ip, port, peer_id) not in self.peers:
    #                 self.peers.append((ip, port, peer_id))

    #     def connect_to_peers(self):
    #         print("Connecting to peers...")
    #         protocol = b"BitTorrent protocol"
    #         reserved = b"\x00" * 8
    #         protocol_length = pack('>B', len(protocol))
    #         handshake = protocol_length + protocol + \
    #             reserved + self.info_hash + self.peer_id

    #         for peer in self.peers:
    #             ip = peer[0]
    #             port = peer[1]
    #             print("Connecting to peer:", ip, port)
    #             peer_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    #             try:
    #                 peer_socket.connect((ip, port))
    #                 print("Connected to peer:", ip, port)
    #                 peer_socket.sendall(handshake)
    #                 response = peer_socket.recv(68)
    #                 connected_peer_id = response[48:]
    #                 # print(peer_id.hex())
    #                 peer_socket.close()
    #                 return connected_peer_id

    #             except Exception as e:
    #                 print("Error connecting to peer:", ip, port, e)
    #                 continue

    #     # def download(self, peer_socket):
    #     #     print("Starting download...")

    #     #     print("Download completed.")


    #     def start(self):
    #         # Start the downloading process
    #         self.connect_to_tracker()
    #         self.connect_to_peers()
if __name__ == "__main__":
    download()
# 14.186.94.68 6881
