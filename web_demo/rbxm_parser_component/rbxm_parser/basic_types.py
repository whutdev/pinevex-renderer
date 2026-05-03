import struct
from typing import List
from .buffer import Buffer


class BasicTypes:
    """Utilities for reading Roblox binary types."""
    
    @staticmethod
    def transform_int(x: int) -> int:
        """Transform a Roblox-encoded signed integer."""
        return x // 2 if x % 2 == 0 else -(x + 1) // 2
    
    @staticmethod
    def rbx_float32(x: int) -> float:
        """Convert a Roblox-encoded float32."""
        x = ((x >> 1) | (x << 31)) & 0xFFFFFFFF
        return struct.unpack('>f', struct.pack('>I', x))[0]
    
    @staticmethod
    def read_string(buffer: Buffer) -> str:
        """Read a length-prefixed string."""
        length = buffer.read_number('<I')
        return buffer.read(length).decode('utf-8', errors='replace')
    
    @staticmethod
    def read_int32(buffer: Buffer) -> int:
        """Read a transformed int32."""
        return BasicTypes.transform_int(buffer.read_number('>I'))
    
    @staticmethod
    def read_int64(buffer: Buffer) -> int:
        """Read a transformed int64."""
        return BasicTypes.transform_int(buffer.read_number('>Q'))
    
    @staticmethod
    def read_float32(buffer: Buffer) -> float:
        """Read a Roblox float32."""
        return BasicTypes.rbx_float32(buffer.read_number('>I'))
    
    @staticmethod
    def read_float64(buffer: Buffer) -> float:
        """Read a float64."""
        return buffer.read_number('<d')
    
    @staticmethod
    def interleave_array(buffer: Buffer, count: int, sizeof: int) -> Buffer:
        """De-interleave an array."""
        if count < 0:
            return Buffer(b'', False)
        
        stream = buffer.read(count * sizeof)
        out = []
        
        for i in range(count):
            chunk = bytearray()
            for s in range(sizeof):
                bit_pos = i + (count * s)
                chunk.append(stream[bit_pos])
            out.append(bytes(chunk))
        
        return Buffer(b''.join(out), False)
    
    @staticmethod
    def unsigned_int_array(buffer: Buffer, count: int) -> List[int]:
        """Read an array of unsigned integers."""
        if count < 1:
            return []
        
        strings = BasicTypes.interleave_array(buffer, count, 4)
        return [strings.read_number('>I') for _ in range(count)]
    
    @staticmethod
    def int32_array(buffer: Buffer, count: int) -> List[int]:
        """Read an array of int32 values."""
        if count < 1:
            return []
        
        strings = BasicTypes.interleave_array(buffer, count, 4)
        return [BasicTypes.read_int32(strings) for _ in range(count)]
    
    @staticmethod
    def int64_array(buffer: Buffer, count: int) -> List[int]:
        """Read an array of int64 values."""
        if count < 1:
            return []
        
        strings = BasicTypes.interleave_array(buffer, count, 8)
        return [BasicTypes.read_int64(strings) for _ in range(count)]
    
    @staticmethod
    def rbx_float32_array(buffer: Buffer, count: int) -> List[float]:
        """Read an array of Roblox float32 values."""
        if count < 1:
            return []
        
        strings = BasicTypes.interleave_array(buffer, count, 4)
        return [BasicTypes.read_float32(strings) for _ in range(count)]
    
    @staticmethod
    def ref_array(buffer: Buffer, count: int) -> List[int]:
        """Read an array of reference IDs."""
        if count < 1:
            return []
        
        refs = BasicTypes.int32_array(buffer, count)
        out = []
        last = 0
        
        for ref in refs:
            ref = last + ref
            out.append(ref)
            last = ref
        
        return out