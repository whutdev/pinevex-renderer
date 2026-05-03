from typing import TYPE_CHECKING
from .buffer import Buffer
from .basic_types import BasicTypes
from .types import *

if TYPE_CHECKING:
    from .parser import RBXM


class ChunkParser:
    """Parsers for different RBXM chunk types."""
    
    @staticmethod
    def parse_meta(chunk_data: Buffer, rbxm: 'RBXM'):
        """Parse META chunk (metadata key-value pairs)."""
        count = chunk_data.read_number('<I')
        for _ in range(count):
            key = BasicTypes.read_string(chunk_data)
            value = BasicTypes.read_string(chunk_data)
            rbxm.metadata[key] = value
    
    @staticmethod
    def parse_sstr(chunk_data: Buffer, rbxm: 'RBXM'):
        """Parse SSTR chunk (shared strings)."""
        version = chunk_data.read_number('<I')
        if version != 0:
            raise ValueError("Invalid SSTR version")
        
        count = chunk_data.read_number('<I')
        for i in range(count):
            chunk_data.read(16)  # MD5 hash (unused)
            rbxm.strings.append(BasicTypes.read_string(chunk_data))
    
    @staticmethod
    def parse_inst(chunk_data: Buffer, rbxm: 'RBXM'):
        """Parse INST chunk (instance definitions)."""
        class_id = chunk_data.read_number('<I')
        class_name = BasicTypes.read_string(chunk_data)
        
        if chunk_data.read(1) == b'\x01':
            raise ValueError("Attempt to insert binary model with services")
        
        count = chunk_data.read_number('<I')
        refs = BasicTypes.ref_array(chunk_data, count)
        
        rbxm.class_refs[class_id] = {
            'name': class_name,
            'sizeof': count,
            'refs': refs
        }
        
        for ref in refs:
            rbxm.instance_refs[ref] = VirtualInstance(class_id, class_name, ref)
    
    @staticmethod
    def parse_prop(chunk_data: Buffer, rbxm: 'RBXM'):
        """Parse PROP chunk (property values)."""
        class_id = chunk_data.read_number('<I')
        class_ref = rbxm.class_refs[class_id]
        refs = class_ref['refs']
        sizeof = class_ref['sizeof']
        
        name = BasicTypes.read_string(chunk_data)
        
        # Check for optional type
        opt_type_check = chunk_data.read(1, False)[0] == 0x1E
        if opt_type_check:
            chunk_data.seek(1)
        
        type_id = chunk_data.read_byte()
        properties = [None] * sizeof
        
        # Parse based on property type
        if type_id == 0x01:  # String
            for i in range(sizeof):
                properties[i] = BasicTypes.read_string(chunk_data)
        
        elif type_id == 0x02:  # Boolean
            for i in range(sizeof):
                properties[i] = chunk_data.read(1) != b'\x00'
        
        elif type_id == 0x03:  # Int32
            properties = BasicTypes.int32_array(chunk_data, sizeof)
        
        elif type_id == 0x04:  # Float32
            properties = BasicTypes.rbx_float32_array(chunk_data, sizeof)
        
        elif type_id == 0x05:  # Float64
            for i in range(sizeof):
                properties[i] = BasicTypes.read_float64(chunk_data)
        
        elif type_id == 0x06:  # UDim
            scales = BasicTypes.rbx_float32_array(chunk_data, sizeof)
            offsets = BasicTypes.int32_array(chunk_data, sizeof)
            for i in range(sizeof):
                properties[i] = UDim(scales[i], offsets[i])
        
        elif type_id == 0x07:  # UDim2
            scale_x = BasicTypes.rbx_float32_array(chunk_data, sizeof)
            scale_y = BasicTypes.rbx_float32_array(chunk_data, sizeof)
            offset_x = BasicTypes.int32_array(chunk_data, sizeof)
            offset_y = BasicTypes.int32_array(chunk_data, sizeof)
            for i in range(sizeof):
                properties[i] = UDim2(scale_x[i], offset_x[i], scale_y[i], offset_y[i])
        
        elif type_id == 0x08:  # Ray
            for i in range(sizeof):
                origin = Vector3(
                    chunk_data.read_number('<f'),
                    chunk_data.read_number('<f'),
                    chunk_data.read_number('<f')
                )
                direction = Vector3(
                    chunk_data.read_number('<f'),
                    chunk_data.read_number('<f'),
                    chunk_data.read_number('<f')
                )
                properties[i] = Ray(origin, direction)
        
        elif type_id == 0x09:  # Faces
            for i in range(sizeof):
                byte = chunk_data.read_byte()
                faces = [j for j in range(6) if byte & (1 << j)]
                properties[i] = Faces(*faces)
        
        elif type_id == 0x0A:  # Axes
            for i in range(sizeof):
                byte = chunk_data.read_byte()
                axes = [j for j in range(3) if byte & (1 << j)]
                properties[i] = Axes(*axes)
        
        elif type_id == 0x0B:  # BrickColor
            ints = BasicTypes.unsigned_int_array(chunk_data, sizeof)
            for i in range(sizeof):
                properties[i] = BrickColor(ints[i])
        
        elif type_id == 0x0C:  # Color3
            r = BasicTypes.rbx_float32_array(chunk_data, sizeof)
            g = BasicTypes.rbx_float32_array(chunk_data, sizeof)
            b = BasicTypes.rbx_float32_array(chunk_data, sizeof)
            for i in range(sizeof):
                properties[i] = Color3(r[i], g[i], b[i])
        
        elif type_id == 0x0D:  # Vector2
            x = BasicTypes.rbx_float32_array(chunk_data, sizeof)
            y = BasicTypes.rbx_float32_array(chunk_data, sizeof)
            for i in range(sizeof):
                properties[i] = Vector2(x[i], y[i])
        
        elif type_id == 0x0E:  # Vector3
            x = BasicTypes.rbx_float32_array(chunk_data, sizeof)
            y = BasicTypes.rbx_float32_array(chunk_data, sizeof)
            z = BasicTypes.rbx_float32_array(chunk_data, sizeof)
            for i in range(sizeof):
                properties[i] = Vector3(x[i], y[i], z[i])
        
        elif type_id == 0x10:  # CFrame
            matrices = []
            for i in range(sizeof):
                raw_orientation = chunk_data.read_byte()
                if raw_orientation > 0:
                    orient_id = raw_orientation - 1
                    r0 = Vector3.from_normal_id(orient_id // 6)
                    r1 = Vector3.from_normal_id(orient_id % 6)
                    r2 = r0.cross(r1)
                    matrices.append((r0, r1, r2))
                else:
                    r00, r01, r02 = (chunk_data.read_number('<f') for _ in range(3))
                    r10, r11, r12 = (chunk_data.read_number('<f') for _ in range(3))
                    r20, r21, r22 = (chunk_data.read_number('<f') for _ in range(3))
                    matrices.append((
                        Vector3(r00, r10, r20),
                        Vector3(r01, r11, r21),
                        Vector3(r02, r12, r22)
                    ))
            
            cf_x = BasicTypes.rbx_float32_array(chunk_data, sizeof)
            cf_y = BasicTypes.rbx_float32_array(chunk_data, sizeof)
            cf_z = BasicTypes.rbx_float32_array(chunk_data, sizeof)
            
            for i in range(sizeof):
                pos = Vector3(cf_x[i], cf_y[i], cf_z[i])
                properties[i] = CFrame.from_matrix(pos, *matrices[i])
        
        elif type_id == 0x11:  # Quaternion
            quaternions = []
            for i in range(sizeof):
                quaternions.append({
                    'x': chunk_data.read_number('<f'),
                    'y': chunk_data.read_number('<f'),
                    'z': chunk_data.read_number('<f'),
                    'w': chunk_data.read_number('<f')
                })
            
            cf_x = BasicTypes.rbx_float32_array(chunk_data, sizeof)
            cf_y = BasicTypes.rbx_float32_array(chunk_data, sizeof)
            cf_z = BasicTypes.rbx_float32_array(chunk_data, sizeof)
            
            for i in range(sizeof):
                q = quaternions[i]
                properties[i] = CFrame(cf_x[i], cf_y[i], cf_z[i], q['x'], q['y'], q['z'], q['w'])
        
        elif type_id == 0x12:  # Enum
            properties = BasicTypes.unsigned_int_array(chunk_data, sizeof)
        
        elif type_id == 0x13:  # Ref
            properties = BasicTypes.ref_array(chunk_data, sizeof)
        
        
        # ============================================================================
# chunk_parsers.py (continued - property types 0x14 onwards)
# ============================================================================

        elif type_id == 0x14:  # Vector3int16
            for i in range(sizeof):
                properties[i] = Vector3int16(
                    chunk_data.read_number('<h'),
                    chunk_data.read_number('<h'),
                    chunk_data.read_number('<h')
                )
        
        elif type_id == 0x15:  # NumberSequence
            for i in range(sizeof):
                kp_count = chunk_data.read_number('<I')
                keypoints = []
                for _ in range(kp_count):
                    keypoints.append(NumberSequenceKeypoint(
                        chunk_data.read_number('<f'),
                        chunk_data.read_number('<f'),
                        chunk_data.read_number('<f')
                    ))
                properties[i] = NumberSequence(keypoints)
        
        elif type_id == 0x16:  # ColorSequence
            for i in range(sizeof):
                kp_count = chunk_data.read_number('<I')
                keypoints = []
                for _ in range(kp_count):
                    time = chunk_data.read_number('<f')
                    color = Color3(
                        chunk_data.read_number('<f'),
                        chunk_data.read_number('<f'),
                        chunk_data.read_number('<f')
                    )
                    chunk_data.read_number('<f')  # Unused
                    keypoints.append(ColorSequenceKeypoint(time, color))
                properties[i] = ColorSequence(keypoints)
        
        elif type_id == 0x17:  # NumberRange
            for i in range(sizeof):
                properties[i] = NumberRange(
                    chunk_data.read_number('<f'),
                    chunk_data.read_number('<f')
                )
        
        elif type_id == 0x18:  # Rect
            xmn = BasicTypes.rbx_float32_array(chunk_data, sizeof)
            ymn = BasicTypes.rbx_float32_array(chunk_data, sizeof)
            xmx = BasicTypes.rbx_float32_array(chunk_data, sizeof)
            ymx = BasicTypes.rbx_float32_array(chunk_data, sizeof)
            for i in range(sizeof):
                properties[i] = Rect(
                    Vector2(xmn[i], ymn[i]),
                    Vector2(xmx[i], ymx[i])
                )
        
        elif type_id == 0x19:  # PhysicalProperties
            for i in range(sizeof):
                if chunk_data.read(1) == b'\x00':
                    continue
                properties[i] = PhysicalProperties(
                    chunk_data.read_number('<f'),
                    chunk_data.read_number('<f'),
                    chunk_data.read_number('<f'),
                    chunk_data.read_number('<f'),
                    chunk_data.read_number('<f')
                )
        
        elif type_id == 0x1A:  # Color3uint8
            r = list(chunk_data.read(sizeof))
            g = list(chunk_data.read(sizeof))
            b = list(chunk_data.read(sizeof))
            for i in range(sizeof):
                properties[i] = Color3.from_rgb(r[i], g[i], b[i])
        
        elif type_id == 0x1B:  # Int64
            properties = BasicTypes.int64_array(chunk_data, sizeof)
        
        elif type_id == 0x1C:  # SharedString
            strings = BasicTypes.unsigned_int_array(chunk_data, sizeof)
            for i in range(sizeof):
                ref = strings[i]
                if ref < len(rbxm.strings):
                    properties[i] = rbxm.strings[ref]
                else:
                    properties[i] = ""  # Fallback for invalid reference
        
        elif type_id == 0x1D:  # Bytecode
            for i in range(sizeof):
                properties[i] = BasicTypes.read_string(chunk_data).encode()
        
        elif type_id == 0x20:  # Font
            for i in range(sizeof):
                family = BasicTypes.read_string(chunk_data)
                weight = chunk_data.read_number('<H')
                style = chunk_data.read_byte()
                cached_face_id = BasicTypes.read_string(chunk_data)
                properties[i] = Font(family, weight, style, cached_face_id)
        
        # Handle optional properties
        if opt_type_check:
            chunk_data.read(1)
            for i in range(sizeof):
                archivable = chunk_data.read(1) != b'\x00'
                if not archivable:
                    properties[i] = None
        
        # Map to instances
        for i, ref in enumerate(refs):
            inst = rbxm.instance_refs[ref]
            prop_value = properties[i]
            
            # Mark reference properties for later resolution
            if type_id == 0x13:  # Ref type
                if prop_value == -1:  # Null reference
                    inst.properties[name] = None
                else:
                    # Store as a marker that needs resolution
                    inst.properties[name] = ('__ref__', prop_value)
            else:
                inst.properties[name] = prop_value
    
    @staticmethod
    def parse_prnt(chunk_data: Buffer, rbxm: 'RBXM'):
        """Parse PRNT chunk (parent-child relationships)."""
        version = chunk_data.read(1)
        if version != b'\x00':
            raise ValueError("Invalid PRNT version")
        
        count = chunk_data.read_number('<I')
        child_refs = BasicTypes.ref_array(chunk_data, count)
        parent_refs = BasicTypes.ref_array(chunk_data, count)
        
        for i in range(count):
            child_id = child_refs[i]
            parent_id = parent_refs[i]
            
            child = rbxm.instance_refs.get(child_id)
            parent = rbxm.instance_refs.get(parent_id) if parent_id >= 0 else None
            
            if not child:
                raise ValueError(f"Could not parent {child_id} to {parent_id}: child {child_id} is nil")
            
            if parent_id >= 0 and not parent:
                raise ValueError(f"Could not parent {child_id} to {parent_id}: parent {parent_id} is nil")
            
            parent_table = parent.children if parent else rbxm.tree
            parent_table.append(child)