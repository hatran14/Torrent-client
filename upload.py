import socket 
import logging
import os
import message
import peers_manager
import pieces_manager
import torrent
import tracker
import peer
import random

from threading import Thread
from bitstring import BitArray
from server import SERVER_IP, SERVER_PORT
from utils import getIP, create_metainfo_file, upload_torrent_file

TRACKER_URL = SERVER_IP + ':' + str(SERVER_PORT) # Simulate a tracker url
PIECE_LENGTH = 2 ** 22
MAX_LISTEN = 100
HOST = getIP()
class Upload(Thread):
    def __init__(self, file_path, torrent_file, _torrent = None):
        Thread.__init__(self)

        if _torrent == None:
            self.file_path = file_path
            self.torrent_file = torrent_file
            self.files = create_metainfo_file(self.file_path, self.torrent_file, TRACKER_URL, PIECE_LENGTH)
            self.torrent = torrent.Torrent(self.torrent_file).load_from_path(self.torrent_file, root_path=os.path.dirname(self.file_path))

        else:
            self.torrent = _torrent
            self.torrent_file = torrent_file

        # Upload created torrent to server
        s = socket.socket()
        s.connect((SERVER_IP, SERVER_PORT))
        upload_torrent_file(s, self.torrent_file)
        s.close()

        self.tracker = tracker.Tracker(self.torrent)
        self.pieces_manager = pieces_manager.PiecesManager(self.torrent)
        self.peers_manager = peers_manager.PeersManager(self.torrent, self.pieces_manager)

        self.peers_manager.start()
        logging.info("PeersManager Started")
        logging.info("PiecesManager Started")

        self.listen = socket.socket()
        self.listen_port = random.randint(6666, 9999)
        self.listen.bind((HOST, self.listen_port))
        self.listen.listen(MAX_LISTEN)

        self.is_active = True

    def run(self):
        try:
            logging.info("Upload thread for {} is running".format(self.torrent_file))
            self.tracker.get_peers_from_trackers(try_connect=False, listen_port=self.listen_port)
            while self.is_active:
                # Perform your thread's tasks here
                try:
                    sock, addr = self.listen.accept()
                    self.add_peer(sock, addr)
                except Exception as e:
                    #logging.debug(e.__str__)
                    pass
            
            logging.info("Upload thread for {} is stopping".format(self.torrent_file))
        finally:
            if self.is_active:
                self.stop()

    def add_peer(self, sock, addr):
        print(f"Add downloader: {addr[0]} - {addr[1]}")
        new_peer = peer.Peer(int(self.torrent.number_of_pieces), addr[0], addr[1], self.torrent.name)
        sock.setblocking(False)
        new_peer.socket = sock
        new_peer.healthy = True
        self.peers_manager.add_peers([new_peer])
        
        bitfield = BitArray(length=self.torrent.number_of_pieces)
        bitfield.set(1)
        msg = message.BitField(bitfield)
        new_peer.send_to_peer(msg.to_bytes())

    def stop(self):
        self.listen.close()
        self.is_active = False

        # Close all sockets
        for peer in self.peers_manager.peers:
            peer.socket.close()
        self.peers_manager.peers.clear()
        
        # Unsubscribe events
        self.peers_manager.unsub()
        self.pieces_manager.unsub()

        logging.info("Thread upload {} stop".format(self.torrent_file))

if __name__ == '__main__':
    pid = os.getpid()
    logging.basicConfig(level=logging.DEBUG)
    while 1:
        try:
            key = int(input("Upload new file? '1' for Yes, '0' for No: "))
            if (key == 1):
                file_path = input("Enter the path to the file or directory you want to TRANSFER: ")
                torrent_file = input("Enter the desired output path for the metainfo file (.torrent file): ")
                upload = Upload(file_path, torrent_file)
                upload.start()
        except Exception as e:
            print(e)
            logging.debug(e.__str__)
            break
        except KeyboardInterrupt:
            os.kill(pid, 9)
            break
