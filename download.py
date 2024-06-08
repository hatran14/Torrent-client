import time
import os
import peers_manager
import pieces_manager
import torrent
import tracker
import logging
import message
import math
from threading import Thread, Lock
from block import State, BLOCK_SIZE
from upload import Upload

class Download(Thread):

    def __init__(self, torrent_file):
        Thread.__init__(self)

        self.torrent_file = torrent_file
        self.torrent = torrent.Torrent(self.torrent_file).load_from_path(self.torrent_file)
        print(self.torrent)
        self.tracker = tracker.Tracker(self.torrent)

        self.pieces_manager = pieces_manager.PiecesManager(self.torrent)
        self.peers_manager = peers_manager.PeersManager(self.torrent, self.pieces_manager)

        self.peers_manager.start()
        self.pieces_manager.start()
        logging.info("PeersManager Started")
        logging.info("PiecesManager Started")

        self.last_log_line = ""
        self.percentage_completed = -1

        self.is_active = True

        self.lock = Lock()

    def run(self):
        try:
            peers_dict = self.tracker.get_peers_from_trackers()
            self.peers_manager.add_peers(peers_dict.values())

            logging.info(f"Download {self.torrent_file} - Num pieces: {self.torrent.number_of_pieces} start")
            t = Thread(target=self.display_progression)
            t.daemon = True
            t.start()
            
            peer_list = []
            start = time.time()
            check_seeder = time.time()
            
            while not self.pieces_manager.all_pieces_completed() and self.is_active:
                peer_idx = 0
                for i in range(math.ceil(self.pieces_manager.number_of_pieces / 2)):
                    # Check for new seeder
                    if (time.time() - check_seeder > 25):
                        with self.lock:
                            peers_dict = self.tracker.get_peers_from_trackers()
                            self.peers_manager.add_peers(peers_dict.values())
                        check_seeder = time.time()

                    counter = 0
                    while counter < 2:
                        if counter == 0:
                            index = i
                        else:
                            if i == self.pieces_manager.number_of_pieces - i - 1:
                                break
                            index = self.pieces_manager.number_of_pieces - i - 1
                        counter += 1
                        
                        if self.pieces_manager.pieces[index].is_full:
                            continue
                        
                        peer_list = self.peers_manager.get_peers_having_piece(index)
                        while len(peer_list) == 0:
                            peer_list = self.peers_manager.get_peers_having_piece(index)
                        
                        peer = peer_list[peer_idx]
                        peer_idx += 1
                        if peer_idx >= len(peer_list):
                            peer_idx = 0

                        self.pieces_manager.pieces[index].update_block_status()

                        while 1:
                            data = self.pieces_manager.pieces[index].get_empty_block()
                            if not data:
                                break

                            piece_index, block_offset, block_length = data
                            piece_data = message.Request(piece_index, block_offset, block_length).to_bytes()
                            peer.send_to_peer(piece_data)

                            time.sleep(0.01)

            logging.info("{} downloaded successfully in {} seconds".format(
                            self.torrent_file, time.time() - start))
        
        except Exception as e:
            logging.debug(e.__str__)
        
        finally:
            if self.is_active:
                self.stop()
    
    def display_progression(self, statistic = None):
        speed = [0]
        avg_speed = 0
        while self.is_active:
            new_progression = 0
            for i in range(self.pieces_manager.number_of_pieces):
                for j in range(self.pieces_manager.pieces[i].number_of_blocks):
                    if self.pieces_manager.pieces[i].blocks[j].state == State.FULL:
                        new_progression += BLOCK_SIZE
            
            speed.append((new_progression - self.percentage_completed) / (2 ** 20))
            if len(speed) == 10:
                avg_speed = sum(speed) / 10
                speed.clear()
            else:
                avg_speed = speed[len(speed) - 1]

            if avg_speed < 0:
                avg_speed *= -1
            
            with self.lock:
                number_of_peers = len(self.peers_manager.peers)
            
            percentage_completed = float((float(new_progression) / self.torrent.total_length) * 100)
            if (percentage_completed > 100):
                percentage_completed = 100

            current_log_line = "Connected peers: {} - {}% completed | {}/{} pieces | Speed: {} Mb/s" \
                                .format(number_of_peers,
                                round(percentage_completed, 2),
                                self.pieces_manager.complete_pieces,
                                self.pieces_manager.number_of_pieces,
                                float(avg_speed))
            
            if current_log_line != self.last_log_line:
                print(current_log_line)

            self.last_log_line = current_log_line
            self.percentage_completed = new_progression
        
            if statistic != None:
                statistic[0] = number_of_peers,
                statistic[1] = round(percentage_completed, 2)
                statistic[2] = self.pieces_manager.complete_pieces
                statistic[3] = self.pieces_manager.number_of_pieces
                statistic[4] = float(avg_speed)
                
            time.sleep(0.1)

    def stop(self):
        self.peers_manager.is_active = False
        self.is_active = False
        
        # Close all sockets
        for peer in self.peers_manager.peers:
            peer.stop()
            peer.socket.close()
        self.peers_manager.peers.clear()
        
        # Unsubscribe events
        self.peers_manager.unsub()
        self.pieces_manager.unsub()

        logging.info("Thread download {} stop".format(self.torrent_file))

        upload = Upload('', self.torrent_file ,self.torrent)
        upload.start()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    pid = os.getpid()
    thread_list = {}
    while 1:
        try:
            key = int(input("Download new file? '1' for Yes, '0' for No: "))
            if key == 1:
                torrent_file = input("Enter .torrent file: ")
                download = Download(torrent_file)
                download.start()
            else:
                break
        except Exception as e:
            logging.debug(e.__str__)
            break
        except KeyboardInterrupt:
            os.kill(pid, 9)