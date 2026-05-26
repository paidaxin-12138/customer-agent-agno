#!/usr/bin/env python3
"""
为知识库添加 Excel 导入支持
"""
import re
from pathlib import Path

# 读取文件
file_path = Path("Agent/CustomerAgent/agent_knowledge.py")
content = file_path.read_text(encoding="utf-8")

# 查找要插入的位置（在 PDF 解析之前）
pdf_pattern = r"(        elif suffix == \"\.pdf\":)"

# Excel 解析代码
excel_code = """        elif suffix in {".xlsx", ".xls"}:
            # Excel 文件解析
            try:
                import pandas as pd
                if suffix == ".xlsx":
                    df = pd.read_excel(str(path), engine="openpyxl")
                else:  # .xls
                    df = pd.read_excel(str(path), engine="xlrd")
                
                # 将所有列的内容合并
                content_parts = []
                for col in df.columns:
                    col_content = df[col].dropna().astype(str).tolist()
                    if col_content:
                        content_parts.append(f"## {col}\\n" + "\\n".join(col_content))
                
                content = "\\n\\n".join(content_parts).strip()
                
                if not content:
                    # 尝试读取所有 sheet
                    excel_file = pd.ExcelFile(str(path))
                    all_parts = []
                    for sheet_name in excel_file.sheet_names:
                        df_sheet = pd.read_excel(excel_file, sheet_name=sheet_name)
                        sheet_parts = []
                        for col in df_sheet.columns:
                            col_content = df_sheet[col].dropna().astype(str).tolist()
                            if col_content:
                                sheet_parts.append(f"### {sheet_name} - {col}\\n" + "\\n".join(col_content))
                        all_parts.extend(sheet_parts)
                    content = "\\n\\n".join(all_parts).strip()
                    
            except ImportError as ie:
                raise RuntimeError(f"Excel 解析失败：缺少依赖库 - {ie}. 请运行 `uv add openpyxl xlrd`") from ie
            except Exception as e:
                raise RuntimeError(f"Excel 解析失败：{e}") from e
"""

# 在 PDF 解析之前插入 Excel 解析代码
new_content = re.sub(pdf_pattern, excel_code + r"\1", content)

# 写回文件
file_path.write_text(new_content, encoding="utf-8")

print("✅ 已成功添加 Excel 导入支持！")
print("\n现在支持的文件格式：")
print("  ✅ .txt, .md, .csv")
print("  ✅ .json")
print("  ✅ .xlsx, .xls (Excel)")
print("  ✅ .pdf")
print("\n请运行以下命令安装依赖：")
print("  uv add openpyxl xlrd pandas")
