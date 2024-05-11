import socket
# from torrent import Torrent
from bcoding import bdecode, bencode
import requests
import hashlib
from struct import pack, unpack
import math
import time
import struct
import random
from PyBitTorrent import TorrentClient

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

class PeerProtocol:
    def __init__(self, request_data):
        self.request_data = request_data
    
    def connection_made(self, transport):
        # Gửi yêu cầu khi kết nối được thiết lập
        transport.sendto(self.request_data)
    
    def datagram_received(self, data, addr):
        # Xử lý phản hồi từ tracker
        # Đảm bảo xử lý dữ liệu phản hồi theo định dạng bạn mong đợi từ tracker
        peers = []
        for i in range(0, len(data), 6):
            ip = socket.inet_ntoa(data[i:i+4])
            port = struct.unpack("!H", data[i+4:i+6])[0]
            self.peer.append((ip, port))
        print("List of peers:", peers)

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
                print("Connecting to tracker:", tracker_url)
                try:
                    # Create a UDP socket
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.settimeout(5)  # Set a timeout for receiving responses

                    # Send request to tracker
                    ip = tracker_url.split('//')[1].split(':')[0]
                    port = int(tracker_url.split('//')[1].split(':')[1].split('/')[0])
                    sock.connect((ip, port))

                    protocol_id = 0x41727101980  # default protocol id for all torrent clients
                    action = 0  # 0 for connect action
                    transaction_id = 12345  # random number
                    message = struct.pack('!qii', protocol_id, action, transaction_id)
                    sock.send(message)
                
                    response = sock.recv(16)
                    action, transaction_id, connection_id = struct.unpack('!iiq', response)
                    
                    key = random.getrandbits(32)
                    num_want = -1
                    ip_address = 0  # default
                    data = struct.pack('!qii20s20sqqqiiiih', connection_id, 1, transaction_id, info_hash, peer_id, downloaded, left, uploaded, 2, ip_address, key, num_want, 6881)

                    # Send the request
                    sock.send(data)

                    # Receive the response
                    response1 = sock.recv(2048)
                    peers = response1[20:]
                    
                    self.get_peers_from_tracker_response(peers)
                
                except Exception as e:
                    print("Error connecting to tracker:", tracker_url, e)

                finally:
                    # Close the UDP socket (important for resource management)
                    sock.close()
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

    def get_peers_from_tracker_response(self, peers_data):
        if isinstance(peers_data, list):
            for peer in peers_data:
                ip = peer['ip']
                port = peer['port']
                if (ip, port) not in self.peers:
                    self.peers.append(
                        (peer['ip'], peer['port']))
            return

        for i, byte in enumerate(peers_data):
            if i % 6 == 0:
                try:
                    ip = ".".join(str(peers_data[i+j]) for j in range(4))
                    port_data = peers_data[i+4:i+6]
                    if len(port_data) == 2:
                        port = int.from_bytes(port_data, byteorder='big')
                        print(ip, port, 'hihi')
                        if (ip, port) not in self.peers:
                            self.peers.append((ip, port))
                    else:
                        print(f"Data at indices {i+4}:{i+6} does not contain exactly 2 bytes")
                except Exception as e:
                    print(e)


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
#########################################################################################################

def read_meta_info(path):
    with open(path, "rb") as f:
        data = bdecode(f.read())
        return data


def download():
    link = "./Stein.C..Django.5.Cookbook..70+.problem.solving.techniques,...2024.torrent"
    meta_info = MetaInfo(read_meta_info(link))
    tracker = Tracker(meta_info.announce_list)
    tracker.connect(meta_info.info_hash, meta_info.peer_id,
                    6881, 0, 0, meta_info.length)

    peers = tracker.peers
    print(peers)
    #Write peers list to a txt
    with open('peers.txt', 'w') as f:
        for peer in peers:
            f.write(f'{peer[0]}:{peer[1]}\n')
    # Connect to each peer
    client = TorrentClient(link, max_peers=50, use_progress_bar=True, peers_file='peers.txt', output_dir='./DSownload')
    client.start()
    
if __name__ == "__main__":
    download()
# 14.186.94.68 6881
