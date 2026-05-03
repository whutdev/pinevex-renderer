import struct
from typing import List, Dict
from dataclasses import dataclass, field
import zstandard as zstd

from .buffer import Buffer
from .compression import lz4_decompress
from .chunk_parsers import ChunkParser
from .types import VirtualInstance


@dataclass
class RBXM:
    """Represents a parsed RBXM file."""
    
    class_refs: Dict[int, Dict] = field(default_factory=dict)
    instance_refs: Dict[int, VirtualInstance] = field(default_factory=dict)
    tree: List[VirtualInstance] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)
    strings: List[str] = field(default_factory=list)


def parse_rbxm(file_path: str) -> RBXM:
    """
    Parse a Roblox RBXM binary file.
    
    Args:
        file_path: Path to the .rbxm file
    
    Returns:
        RBXM object containing the instance tree and metadata
    
    Example:
        >>> rbxm = parse_rbxm('model.rbxm')
        >>> for instance in rbxm.tree:
        ...     print(instance.class_name, instance.properties)
    """
    with open(file_path, 'rb') as f:
        data = f.read()
    
    return parse_rbxm_bytes(data)


def parse_rbxm_bytes(data: bytes) -> RBXM:
    """
    Parse RBXM data from bytes.
    
    Args:
        data: Raw RBXM file bytes
    
    Returns:
        RBXM object containing the instance tree and metadata
    
    Raises:
        ValueError: If the file format is invalid
    
    Example:
        >>> with open('model.rbxm', 'rb') as f:
        ...     rbxm = parse_rbxm_bytes(f.read())
    """
    HEADER = b'<roblox!'
    RBXM_SIGNATURE = b'\x89\xff\x0d\x0a\x1a\x0a'
    ZSTD_HEADER = b'\x28\xB5\x2F\xFD'
    
    buffer = Buffer(data, False)
    
    # Verify header
    if buffer.read(8) != HEADER or buffer.read(6) != RBXM_SIGNATURE:
        raise ValueError("Provided file does not match the header of an RBXM file")
    
    if buffer.read(2) != b'\x00\x00':
        raise ValueError("Invalid RBXM version")
    
    rbxm = RBXM()
    
    class_count = buffer.read_number('<i')
    inst_count = buffer.read_number('<i')
    
    if buffer.read(8) != b'\x00\x00\x00\x00\x00\x00\x00\x00':
        raise ValueError("Provided file does not match the header of an RBXM file")
    
    # Parse chunks
    chunks = {
        b'END\x00': [],
        b'INST': [],
        b'META': [],
        b'PRNT': [],
        b'PROP': [],
        b'SIGN': [],
        b'SSTR': []
    }
    
    while True:
        chunk_header = buffer.read(4)
        
        if chunk_header not in chunks:
            raise ValueError(f"Invalid chunk identifier: {chunk_header}")
        
        # Read LZ4/ZSTD header
        lz4_header = buffer.read(16, False)
        compressed = struct.unpack('<I', lz4_header[0:4])[0]
        decompressed = struct.unpack('<I', lz4_header[4:8])[0]
        reserved = lz4_header[8:12]
        zstd_check = lz4_header[12:16]
        
        if reserved != b'\x00\x00\x00\x00':
            raise ValueError(f"Invalid chunk header")
        
        if compressed == 0:
            chunk_data = Buffer(buffer.read(decompressed + 12), False)
        else:
            if zstd_check == ZSTD_HEADER:
                buffer.seek(12)
                compressed_data = buffer.read(compressed)
                dctx = zstd.ZstdDecompressor()
                chunk_data = Buffer(dctx.decompress(compressed_data), False)
            else:
                chunk_data = Buffer(lz4_decompress(buffer.read(compressed + 12)), False)
        
        chunks[chunk_header].append(chunk_data)
        
        if chunk_header == b'END\x00':
            break
    
    # Process chunks in order
    for chunk_data in chunks[b'META']:
        ChunkParser.parse_meta(chunk_data, rbxm)
    
    for chunk_data in chunks[b'SSTR']:
        ChunkParser.parse_sstr(chunk_data, rbxm)
    
    for chunk_data in chunks[b'INST']:
        ChunkParser.parse_inst(chunk_data, rbxm)
    
    for chunk_data in chunks[b'PROP']:
        ChunkParser.parse_prop(chunk_data, rbxm)
    
    for chunk_data in chunks[b'PRNT']:
        ChunkParser.parse_prnt(chunk_data, rbxm)
    
    # Resolve all reference properties to point to actual instances
    _resolve_references(rbxm)
    
    return rbxm


def _resolve_references(rbxm: RBXM):
    """
    Resolve all reference properties to point to actual VirtualInstance objects.
    
    After parsing, reference properties are stored as ('__ref__', ref_id) tuples.
    This function replaces those tuples with actual instance references.
    """
    for inst in rbxm.instance_refs.values():
        for prop_name, prop_value in list(inst.properties.items()):
            # Check if this is a reference that needs resolution
            if isinstance(prop_value, tuple) and len(prop_value) == 2:
                if prop_value[0] == '__ref__':
                    ref_id = prop_value[1]
                    if ref_id == -1:
                        inst.properties[prop_name] = None
                    else:
                        # Replace with actual instance reference
                        referenced_inst = rbxm.instance_refs.get(ref_id)
                        inst.properties[prop_name] = referenced_inst