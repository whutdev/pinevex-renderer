from .buffer import Buffer


def lz4_decompress(lz4_data: bytes) -> bytes:
    """Decompress LZ4 compressed data."""
    buffer = Buffer(lz4_data)
    
    compressed_len = buffer.read_number('<I')
    decompressed_len = buffer.read_number('<I')
    reserved = buffer.read_number('<I')
    
    if reserved != 0:
        raise ValueError("Provided chunk is not LZ4 data")
    
    if compressed_len == 0:
        return buffer.read(decompressed_len)
    
    output = bytearray()
    
    while len(output) < decompressed_len:
        token = buffer.read_byte()
        lit_len = token >> 4
        mat_len = (token & 15) + 4
        
        if lit_len >= 15:
            while True:
                next_byte = buffer.read_byte()
                lit_len += next_byte
                if next_byte != 0xFF:
                    break
        
        literal = buffer.read(lit_len)
        output.extend(literal)
        
        if len(output) < decompressed_len:
            offset = buffer.read_number('<H')
            
            if mat_len >= 19:
                while True:
                    next_byte = buffer.read_byte()
                    mat_len += next_byte
                    if next_byte != 0xFF:
                        break
            
            # Copy match
            pos = len(output) - offset
            for _ in range(mat_len):
                output.append(output[pos])
                pos += 1
    
    return bytes(output[:decompressed_len])