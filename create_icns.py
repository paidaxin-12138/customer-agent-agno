#!/usr/bin/env python3
"""
创建 macOS ICNS 图标
"""
import os
import shutil
from pathlib import Path

try:
    from PIL import Image
    has_pil = True
except ImportError:
    print("❌ 未安装 Pillow，请先运行：uv add pillow")
    exit(1)

def create_icns():
    # 路径
    icon_dir = Path("/tmp/app_icon.iconset")
    if icon_dir.exists():
        shutil.rmtree(icon_dir)
    icon_dir.mkdir(exist_ok=True)
    
    # 打开原始图标
    png_path = Path("icon/app_icon.png")
    if not png_path.exists():
        print(f"❌ 图标文件不存在：{png_path}")
        return False
    
    img = Image.open(png_path)
    print(f"📍 使用图标：{png_path} ({img.size[0]}x{img.size[1]})")
    
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
        output_path = icon_dir / f"icon_{size[0]}x{size[1]}.png"
        resized.save(output_path, "PNG")
        print(f"✅ 创建 {size[0]}x{size[1]}")
        
        # 2x 尺寸
        if size[0] <= 512:  # 避免超过原始尺寸
            size_2x = (size[0]*2, size[1]*2)
            resized_2x = img.resize(size_2x, Image.Resampling.LANCZOS)
            output_path_2x = icon_dir / f"icon_{size[0]}x{size[1]}@2x.png"
            resized_2x.save(output_path_2x, "PNG")
            print(f"✅ 创建 {size_2x[0]}x{size_2x[1]} @2x")
    
    # 使用 iconutil 转换为 ICNS
    output_icns = Path("启动 AI 客服.app/Contents/Resources/app_icon.icns")
    output_icns.parent.mkdir(parents=True, exist_ok=True)
    
    ret = os.system(f"iconutil -c icns {icon_dir} -o {output_icns}")
    
    # 清理临时文件
    shutil.rmtree(icon_dir)
    
    if ret == 0:
        print(f"✅ ICNS 图标已创建：{output_icns}")
        return True
    else:
        print("❌ ICNS 创建失败")
        return False

if __name__ == "__main__":
    create_icns()
