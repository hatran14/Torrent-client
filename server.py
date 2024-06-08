import socket
from threading import Thread
from bcoding import bdecode, bencode
import os
from utils import getIP

SERVER_IP = "192.168.1.15" #getIP()"
SERVER_PORT = 1234
MAX_LISTEN = 100

TORRENTS_DIR = "torrents"

class Server(Thread):	
	def __init__(self):
		Thread.__init__(self)
		self.peer_addresses = {}

	def run(self):
		Server_Socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		Server_Socket.bind((SERVER_IP, SERVER_PORT))
		Server_Socket.listen(MAX_LISTEN)        

		# Receive client info (address,port)
		while True:
			client = {}
			client['Socket'] = Server_Socket.accept()
			print(f"connect from {client['Socket'][1]}")
			Thread(target=self.recvRequest, args=(client,)).start()

	def recvRequest(self, client):
		"""Receive request from the client."""
		connSocket = client['Socket'][0]
		while True:          
			try:
				data = connSocket.recv(2**20)
				if data:
					# print(f"Data received from {client['Socket'][1]}:")
					# print(bdecode(data))
					self.processRequest(bdecode(data), client)
			except:
				#print(f"{client['username']} has logged out")
				break

	def processRequest(self, data, client):
		if 'event' in data:
			"""Store peer address based on the info_hash"""
			peer = {'ip': client['Socket'][1][0], 'port': data['port']}
			self.add_peer(data['info_hash'], peer)
			"""Response list of peers"""
			response = {'peers' : []}
			response['peers'] = self.peer_addresses[data['info_hash']].copy()
			response['peers'].remove(peer)
			client['Socket'][0].sendall(bencode(response))
		
		elif 'torrent' in data:
			"""Store torrent file"""
			if not os.path.exists(TORRENTS_DIR):
				os.mkdir(TORRENTS_DIR, 0o0766 )
			
			filename = TORRENTS_DIR + '/' + data['name']

			# Write the torrent file to disk
			try:
				with open(filename, 'wb') as file:
					file.write(data['torrent'])
			except Exception as e:
				print(e)
			
			client['Socket'][0].sendall('OK'.encode())
		
		elif 'get' in data:
			filename = TORRENTS_DIR + '/' + data['get']
			response = b''
			try:
				with open(filename, 'rb') as file:
					response = file.read()
			except Exception as e:
				print(e)
			client['Socket'][0].sendall(response)

		elif 'retrieve' in data:
			file_names = []
			for filename in os.listdir(TORRENTS_DIR):
				if os.path.isfile(os.path.join(TORRENTS_DIR, filename)):
					file_names.append(filename)
			response = {'file_list' : file_names}
			client['Socket'][0].sendall(bencode(response))

	def add_peer(self, info_hash, address):
		"""Add a peer address to the dictionary based on the info_hash"""
		if info_hash not in self.peer_addresses:
			self.peer_addresses[info_hash] = []
		if address not in self.peer_addresses[info_hash]:
			self.peer_addresses[info_hash].append(address)

	def remove_peer(self, info_hash, address):
		"""Remove a peer address from the dictionary based on the info_hash"""
		if info_hash in self.peer_addresses:
			if address in self.peer_addresses[info_hash]:
				self.peer_addresses[info_hash].remove(address)
				if len(self.peer_addresses[info_hash]) == 0:
					# Remove the info_hash entry if there are no more peers associated with it
					del self.peer_addresses[info_hash]

if __name__ == "__main__":
	try:
		pid = os.getpid()
		server = Server()
		server.start()
		input('Server is listening, press any key to abort...')
		os.kill(pid,9)
	except KeyboardInterrupt:
		os.kill(pid,9)
