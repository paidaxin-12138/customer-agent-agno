#!/usr/bin/env python3
"""
创建应用图标
将 PNG 转换为 ICNS 格式
"""
import os
from pathlib import Path

try:
    from PIL import Image
    has_pil = True
except ImportError:
    has_pil = False

def create_icns_from_png(png_path, output_path):
    """将 PNG 转换为 ICNS"""
    if not has_pil:
        print("❌ 未安装 Pillow，尝试使用系统工具...")
        return create_icns_with_sips(png_path, output_path)
    
    # 创建临时图标集
    iconset_dir = Path("/tmp/app_icon.iconset")
    iconset_dir.mkdir(exist_ok=True)
    
    # 打开原始图标
    img = Image.open(png_path)
    
    # 生成各种尺寸的图标
    sizes = [
        (16, 16),
        (32, 32),
        (64, 64),
        (128, 128),
        (256, 256),
        (512, 512),
        (1024, 1024),
    ]
    
    for size in sizes:
        # 标准尺寸
        resized = img.resize(size, Image.Resampling.LANCZOS)
        resized.save(iconset_dir / f"icon_{size[0]}x{size[1]}.png")
        
        # 2x 尺寸
        resized_2x = img.resize((size[0]*2, size[1]*2), Image.Resampling.LANCZOS)
        resized_2x.save(iconset_dir / f"icon_{size[0]}x{size[1]}@2x.png")
    
    # 使用 iconutil 转换为 ICNS
    os.system(f"iconutil -c icns {iconset_dir} -o {output_path}")
    
    # 清理临时文件
    import shutil
    shutil.rmtree(iconset_dir)
    
    print(f"✅ 图标已创建：{output_path}")
    return True

def create_icns_with_sips(png_path, output_path):
    """使用 macOS 系统工具 sips 创建图标"""
    import tempfile
    import shutil
    
    # 创建临时图标集
    iconset_dir = Path(tempfile.mkdtemp()) / "app_icon.iconset"
    iconset_dir.mkdir(exist_ok=True)
    
    sizes = [16, 32, 64, 128, 256, 512, 1024]
    
    for size in sizes:
        png_name = f"icon_{size}x{size}.png"
        os.system(f"sips -z {size} {size} '{png_path}' --out '{iconset_dir}/{png_name}' 2>/dev/null")
    
    # 转换
    os.system(f"iconutil -c icns {iconset_dir} -o {output_path}")
    
    # 清理
    shutil.rmtree(iconset_dir.parent)
    
    print(f"✅ 图标已创建：{output_path}")
    return True

if __name__ == "__main__":
    # 查找图标文件
    icon_paths = [
        Path("icon/app_icon.png"),
        Path("icon.png"),
        Path("assets/icon.png"),
    ]
    
    png_path = None
    for p in icon_paths:
        if p.exists():
            png_path = p
            break
    
    if not png_path:
        print("❌ 未找到 PNG 图标文件")
        exit(1)
    
    print(f"📍 找到图标：{png_path}")
    
    # 输出路径
    output_path = Path("启动 AI 客服.app/Contents/Resources/app_icon.icns")
    output_path.parent.mkdir(exist_ok=True)
    
    # 创建图标
    create_icns_from_png(png_path, output_path)
