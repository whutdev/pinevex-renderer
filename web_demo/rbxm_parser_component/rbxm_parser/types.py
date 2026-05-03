from typing import List, Dict, Any
from dataclasses import dataclass, field


class Vector3:
    """Represents a 3D vector."""
    
    def __init__(self, x: float, y: float, z: float):
        self.x = x
        self.y = y
        self.z = z
    
    def __repr__(self):
        return f"Vector3({self.x}, {self.y}, {self.z})"
    
    def cross(self, other: 'Vector3') -> 'Vector3':
        """Calculate the cross product of two vectors."""
        return Vector3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x
        )
    
    @staticmethod
    def from_normal_id(normal_id: int) -> 'Vector3':
        """Create a Vector3 from a Roblox NormalId."""
        normals = [
            Vector3(1, 0, 0),   # Right
            Vector3(0, 1, 0),   # Top
            Vector3(0, 0, 1),   # Back
            Vector3(-1, 0, 0),  # Left
            Vector3(0, -1, 0),  # Bottom
            Vector3(0, 0, -1),  # Front
        ]
        return normals[normal_id]


class Vector2:
    """Represents a 2D vector."""
    
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y
    
    def __repr__(self):
        return f"Vector2({self.x}, {self.y})"


class Vector3int16:
    """Represents a 3D vector with 16-bit integer components."""
    
    def __init__(self, x: int, y: int, z: int):
        self.x = x
        self.y = y
        self.z = z
    
    def __repr__(self):
        return f"Vector3int16({self.x}, {self.y}, {self.z})"


class CFrame:
    """Represents a coordinate frame (position + rotation)."""
    
    def __init__(self, x: float = 0, y: float = 0, z: float = 0,
                 qx: float = 0, qy: float = 0, qz: float = 0, qw: float = 1):
        self.position = Vector3(x, y, z)
        if qw != 1 or qx != 0 or qy != 0 or qz != 0:
            self.rotation = self._quaternion_to_matrix(qx, qy, qz, qw)
        else:
            self.rotation = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    
    @staticmethod
    def from_matrix(pos: Vector3, r0: Vector3, r1: Vector3, r2: Vector3) -> 'CFrame':
        """Create a CFrame from a position and rotation vectors."""
        cf = CFrame(pos.x, pos.y, pos.z)
        cf.position = pos
        cf.rotation = [
            [r0.x, r1.x, r2.x],
            [r0.y, r1.y, r2.y],
            [r0.z, r1.z, r2.z]
        ]
        return cf
    
    def _quaternion_to_matrix(self, x: float, y: float, z: float, w: float):
        """Convert quaternion to rotation matrix."""
        xx, yy, zz = x*x, y*y, z*z
        xy, xz, yz = x*y, x*z, y*z
        wx, wy, wz = w*x, w*y, w*z
        
        return [
            [1 - 2*(yy + zz), 2*(xy - wz), 2*(xz + wy)],
            [2*(xy + wz), 1 - 2*(xx + zz), 2*(yz - wx)],
            [2*(xz - wy), 2*(yz + wx), 1 - 2*(xx + yy)]
        ]
    
    def __repr__(self):
        return f"CFrame(pos={self.position})"


class Color3:
    """Represents an RGB color with float components (0-1)."""
    
    def __init__(self, r: float, g: float, b: float):
        self.r = r
        self.g = g
        self.b = b
    
    @staticmethod
    def from_rgb(r: int, g: int, b: int) -> 'Color3':
        """Create a Color3 from RGB byte values (0-255)."""
        return Color3(r / 255.0, g / 255.0, b / 255.0)
    
    def __repr__(self):
        return f"Color3({self.r}, {self.g}, {self.b})"


class UDim:
    """Represents a 1D UI dimension with scale and offset."""
    
    def __init__(self, scale: float, offset: int):
        self.scale = scale
        self.offset = offset
    
    def __repr__(self):
        return f"UDim({self.scale}, {self.offset})"


class UDim2:
    """Represents a 2D UI dimension."""
    
    def __init__(self, scale_x: float, offset_x: int, scale_y: float, offset_y: int):
        self.x = UDim(scale_x, offset_x)
        self.y = UDim(scale_y, offset_y)
    
    def __repr__(self):
        return f"UDim2({self.x.scale}, {self.x.offset}, {self.y.scale}, {self.y.offset})"


