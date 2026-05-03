import struct


class Buffer:
    """A buffer for reading binary data with offset tracking."""
    
    def __init__(self, data: bytes, allow_overflows: bool = True):
        self.source = data
        self.offset = 0
        self.length = len(data)
        self.is_finished = False
        self.last_unread_bytes = 0
        self.allow_overflows = allow_overflows
    
    def read(self, length: int = 1, shift: bool = True) -> bytes:
        """Read bytes from the buffer."""
        data = self.source[self.offset:self.offset + length]
        data_length = len(data)
        unread_bytes = length - data_length
        
        if unread_bytes > 0 and not self.allow_overflows:
            raise ValueError("Buffer went out of bounds and AllowOverflows is false")
        
        if shift:
            self.seek(length)
        
        self.last_unread_bytes = unread_bytes
        return data
    
    def seek(self, length: int = 1):
        """Move the read offset forward."""
        self.offset = max(0, min(self.offset + length, self.length))
        self.is_finished = self.offset >= self.length
    
    def append(self, new_data: bytes):
        """Append data to the buffer."""
        self.source += new_data
        self.length = len(self.source)
        self.seek(0)
    
    def to_end(self):
        """Move the offset to the end."""
        self.seek(self.length)
    
    def read_number(self, fmt: str, shift: bool = True) -> int:
        """Read a number using struct format."""
        pack_size = struct.calcsize(fmt)
        chunk = self.read(pack_size, shift)
        return struct.unpack(fmt, chunk)[0]
    
    def read_byte(self, shift: bool = True) -> int:
        """Read a single byte as an integer."""
        return self.read(1, shift)[0]