import math
import hashlib
import time
from bcoding import bencode, bdecode
import logging
import os

DOWNLOADS_DIR = "downloads"

class Torrent(object):
    def __init__(self, name: str):
        # Refer from Metainfo File Structure
        self.torrent_file = {}
        self.total_length: int = 0
        self.piece_length: int = 0
        self.pieces: int = 0
        self.info_hash: str = ''
        self.peer_id: str = ''
        self.announce_list = ''
        self.file_names = []
        self.number_of_pieces: int = 0
        self.name = name.split(':')[0]
    
    def __str__ (self):
        return  f"Torrent Object:\n" \
                f"total_length: {self.total_length}\n" \
                f"piece_length: {self.piece_length}\n" \
                f"info_hash: {self.info_hash}\n" \
                f"peer_id: {self.peer_id}\n" \
                f"announce_list: {self.announce_list}\n" \
                f"file_names: {self.file_names}\n" \
                f"number_of_pieces: {self.number_of_pieces}\n" \
                #f"pieces: {self.pieces}\n" \
                #f"torrent_file: {self.torrent_file}\n" \

    #This function load and get information from a .torrent file
    def load_from_path(self, path, root_path = DOWNLOADS_DIR):
        with open(path, 'rb') as file:
            contents = bdecode(file)

        self.torrent_file = contents
        self.piece_length = self.torrent_file['info']['piece length']
        self.pieces = self.torrent_file['info']['pieces']
        raw_info_hash = bencode(self.torrent_file['info'])
        self.info_hash = hashlib.sha1(raw_info_hash).digest()
        self.peer_id = self.generate_peer_id()
        self.announce_list = self.get_trackers()
        self.init_files(root_path)
        self.number_of_pieces = math.ceil(self.total_length / self.piece_length)
        
        logging.debug(self)

        assert(self.total_length > 0)
        assert(len(self.file_names) > 0)

        return self

    # Init files base on .torrent file information
    def init_files(self, root_path):
        if root_path:
            if not os.path.exists(root_path):
                os.mkdir(root_path, 0o0766 )
            root = root_path + "/" + self.torrent_file['info']['name']
        else:
            root = self.torrent_file['info']['name']

        if 'files' in self.torrent_file['info']:
            if not os.path.exists(root):
                os.mkdir(root, 0o0766 )

            for file in self.torrent_file['info']['files']:
                path_file = os.path.join(root, *file["path"])

                if not os.path.exists(os.path.dirname(path_file)):
                    os.makedirs(os.path.dirname(path_file))

                self.file_names.append({"path": path_file , "length": file["length"]})
                self.total_length += file["length"]

        else:
            self.file_names.append({"path": root , "length": self.torrent_file['info']['length']})
            self.total_length = self.torrent_file['info']['length']

    # Get announce URL of the tracker
    def get_trackers(self):
        if 'announce-list' in self.torrent_file:
            return self.torrent_file['announce-list']
        else:
            return [[self.torrent_file['announce']]]

    # Generate urlencoded 20-byte string used as a unique ID for the client
    def generate_peer_id(self):
        seed = str(time.time())
        return hashlib.sha1(seed.encode('utf-8')).digest()