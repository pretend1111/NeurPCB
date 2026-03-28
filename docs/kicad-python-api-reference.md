# KiCad Python API 参考文档 (`kipy`)

> **版本**：kicad-python 0.6.0（对应 KiCad 9.0）  
> **官方文档**：https://docs.kicad.org/kicad-python-main  
> **源码仓库**：https://gitlab.com/kicad/code/kicad-python/  
> **PyPI 安装**：`pip install kicad-python`

---

## 目录

1. [前置条件与连接](#1-前置条件与连接)
2. [单位系统](#2-单位系统)
3. [KiCad 主类](#3-kicad-主类)
4. [Board（PCB 文档）](#4-board-pcb-文档)
5. [Footprint（封装）](#5-footprint-封装)
6. [Track 与 ArcTrack（走线）](#6-track-与-arctrack-走线)
7. [Via（过孔）](#7-via-过孔)
8. [Pad（焊盘）](#8-pad-焊盘)
9. [Zone（铜区）](#9-zone-铜区)
10. [BoardShape（图形对象）](#10-boardshape-图形对象)
11. [Net（网络）](#11-net-网络)
12. [几何类型](#12-几何类型)
13. [公共类型（Common Types）](#13-公共类型-common-types)
14. [Project（项目）](#14-project-项目)
15. [BoardStackup（板层叠结构）](#15-boardstackup-板层叠结构)
16. [提交事务机制（Commit）](#16-提交事务机制-commit)
17. [导出功能（Export Jobs）](#17-导出功能-export-jobs)
18. [枚举类型速查](#18-枚举类型速查)
19. [错误处理](#19-错误处理)
20. [实用工具函数](#20-实用工具函数)
21. [完整示例](#21-完整示例)

---

## 1. 前置条件与连接

### 系统要求

- **KiCad 9.0 或更高版本**（必须正在运行）
- 在 KiCad 中启用 API 服务：`Preferences → Plugins → Enable IPC API Server`
- Python 依赖：`protobuf`、`pynng`

### 安装

```bash
pip install kicad-python
```

### 建立连接

```python
from kipy import KiCad

# 方式 1：标准连接（KiCad 必须已运行且 API 服务已启用）
kicad = KiCad()

# 方式 2：使用上下文管理器（推荐，自动关闭连接）
with KiCad() as kicad:
    board = kicad.get_board()
    # ... 操作 ...

# 方式 3：指定 socket 路径（高级用法）
kicad = KiCad(socket_path='ipc:///tmp/kicad/api.sock')

# 方式 4：无头模式（KiCad 11+，自动启动 kicad-cli api-server）
with KiCad(headless=True, file_path='/path/to/project.kicad_pcb') as kicad:
    board = kicad.get_board()
```

### Socket 路径默认值

| 操作系统 | 默认路径 |
|----------|----------|
| Windows  | `ipc://%TEMP%\kicad\api.sock` |
| Linux/Mac | `ipc:///tmp/kicad/api.sock` |
| Linux Flatpak | `~/.var/app/org.kicad.KiCad/cache/tmp/kicad/api.sock` |

可通过环境变量 `KICAD_API_SOCKET` 覆盖默认路径。

---

## 2. 单位系统

> ⚠️ **所有长度/坐标值均以纳米（nm）为单位，类型为 `int`。**

```python
from kipy.util.units import to_mm, from_mm

# 纳米 → 毫米
mm_value = to_mm(1_000_000)       # → 1.0 mm
mm_value = to_mm(track.width)     # 将 nm 转换为 mm

# 毫米 → 纳米
nm_value = from_mm(1.0)           # → 1_000_000 nm
nm_value = from_mm(0.2)           # → 200_000 nm

# 实际使用示例
track.width = from_mm(0.25)       # 设置走线宽度为 0.25mm
pos_mm = to_mm(footprint.position.x)  # 读取位置（mm）

# 角度单位：度（float）
# Angle 对象使用度数，正方向为逆时针
from kipy.geometry import Angle
angle = Angle.from_degrees(90.0)  # 90 度
```

---

## 3. KiCad 主类

### `class KiCad`

顶层入口类，负责与 KiCad IPC API 服务通信。

```python
from kipy import KiCad
```

#### 构造参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `socket_path` | `str \| None` | IPC socket 路径（默认读取环境变量） |
| `client_name` | `str \| None` | 客户端唯一名称（默认随机生成） |
| `kicad_token` | `str \| None` | KiCad 实例令牌（默认读取 `KICAD_API_TOKEN`） |
| `timeout_ms` | `int` | 响应超时毫秒数（默认 2000ms） |
| `headless` | `bool` | 是否无头模式启动 kicad-cli（KiCad 11+） |
| `kicad_cli_path` | `str \| None` | kicad-cli 可执行文件路径 |
| `file_path` | `str \| None` | 无头模式下预加载的文件路径 |

#### 版本检查方法

```python
# 获取已连接的 KiCad 版本
version = kicad.get_version()
print(version)          # e.g. "9.0.2 (9.0.2)"
print(version.major)    # 9
print(version.minor)    # 0
print(version.patch)    # 2

# 获取 kipy 库对应的 API 版本
api_version = kicad.get_api_version()

# 检查版本兼容性（不匹配时抛出 FutureVersionError）
kicad.check_version()

# ping 测试连接
kicad.ping()
```

#### 文档管理

```python
from kipy.proto.common.types import DocumentType

# 获取所有打开的文档列表
docs = kicad.get_open_documents(DocumentType.DOCTYPE_PCB)
docs = kicad.get_open_documents(DocumentType.DOCTYPE_SCHEMATIC)

# 获取当前打开的 PCB（最常用）
board = kicad.get_board()

# 获取项目对象
project = kicad.get_project(docs[0])

# 无头模式：打开/关闭文档（需 KiCad 11+）
doc_spec = kicad.open_document('/path/to/file.kicad_pcb', DocumentType.DOCTYPE_PCB)
kicad.close_document(doc_spec)
```

#### 其他工具方法

```python
# 获取 KiCad 二进制文件路径
cli_path = kicad.get_kicad_binary_path('kicad-cli')

# 获取插件设置路径
settings_path = kicad.get_plugin_settings_path('com.example.myplugin')

# 获取文本包围盒（返回 Box2，单位 nm）
from kipy.common_types import Text
box = kicad.get_text_extents(text_object)

# 将文本对象转为多边形形状（用于精确渲染/碰撞检测）
shapes = kicad.get_text_as_shapes(text_object)
shapes = kicad.get_text_as_shapes([text1, text2, textbox1])

# 关闭连接
kicad.close()
```

---

## 4. Board（PCB 文档）

### `class Board`

代表一个打开的 `.kicad_pcb` 文档。通过 `KiCad.get_board()` 获取。

```python
board = kicad.get_board()
print(board.name)   # 文件名
```

### 文档操作

```python
# 保存
board.save()

# 另存为
board.save_as('/path/to/output.kicad_pcb', overwrite=True, include_project=True)

# 还原到最后保存状态
board.revert()

# 将整个板子导出为字符串（KiCad 文件格式）
board_str = board.get_as_string()

# 将当前选中内容导出为字符串
selection_str = board.get_selection_as_string()
```

### 获取板层信息

```python
from kipy.board import BoardLayer

# 获取板子中所有已启用的层
enabled_layers = board.get_enabled_layers()  # → List[BoardLayer]

# 启用/禁用层（接受层 ID 列表）
board.set_enabled_layers([BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu])

# 获取铜层数量
copper_count = board.get_copper_layer_count()  # e.g. 4

# 获取层名称（KiCad 9.0.8+）
layer_name = board.get_layer_name(BoardLayer.BL_F_Cu)  # "F.Cu"

# 获取板子原点
origin = board.get_origin()  # → Vector2（nm 单位）

# 设置板子原点
from kipy.geometry import Vector2
board.set_origin(Vector2.from_xy_mm(10.0, 10.0))
```

### 获取各类元素

```python
# 获取所有封装
footprints = board.get_footprints()  # → List[FootprintInstance]

# 获取所有走线（含弧形走线）
tracks = board.get_tracks()  # → List[Track | ArcTrack]

# 获取所有过孔
vias = board.get_vias()  # → List[Via]

# 获取所有焊盘
pads = board.get_pads()  # → List[Pad]

# 获取所有铜区/规则区域
zones = board.get_zones()  # → List[Zone]

# 获取所有图形对象（走线、文字除外）
shapes = board.get_shapes()  # → List[BoardShape 子类]

# 获取所有文本
texts = board.get_text()  # → List[BoardText | BoardTextBox]

# 获取所有标注对象
dimensions = board.get_dimensions()  # → List[Dimension 子类]

# 获取所有组（KiCad 10+）
groups = board.get_groups()  # → List[Group]

# 获取所有条码（KiCad 10.0.1+）
barcodes = board.get_barcodes()  # → List[Barcode]

# 获取所有参考图像（KiCad 10.0.1+）
ref_images = board.get_reference_images()  # → List[ReferenceImage]
```

### 通过类型过滤获取元素

```python
from kipy.proto.common.types import KiCadObjectType

# 获取特定类型的元素
items = board.get_items(KiCadObjectType.KOT_PCB_TRACE)
items = board.get_items([
    KiCadObjectType.KOT_PCB_TRACE,
    KiCadObjectType.KOT_PCB_VIA,
])

# 通过 KIID 获取（KiCad 10+）
item = board.get_items_by_id(kiid)
items = board.get_items_by_id([kiid1, kiid2])

# 通过网络过滤（KiCad 10.0.1+）
gnd_net = Net(name='GND')
items = board.get_items_by_net(gnd_net)
items = board.get_items_by_net(gnd_net, types=KiCadObjectType.KOT_PCB_TRACE)

# 通过网络类过滤（KiCad 10.0.1+）
items = board.get_items_by_netclass('Power')

# 获取铜连接的相邻元素（KiCad 10.0.1+）
connected = board.get_connected_items(track)
connected = board.get_connected_items([track, via])
```

### 修改元素

```python
# 创建新元素（返回已创建的元素列表，含服务器分配的 ID）
created = board.create_items(track)
created = board.create_items([track1, track2, via])

# 更新已有元素属性（按 UUID 匹配，覆盖其他属性）
updated = board.update_items(track)
updated = board.update_items([track1, track2])

# 删除元素
board.remove_items(track)
board.remove_items([track1, track2])

# 通过 ID 删除元素（KiCad 0.4.0+）
board.remove_items_by_id(kiid)
board.remove_items_by_id([kiid1, kiid2])
```

### 碰撞检测

```python
from kipy.geometry import Vector2

# 对一个坐标点进行碰撞检测，返回该点覆盖的所有元素
results = board.hit_test(Vector2.from_xy_mm(50.0, 30.0))
for result in results:
    print(result.item, result.distance)
```

### 选中状态管理

```python
# 获取当前选中的元素
selected = board.get_selection()

# 设置选中
board.set_selection([footprint1, track1])

# 清除选中
board.clear_selection()

# 展开选中（选中组内的所有元素）
board.expand_selection()
```

### 板子信息

```python
# 获取板子叠层结构
stackup = board.get_stackup()

# 获取/设置标题栏信息（KiCad 10.0.1+）
title_block = board.get_title_block_info()
board.set_title_block_info(title_block)

# 检查焊盘叠层与铜层的关系
is_present = board.check_padstack_presence_on_layers(pad, [BoardLayer.BL_F_Cu])
```

---

## 5. Footprint（封装）

### `class FootprintInstance`

板上元件封装的实例，通过 `board.get_footprints()` 获取。

```python
footprints = board.get_footprints()
for fp in footprints:
    print(fp.reference, fp.value, fp.position)
```

#### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `id` | `KIID` | 内部唯一 ID |
| `reference` | `str` | 元件位号（如 "R1"） |
| `value` | `str` | 元件值（如 "10k"） |
| `position` | `Vector2` | 中心坐标（nm） |
| `orientation` | `Angle` | 旋转角度（度） |
| `layer` | `BoardLayer` | 所在层（F.Cu / B.Cu） |
| `locked` | `bool` | 是否锁定 |
| `attributes` | `FootprintAttributes` | 扩展属性对象 |
| `sheet_path` | `SheetPath` | 来源原理图路径 |

#### 方法

```python
# 移动封装（修改 position 后调用 update_items）
fp.position = Vector2.from_xy_mm(50.0, 30.0)
board.update_items(fp)

# 旋转封装
fp.orientation = Angle.from_degrees(90.0)
board.update_items(fp)

# 翻面（F.Cu ↔ B.Cu）
from kipy.board import BoardFlipMode
fp.layer = BoardLayer.BL_B_Cu  # 切换层

# 获取封装的所有焊盘
pads = fp.pads  # → List[Pad]

# 获取封装的所有 Fields（字段）
fields = fp.fields  # → List[Field]

# 获取封装的 3D 模型信息
models = fp.models  # → List[Footprint3DModel]
```

### `class FootprintAttributes`

```python
attrs = fp.attributes
print(attrs.mounting_style)   # 安装方式（SMD/Through-hole）
print(attrs.exclude_from_bom) # 是否从 BOM 中排除
print(attrs.exclude_from_pos) # 是否从坐标文件中排除
```

---

## 6. Track 与 ArcTrack（走线）

### `class Track`（直线走线）

```python
from kipy.board_types import Track, BoardLayer
from kipy.geometry import Vector2
from kipy.util.units import from_mm

# 创建新走线
track = Track()
track.start = Vector2.from_xy_mm(10.0, 20.0)
track.end   = Vector2.from_xy_mm(30.0, 20.0)
track.layer = BoardLayer.BL_F_Cu
track.net   = Net(name='VCC')
track.width = from_mm(0.25)      # 0.25mm
track.locked = False

board.create_items(track)
```

#### Track 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `id` | `KIID` | 内部 UUID |
| `start` | `Vector2` | 起点坐标（nm） |
| `end` | `Vector2` | 终点坐标（nm） |
| `layer` | `BoardLayer` | 所在铜层 |
| `net` | `Net` | 所属网络 |
| `width` | `int` | 线宽（nm） |
| `locked` | `bool` | 是否锁定（0.6.0+） |

#### Track 方法

```python
# 计算走线长度（nm）
length_nm = track.length()

# 换算为 mm
from kipy.util.units import to_mm
length_mm = to_mm(track.length())
```

---

### `class ArcTrack`（弧形走线）

弧形走线用三点（起点、中点、终点）定义。

```python
from kipy.board_types import ArcTrack

arc = ArcTrack()
arc.start  = Vector2.from_xy_mm(10.0, 10.0)
arc.mid    = Vector2.from_xy_mm(15.0, 5.0)
arc.end    = Vector2.from_xy_mm(20.0, 10.0)
arc.layer  = BoardLayer.BL_F_Cu
arc.net    = Net(name='GND')
arc.width  = from_mm(0.2)
```

#### ArcTrack 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `start` | `Vector2` | 弧起点（nm） |
| `mid` | `Vector2` | 弧中点（nm） |
| `end` | `Vector2` | 弧终点（nm） |
| `layer` | `BoardLayer` | 所在铜层 |
| `net` | `Net` | 所属网络 |
| `width` | `int` | 线宽（nm） |
| `locked` | `bool` | 是否锁定（0.6.0+） |

#### ArcTrack 方法

```python
# 计算弧圆心（使用三点圆算法）
center = arc.center()  # → Optional[Vector2]

# 计算弧半径（nm）
radius = arc.radius()

# 计算弧的起始角（弧度）
start_angle = arc.start_angle()

# 计算弧的终止角（弧度）
end_angle = arc.end_angle()

# 计算弧张角（弧度，0.4.0+）
angle = arc.angle()

# 计算弧长（nm，0.3.0+）
length = arc.length()

# 计算包围盒
bbox = arc.bounding_box()  # → Box2
```

---

## 7. Via（过孔）

### `class Via`

```python
from kipy.board_types import Via, ViaType, BoardLayer
from kipy.geometry import Vector2

# 创建过孔
via = Via()
via.position = Vector2.from_xy_mm(25.0, 25.0)
via.net      = Net(name='GND')
via.via_type = ViaType.VT_THROUGH      # 通孔
via.size     = from_mm(0.8)            # 过孔直径
via.drill    = from_mm(0.4)            # 钻孔直径

board.create_items(via)
```

#### Via 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `id` | `KIID` | 内部 UUID |
| `position` | `Vector2` | 坐标（nm） |
| `net` | `Net` | 所属网络 |
| `via_type` | `ViaType` | 过孔类型 |
| `size` | `int` | 过孔外径（nm） |
| `drill` | `int` | 钻孔直径（nm） |
| `layer_pair` | `(BoardLayer, BoardLayer)` | 起止层（盲埋孔） |
| `locked` | `bool` | 是否锁定 |

#### ViaType 枚举

| 枚举值 | 说明 |
|--------|------|
| `ViaType.VT_THROUGH` | 通孔（贯穿所有层） |
| `ViaType.VT_BLIND_BURIED` | 盲孔/埋孔 |
| `ViaType.VT_MICRO` | 微孔 |

---

## 8. Pad（焊盘）

### `class Pad`

焊盘属于封装，不直接创建，通过 `board.get_pads()` 或 `footprint.pads` 获取。

```python
pads = board.get_pads()
for pad in pads:
    print(pad.number, pad.net.name, pad.position, pad.pad_type)
```

#### Pad 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `id` | `KIID` | 内部 UUID |
| `number` | `str` | 焊盘编号（如 "1", "A1"） |
| `net` | `Net` | 所属网络 |
| `position` | `Vector2` | 全局坐标（nm） |
| `pad_type` | `PadType` | 焊盘类型 |
| `locked` | `bool` | 是否锁定 |
| `pad_to_die_length` | `int` | 焊盘到芯片键合线长度（nm, 9.0.4+） |

#### PadType 枚举

| 枚举值 | 说明 |
|--------|------|
| `PadType.PT_SMD` | 表面贴装 |
| `PadType.PT_THROUGH_HOLE` | 通孔焊盘 |
| `PadType.PT_NPTH` | 非镀铜孔 |
| `PadType.PT_CONN` | 连接器焊盘 |

### `class PadStack`

焊盘叠层定义，用于描述每层的焊盘形状。

```python
padstack = pad.padstack
for layer in padstack.layers:
    print(layer.layer, layer.shape)
```

---

## 9. Zone（铜区）

### `class Zone`

可代表铜区、规则禁布区等。

```python
from kipy.board_types import Zone, ZoneFillMode, ZoneConnectionStyle
from kipy.geometry import PolygonWithHoles, Vector2

# 获取所有铜区
zones = board.get_zones()
for zone in zones:
    print(zone.net.name, zone.layer)

# 创建新铜区
zone = Zone()
zone.net   = Net(name='GND')
zone.layer = BoardLayer.BL_F_Cu

# 设置多边形轮廓
from kipy.geometry import PolyLine, PolyLineNode
outline = PolyLine()
outline.nodes = [
    PolyLineNode(Vector2.from_xy_mm(0, 0)),
    PolyLineNode(Vector2.from_xy_mm(100, 0)),
    PolyLineNode(Vector2.from_xy_mm(100, 100)),
    PolyLineNode(Vector2.from_xy_mm(0, 100)),
]
zone.outline = outline
board.create_items(zone)
```

#### Zone 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `id` | `KIID` | 内部 UUID |
| `net` | `Net` | 所属网络 |
| `layer` | `BoardLayer` | 所在层 |
| `fill_mode` | `ZoneFillMode` | 填充模式 |
| `connection_style` | `ZoneConnectionStyle` | 连接方式 |
| `outline` | `PolyLine` | 外轮廓 |
| `zone_type` | `ZoneType` | 区域类型 |

#### ZoneConnectionStyle 枚举

| 枚举值 | 说明 |
|--------|------|
| `ZoneConnectionStyle.ZCS_INHERITED` | 继承 |
| `ZoneConnectionStyle.ZCS_NONE` | 无连接 |
| `ZoneConnectionStyle.ZCS_THERMAL` | 热焊盘 |
| `ZoneConnectionStyle.ZCS_FULL` | 完全连接 |

---

## 10. BoardShape（图形对象）

图形对象是放置在任意层上的非电气图形，包括线段、圆、弧、多边形、矩形、贝塞尔曲线。

### 基类 `class BoardShape`

属性：

| 属性 | 类型 | 说明 |
|------|------|------|
| `id` | `KIID` | 内部 UUID |
| `layer` | `BoardLayer` | 所在层 |
| `locked` | `bool` | 是否锁定 |
| `attributes` | `GraphicAttributes` | 描边/填充属性 |

### 具体形状子类

```python
from kipy.board_types import (
    BoardSegment,   # 线段
    BoardArc,       # 弧线
    BoardCircle,    # 圆形
    BoardRectangle, # 矩形
    BoardPolygon,   # 多边形
    BoardBezier,    # 贝塞尔曲线
)

# 创建线段（Edge.Cuts 上的板边）
seg = BoardSegment()
seg.start = Vector2.from_xy_mm(0, 0)
seg.end   = Vector2.from_xy_mm(100, 0)
seg.layer = BoardLayer.BL_Edge_Cuts
seg.attributes.stroke.width = from_mm(0.05)
board.create_items(seg)

# 创建圆形
circle = BoardCircle()
circle.center = Vector2.from_xy_mm(50, 50)
circle.radius = from_mm(10)     # 从中心到边缘的距离（nm）
circle.layer  = BoardLayer.BL_F_Silkscreen

# 创建多边形（直接指定 PolygonWithHoles）
poly = BoardPolygon()
poly.polygon = PolygonWithHoles(outline=[
    Vector2.from_xy_mm(0, 0),
    Vector2.from_xy_mm(10, 0),
    Vector2.from_xy_mm(5, 10),
])
poly.layer = BoardLayer.BL_F_Cu
board.create_items(poly)
```

---

## 11. Net（网络）

### `class Net`

```python
from kipy.board_types import Net

# 创建网络对象
net = Net(name='GND')
net = Net(name='VCC')

# 获取板上所有网络
nets = board.get_nets()  # → List[Net]

# 比较网络（按名称比较）
assert Net(name='GND') == Net(name='GND')

# 设置走线网络
track.net = Net(name='VCC')
```

> ⚠️ `Net.code` 属性已在 0.4.0 中废弃，不应在 API 客户端中使用网络编号。

---

## 12. 几何类型

### `class Vector2`

2D 坐标/向量，内部存储为 nm（`int`）。

```python
from kipy.geometry import Vector2

# 构造
v = Vector2.from_xy(1_000_000, 2_000_000)   # (1mm, 2mm)
v = Vector2.from_xy_mm(1.0, 2.0)            # 更方便

# 属性
v.x  # nm（int）
v.y  # nm（int）

# 运算
v1 + v2   # 向量加法
v1 - v2   # 向量减法
v * 2.0   # 标量乘法
-v        # 取反

# 计算
v.length()         # 长度（float，nm）
v.angle()          # 方向角（弧度）
v.angle_degrees()  # 方向角（度）
v.rotate(angle, center)  # 原地旋转（0.4.0+）
```

---

### `class Vector3D`

3D 坐标，用于 3D 模型位置/旋转。

```python
from kipy.geometry import Vector3D

v3 = Vector3D.from_xyz(0, 0, 1_000_000)   # (0, 0, 1mm)
v3.x  # float，nm
v3.y  # float，nm
v3.z  # float，nm
v3.length()  # 3D 长度
```

---

### `class Box2`

2D 包围盒描述矩形区域。

```python
from kipy.geometry import Box2, Vector2

# 构造
box = Box2.from_xywh(x_nm, y_nm, w_nm, h_nm)
box = Box2.from_pos_size(pos_v2, size_v2)
box = Box2.from_points([v1, v2, v3])  # 包含所有点的最小包围盒（0.7.0+）

# 属性
box.pos    # → Vector2（左上角坐标）
box.size   # → Vector2（宽高）

# 方法
box.center()      # 中心点
box.move(delta)   # 平移
box.merge(other)  # 合并另一个 Box2 或 Vector2
box.inflate(amount_nm)  # 向外扩展（nm）
```

---

### `class Angle`

旋转角度，内部存储为度数。

```python
from kipy.geometry import Angle

angle = Angle.from_degrees(45.0)
angle.degrees       # → float（度）
angle.to_radians()  # → float（弧度）
```

---

### `class PolyLine` 和 `PolyLineNode`

用于描述多段线轮廓（区域边界、焊盘形状等）。

```python
from kipy.geometry import PolyLine, PolyLineNode, Vector2

line = PolyLine()
line.nodes = [
    PolyLineNode(Vector2.from_xy_mm(0, 0)),
    PolyLineNode(Vector2.from_xy_mm(10, 0)),
    PolyLineNode(Vector2.from_xy_mm(10, 10)),
]
```

---

### `class PolygonWithHoles`

含孔多边形，用于铜区轮廓、贴片形状等。

```python
from kipy.geometry import PolygonWithHoles, Vector2

polygon = PolygonWithHoles(
    outline=[
        Vector2.from_xy_mm(0, 0),
        Vector2.from_xy_mm(20, 0),
        Vector2.from_xy_mm(20, 20),
        Vector2.from_xy_mm(0, 20),
    ],
    holes=[
        # 每个 hole 本身是一个 List[Vector2]
        [
            Vector2.from_xy_mm(5, 5),
            Vector2.from_xy_mm(15, 5),
            Vector2.from_xy_mm(15, 15),
            Vector2.from_xy_mm(5, 15),
        ]
    ]
)
```

---

### 弧形工具函数

```python
from kipy.geometry import (
    arc_center,          # (start, mid, end) → Optional[Vector2]
    arc_radius,          # (start, mid, end) → float
    arc_start_angle,     # (start, mid, end) → Optional[float]（弧度）
    arc_end_angle,       # (start, mid, end) → Optional[float]（弧度）
    arc_start_angle_degrees,  # → Optional[float]（度）
    arc_end_angle_degrees,    # → Optional[float]（度）
    arc_angle,           # (start, mid, end) → Optional[float]（张角，弧度）
    arc_bounding_box,    # (start, mid, end) → Box2
    normalize_angle_degrees,       # 角度归一化到 [0, 360)
    normalize_angle_radians,       # 角度归一化到 [0, 2π)
    normalize_angle_pi_radians,    # 角度归一化到 [-π, π)
)
```

---

## 13. 公共类型（Common Types）

### `class Color`

```python
from kipy.common_types import Color

color = Color()
color.r = 255  # 0-255
color.g = 128
color.b = 0
color.a = 255  # 透明度
```

### `class Commit`

事务提交句柄，见 [提交事务机制](#16-提交事务机制-commit)。

### 形状类型（用于 Schematic 或通用形状）

- `Arc` — 弧线
- `Bezier` — 贝塞尔曲线
- `Circle` — 圆形
- `Polygon` — 多边形
- `Rectangle` — 矩形
- `Segment` — 线段
- `CompoundShape` — 复合形状（文本转多边形结果）

### `class StrokeAttributes`

```python
from kipy.common_types import StrokeAttributes

stroke = StrokeAttributes()
stroke.width = from_mm(0.1)  # 线宽（nm）
# stroke.style  → 线型枚举
```

### `class GraphicAttributes`

```python
attrs.stroke  # → StrokeAttributes
attrs.fill    # → GraphicFillAttributes
```

### `class TextAttributes`

```python
from kipy.common_types import TextAttributes

ta = TextAttributes()
ta.font_size  = from_mm(1.5)  # 字号（nm）
ta.bold       = True
ta.italic     = False
ta.visible    = True          # 已在 0.3.0 从 TextAttributes 移入 Field
```

### `class TitleBlockInfo`

```python
title_block = board.get_title_block_info()  # KiCad 10.0.1+
title_block.title    = "My PCB Design"
title_block.revision = "1.0"
title_block.date     = "2026-03-26"
title_block.company  = "ACME Corp"
board.set_title_block_info(title_block)
```

---

## 14. Project（项目）

### `class Project`

包含项目级别的设置，例如网络类。

```python
project = kicad.get_project(docs[0])
project = board.get_project()

# 获取所有网络类
net_classes = project.get_net_classes()  # → List[NetClass]

# 保存项目
project.save()
```

### `class NetClass`

```python
nc = project.get_net_classes()[0]
print(nc.name)           # 网络类名称
print(nc.clearance)      # 间距规则（nm）
print(nc.track_width)    # 走线宽度（nm）
print(nc.via_diameter)   # 过孔直径（nm）
print(nc.via_drill)      # 过孔钻孔（nm）
```

---

## 15. BoardStackup（板层叠结构）

```python
stackup = board.get_stackup()
print(stackup.layers)   # 从顶到底排列的层列表

for layer in stackup.layers:
    print(layer.layer)         # BoardLayer 枚举值
    print(layer.user_name)     # 层名称（如 "F.Cu"）
    print(layer.thickness)     # 层厚度（nm）
    print(layer.material_name) # 材质（如 "FR4"）
    print(layer.enabled)       # 是否启用
    print(layer.type)          # 层类型（铜层/介质层/蒙版层等）

# 介质层的属性
for sub_layer in layer.dielectric.layers:
    print(sub_layer.epsilon_r)        # 相对介电常数
    print(sub_layer.loss_tangent)     # 损耗角正切
    print(sub_layer.material_name)    # 材质
    print(sub_layer.thickness)        # 厚度（nm）
```

---

## 16. 提交事务机制（Commit）

Commit 是对 KiCad 撤销/重做历史的事务控制。

```python
# 不使用 Commit（每次修改立即生效，各自独立进入撤销历史）
track.width = from_mm(0.3)
board.update_items(track)

# 使用 Commit（将多步操作合并为一次撤销历史记录）
commit = board.begin_commit()

try:
    # 在 commit 期间进行的改动不会立即刷新到 KiCad 编辑器
    for track in tracks:
        track.width = from_mm(0.3)
    board.update_items(tracks)

    # 提交，写入撤销历史
    board.push_commit(commit, message="批量修改走线宽度")

except Exception as e:
    # 回滚，丢弃所有改动
    board.drop_commit(commit)
    raise
```

---

## 17. 导出功能（Export Jobs）

所有导出函数均返回 `JobResult` 对象。

```python
from kipy.board import BoardLayer

# 导出 Gerber
board.export_gerbers(
    output_path='/output/gerbers/',
    layers=[BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu, BoardLayer.BL_Edge_Cuts]
)

# 导出钻孔文件
from kipy.board import DrillFormat
board.export_drill(
    output_path='/output/',
    format=DrillFormat.DF_EXCELLON
)

# 导出 PDF
board.export_pdf(
    output_path='/output/board.pdf',
    include_metadata=True,
    single_document=True
)

# 导出 SVG
board.export_svg(output_path='/output/board.svg')

# 导出 DXF
from kipy.board import Units
board.export_dxf(output_path='/output/board.dxf', units=Units.U_MM)

# 导出 3D 模型（STEP/WRL 等）
board.export_3d(output_path='/output/board.step')

# 导出光线追踪渲染图
board.export_render(output_path='/output/render.png')

# 导出坐标文件（贴片机）
board.export_position(output_path='/output/pick_and_place.csv')

# 导出 IPC-2581
board.export_ipc2581(output_path='/output/board.xml')

# 导出 ODB++
board.export_odb(output_path='/output/board.odb')

# 导出 GenCAD
board.export_gencad(output_path='/output/board.cad')

# 导出 IPC-D-356 网表
board.export_ipc_d356(output_path='/output/board.d356')

# 导出统计信息
board.export_stats(output_path='/output/stats.txt')

# 导出 PostScript
board.export_ps(output_path='/output/')
```

---

## 18. 枚举类型速查

### BoardLayer（常用层）

```python
from kipy.board_types import BoardLayer

# 铜层
BoardLayer.BL_F_Cu          # 正面铜层
BoardLayer.BL_B_Cu          # 背面铜层
BoardLayer.BL_In1_Cu        # 内层1
BoardLayer.BL_In2_Cu        # 内层2
# ... 内层铜层以此类推 BL_In3_Cu ... BL_In30_Cu

# 丝印层
BoardLayer.BL_F_Silkscreen  # 正面丝印
BoardLayer.BL_B_Silkscreen  # 背面丝印

# 阻焊层
BoardLayer.BL_F_Mask        # 正面阻焊
BoardLayer.BL_B_Mask        # 背面阻焊

# 助焊层
BoardLayer.BL_F_Paste       # 正面助焊
BoardLayer.BL_B_Paste       # 背面助焊

# 板边
BoardLayer.BL_Edge_Cuts     # 板型轮廓

# 用户层
BoardLayer.BL_User_1        # 用户层1
# ... BL_User_45（0.3.0+ 支持 User.10 ~ User.45）

# 蚀刻层（设计图纸）
BoardLayer.BL_F_Fab         # 正面制造层
BoardLayer.BL_B_Fab         # 背面制造层
BoardLayer.BL_F_Cu_Courtyard  # 正面封装外框
BoardLayer.BL_B_Cu_Courtyard  # 背面封装外框
```

### 层工具函数

```python
from kipy.util.board_layer import (
    canonical_name,          # layer → str（规范名称如 "F.Cu"）
    is_copper_layer,         # layer → bool
    iter_copper_layers,      # (count) → Iterator[BoardLayer]
    layer_from_canonical_name,  # str → BoardLayer
)

# 用法示例
name = canonical_name(BoardLayer.BL_F_Cu)   # "F.Cu"
is_cu = is_copper_layer(BoardLayer.BL_F_Cu) # True

for layer in iter_copper_layers(4):
    print(canonical_name(layer))  # F.Cu, In1.Cu, In2.Cu, B.Cu
```

### KiCadObjectType（常用类型）

```python
from kipy.proto.common.types import KiCadObjectType

KiCadObjectType.KOT_PCB_TRACE       # 走线
KiCadObjectType.KOT_PCB_ARC         # 弧形走线
KiCadObjectType.KOT_PCB_VIA         # 过孔
KiCadObjectType.KOT_PCB_FOOTPRINT   # 封装
KiCadObjectType.KOT_PCB_PAD         # 焊盘
KiCadObjectType.KOT_PCB_ZONE        # 铜区
KiCadObjectType.KOT_PCB_SHAPE       # 图形对象
KiCadObjectType.KOT_PCB_TEXT        # 文本
KiCadObjectType.KOT_PCB_TEXTBOX     # 文本框
KiCadObjectType.KOT_PCB_DIMENSION   # 标注
KiCadObjectType.KOT_PCB_GROUP       # 组
KiCadObjectType.KOT_PCB_BARCODE     # 条码
KiCadObjectType.KOT_PCB_REFERENCE_IMAGE  # 参考图像
```

---

## 19. 错误处理

```python
from kipy.errors import ApiError, ConnectionError, FutureVersionError

try:
    kicad = KiCad()
    board = kicad.get_board()

except ConnectionError as e:
    # KiCad 未运行或 API 服务未启用
    print(f"无法连接到 KiCad: {e}")

except FutureVersionError as e:
    # kipy 库版本比已安装的 KiCad 旧
    print(f"版本不兼容: {e}")

except ApiError as e:
    # API 调用失败（如请求的文档不存在）
    print(f"API 错误: {e}")
```

### 常见错误场景

| 错误类型 | 原因 | 解决方案 |
|----------|------|----------|
| `ConnectionError` | KiCad 未运行 / API 服务未启用 | 启动 KiCad，`Preferences → Plugins` 启用 API |
| `ApiError: Expected to be able to retrieve at least one board` | 没有打开的 PCB 文档 | 在 KiCad 中打开 `.kicad_pcb` 文件 |
| `FutureVersionError` | kipy 版本太旧 | `pip install --upgrade kicad-python` |
| 超时 | 复杂操作超出 `timeout_ms` | 增大超时：`KiCad(timeout_ms=10000)` |

---

## 20. 实用工具函数

### 单位转换（`kipy.util.units`）

```python
from kipy.util.units import to_mm, from_mm

to_mm(1_000_000)    # → 1.0  （nm → mm）
from_mm(1.0)        # → 1_000_000  （mm → nm）

# 可以对任意数值操作
to_mm(track.width)        # 走线宽度转 mm
from_mm(0.25)             # 0.25mm 转 nm
int(from_mm(1.6))         # 板厚 1.6mm 转 nm
```

### 打包工具（内部）

```python
from kipy.util import pack_any
# pack_any(proto_msg) → google.protobuf.Any，用于 create_items/update_items 内部
```

---

## 21. 完整示例

### 示例 1：列出所有封装及坐标

```python
from kipy import KiCad
from kipy.util.units import to_mm

with KiCad() as kicad:
    board = kicad.get_board()
    footprints = board.get_footprints()

    print(f"{'Ref':<10} {'Value':<20} {'X(mm)':<10} {'Y(mm)':<10} {'Layer'}")
    for fp in footprints:
        x = to_mm(fp.position.x)
        y = to_mm(fp.position.y)
        print(f"{fp.reference:<10} {fp.value:<20} {x:<10.3f} {y:<10.3f} {fp.layer}")
```

---

### 示例 2：删除所有走线

```python
from kipy import KiCad

with KiCad() as kicad:
    board = kicad.get_board()
    commit = board.begin_commit()
    try:
        tracks = board.get_tracks()
        board.remove_items(tracks)
        board.push_commit(commit, message="清空所有走线")
        board.save()
        print(f"删除了 {len(tracks)} 条走线")
    except Exception:
        board.drop_commit(commit)
        raise
```

---

### 示例 3：批量修改走线宽度

```python
from kipy import KiCad
from kipy.util.units import from_mm

with KiCad() as kicad:
    board = kicad.get_board()
    tracks = board.get_tracks()

    commit = board.begin_commit()
    try:
        for track in tracks:
            if track.net.name == 'GND':
                track.width = from_mm(0.5)   # GND 线宽 0.5mm
            else:
                track.width = from_mm(0.25)  # 其他线宽 0.25mm

        board.update_items(list(tracks))
        board.push_commit(commit, message="统一走线宽度")
        board.save()
    except Exception:
        board.drop_commit(commit)
        raise
```

---

### 示例 4：在指定位置添加走线

```python
from kipy import KiCad
from kipy.board_types import Track, BoardLayer, Net
from kipy.geometry import Vector2
from kipy.util.units import from_mm

with KiCad() as kicad:
    board = kicad.get_board()

    commit = board.begin_commit()
    try:
        track = Track()
        track.start = Vector2.from_xy_mm(10.0, 20.0)
        track.end   = Vector2.from_xy_mm(40.0, 20.0)
        track.layer = BoardLayer.BL_F_Cu
        track.net   = Net(name='VCC')
        track.width = from_mm(0.3)

        board.create_items(track)
        board.push_commit(commit, message="添加 VCC 走线")
        board.save()
    except Exception:
        board.drop_commit(commit)
        raise
```

---

### 示例 5：查询连接到特定网络的所有元素

```python
from kipy import KiCad
from kipy.board_types import Net

with KiCad() as kicad:
    board = kicad.get_board()
    gnd = Net(name='GND')

    # 获取 GND 网络的所有铜元素（走线+过孔+焊盘）
    items = board.get_items_by_net(gnd)
    for item in items:
        print(type(item).__name__, item.id)
```

---

### 示例 6：移动封装

```python
from kipy import KiCad
from kipy.geometry import Vector2

with KiCad() as kicad:
    board = kicad.get_board()
    footprints = board.get_footprints()

    # 找到 U1
    u1 = next((fp for fp in footprints if fp.reference == 'U1'), None)
    if u1:
        commit = board.begin_commit()
        try:
            u1.position = Vector2.from_xy_mm(50.0, 40.0)
            board.update_items(u1)
            board.push_commit(commit, message="移动 U1")
            board.save()
        except Exception:
            board.drop_commit(commit)
            raise
```

---

### 示例 7：绘制板边（矩形板型）

```python
from kipy import KiCad
from kipy.board_types import BoardSegment, BoardLayer
from kipy.geometry import Vector2
from kipy.util.units import from_mm

def draw_board_outline(board, x, y, width, height):
    """在 Edge.Cuts 层绘制矩形板边"""
    corners = [
        (x, y), (x + width, y),
        (x + width, y + height), (x, y + height),
    ]
    segments = []
    for i in range(4):
        x1, y1 = corners[i]
        x2, y2 = corners[(i + 1) % 4]
        seg = BoardSegment()
        seg.start = Vector2.from_xy_mm(x1, y1)
        seg.end   = Vector2.from_xy_mm(x2, y2)
        seg.layer = BoardLayer.BL_Edge_Cuts
        seg.attributes.stroke.width = from_mm(0.05)
        segments.append(seg)
    return segments

with KiCad() as kicad:
    board = kicad.get_board()
    commit = board.begin_commit()
    try:
        segs = draw_board_outline(board, 0, 0, 100, 80)  # 100x80mm
        board.create_items(segs)
        board.push_commit(commit, message="绘制板边")
        board.save()
    except Exception:
        board.drop_commit(commit)
        raise
```

---

## 版本历史摘要

| 版本 | KiCad 对应版本 | 主要新增功能 |
|------|---------------|-------------|
| 0.6.0 | 9.0.x | `Track.locked`, `ArcTrack.locked`, `Board.get_layer_name`, `Field.name` setter |
| 0.5.0 | 9.0.4-9.0.5 | `Pad.pad_to_die_length`, 层管理 API, `BoardCircle.rotate` |
| 0.4.0 | 9.0.x | 封装移动/旋转修复, `Net.name` setter, `add_polygon` 改进, `remove_items_by_id` |
| 0.3.0 | 9.0.0 | 安装方式属性, `board.get/set_origin`, `ArcTrack.length`, 完整层支持 (`User.10-45`) |
| 0.2.0 | 9.0.0 | 选中状态管理 API（GA 发布更新）|
| 0.1.x | 9.0.0-rc1 | 首个正式版本，支持大部分 PCB 编辑 API |

---

*文档生成时间：2026-03-26 | 基于 kicad-python v0.6.0 源码及官方文档整理*
