import psutil
import socket
import hashlib
import os
import bencodepy
from bcoding import bencode, bdecode

# Create a metainfo file for uploading base on user input
def create_metainfo_file(file_path, output_path, tracker_url, piece_length):
    files = []

    # Check if the input path is a file or a directory
    if os.path.isdir(file_path):
        # Multiple-file mode
        for root, _, filenames in os.walk(file_path):
            for filename in filenames:
                file_rel_path = os.path.relpath(os.path.join(root, filename), file_path)
                file_abs_path = os.path.join(root, filename)
                file_size = os.path.getsize(file_abs_path)
                files.append((file_rel_path, file_size))
    
    elif os.path.isfile(file_path):
        files.append(('', os.path.getsize(file_path)))

    else:
        print("Invalid input path.")
        return
    
    # Create the metainfo dictionary
    metainfo = {
        'info': {
            'name': os.path.basename(file_path),
            'piece length': piece_length,
            'pieces': b''
        },
        'announce': tracker_url,
    }

    total_length = 0
    pieces = b''
    piece_data = b''

    for file_rel_path, file_size in files:
        total_length += file_size

        if (file_rel_path == ''):
            file = open(file_path, 'rb')
        else:
            file = open(os.path.join(file_path, file_rel_path), 'rb')

        while 1:
            file_data = file.read(piece_length)
            if not file_data:
                break
            
            piece_data += file_data

            while (len(piece_data) >= piece_length):
                piece = piece_data[:piece_length]
                piece_data = piece_data[piece_length:]

                piece_hash = hashlib.sha1(piece).digest()
                pieces += piece_hash
        
        file.close()

        if file_rel_path == '':
            break

        # Add file information to the metainfo dictionary
        if 'files' not in metainfo['info']:
            metainfo['info']['files'] = []
        metainfo['info']['files'].append({
            'path': file_rel_path.split(os.path.sep),
            'length': file_size
        })

    if (len(piece_data)):
        # Handle last piece
        piece_hash = hashlib.sha1(piece_data).digest()
        pieces += piece_hash

    metainfo['info']['length'] = total_length
    metainfo['info']['pieces'] = pieces

    # Encode the metainfo dictionary using bencodepy
    encoded_metainfo = bencodepy.encode(metainfo)

    # Save the encoded metainfo to a .torrent file
    with open(output_path, 'wb') as output_file:
        output_file.write(encoded_metainfo)

    print(f"Metainfo file '{output_path}' created successfully.")

    return files


def getIP():
    # Get all network interfaces
    interfaces = psutil.net_if_addrs()

    # Find the Ethernet interface
    eth_interface = None
    for interface, addresses in interfaces.items():
        for addr in addresses:
            if addr.family == socket.AddressFamily.AF_INET and "Ethernet" in interface:
                eth_interface = interface
                break

    # Get the IP address associated with the Ethernet interface
    if eth_interface:
        ip_address = interfaces[eth_interface][1].address
        print("Ethernet IP Address:", ip_address)
    else:
        print("Ethernet interface not found")
    
    return ip_address

def upload_torrent_file(server_socket: socket.socket, torrent: str):
    try:
        with open(torrent, 'rb') as file:
            data = file.read()
    except Exception as e:
        print(e)
    
    params = {
        'name': torrent,
        'torrent' : data
    }
    
    #POST to server
    try:
        server_socket.sendall(bencode(params))
    except Exception as e:
        print(e)
    
    data = server_socket.recv(8)
    while data.decode() != 'OK':
        print(data.decode())
        upload_torrent_file(server_socket, torrent)

def download_torrent_file(server_socket: socket.socket, torrent: str):
    params = {
        'get' : torrent,
    }
    
    # Send GET request
    server_socket.sendall(bencode(params))

    # Wait for response
    data = server_socket.recv(2**20)
    try:
        with open(torrent, 'wb') as file:
            file.write(data)
    except Exception as e:
        print(e)

def retrieve_torrent_file(server_socket: socket.socket) -> list:
    params = {
        'retrieve'
    }
    
    # Send GET request
    server_socket.sendall(bencode(params))

    # Wait for response
    data = server_socket.recv(2**20)
    data = bdecode(data)
    return data['file_list']