class Ray:
    """Represents a ray with origin and direction."""
    
    def __init__(self, origin: Vector3, direction: Vector3):
        self.origin = origin
        self.direction = direction
    
    def __repr__(self):
        return f"Ray(origin={self.origin}, direction={self.direction})"


class Rect:
    """Represents a 2D rectangle."""
    
    def __init__(self, min_pos: Vector2, max_pos: Vector2):
        self.min = min_pos
        self.max = max_pos
    
    def __repr__(self):
        return f"Rect(min={self.min}, max={self.max})"


class NumberRange:
    """Represents a range of numbers."""
    
    def __init__(self, min_val: float, max_val: float):
        self.min = min_val
        self.max = max_val
    
    def __repr__(self):
        return f"NumberRange({self.min}, {self.max})"


class NumberSequenceKeypoint:
    """Keypoint for a NumberSequence."""
    
    def __init__(self, time: float, value: float, envelope: float = 0):
        self.time = time
        self.value = value
        self.envelope = envelope
    
    def __repr__(self):
        return f"NumberSequenceKeypoint({self.time}, {self.value}, {self.envelope})"


class NumberSequence:
    """Represents a sequence of number keypoints."""
    
    def __init__(self, keypoints: List[NumberSequenceKeypoint]):
        self.keypoints = keypoints
    
    def __repr__(self):
        return f"NumberSequence({self.keypoints})"


class ColorSequenceKeypoint:
    """Keypoint for a ColorSequence."""
    
    def __init__(self, time: float, value: Color3):
        self.time = time
        self.value = value
    
    def __repr__(self):
        return f"ColorSequenceKeypoint({self.time}, {self.value})"


class ColorSequence:
    """Represents a sequence of color keypoints."""
    
    def __init__(self, keypoints: List[ColorSequenceKeypoint]):
        self.keypoints = keypoints
    
    def __repr__(self):
        return f"ColorSequence({self.keypoints})"


class PhysicalProperties:
    """Represents physical properties of a part."""
    
    def __init__(self, density: float, friction: float, elasticity: float,
                 friction_weight: float, elasticity_weight: float):
        self.density = density
        self.friction = friction
        self.elasticity = elasticity
        self.friction_weight = friction_weight
        self.elasticity_weight = elasticity_weight
    
    def __repr__(self):
        return f"PhysicalProperties({self.density}, {self.friction}, {self.elasticity})"


class BrickColor:
    """Represents a Roblox BrickColor."""
    
    def __init__(self, number: int):
        self.number = number
    
    def __repr__(self):
        return f"BrickColor({self.number})"


class Faces:
    """Represents a set of faces."""
    
    def __init__(self, *faces):
        self.faces = list(faces)
    
    def __repr__(self):
        return f"Faces({', '.join(str(f) for f in self.faces)})"


class Axes:
    """Represents a set of axes."""
    
    def __init__(self, *axes):
        self.axes = list(axes)
    
    def __repr__(self):
        return f"Axes({', '.join(str(a) for a in self.axes)})"


class Font:
    """Represents a font."""

    def __init__(self, family: str, weight: int, style: int, cached_face_id: str = ""):
        self.family = family
        self.weight = weight
        self.style = style
        self.cached_face_id = cached_face_id

    def __repr__(self):
        return f"Font({self.family}, {self.weight}, {self.style}, {self.cached_face_id!r})"


@dataclass
class VirtualInstance:
    """Represents a Roblox instance in the file."""
    
    class_id: int
    class_name: str
    ref: int
    properties: Dict[str, Any] = field(default_factory=dict)
    children: List['VirtualInstance'] = field(default_factory=list)
    
    def __repr__(self):
        return f"<{self.class_name} [{len(self.children)} children]>"
    
    def get_property(self, name: str, default=None):
        """Get a property value with a default fallback."""
        return self.properties.get(name, default)
    
    def find_first_child(self, name: str, class_name: str = None) -> 'VirtualInstance':
        """Find the first child with the given name and optional class."""
        for child in self.children:
            if class_name and child.class_name != class_name:
                continue
            if child.get_property('Name') == name:
                return child
        return None
    
    def find_children_of_class(self, class_name: str) -> List['VirtualInstance']:
        """Find all direct children of a specific class."""
        return [child for child in self.children if child.class_name == class_name]
    
    def get_descendants(self) -> List['VirtualInstance']:
        """Get all descendants recursively."""
        descendants = []
        for child in self.children:
            descendants.append(child)
            descendants.extend(child.get_descendants())
        return descendants