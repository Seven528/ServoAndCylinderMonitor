import pandas as pd
from pathlib import Path
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from src.data_handling import parse_ltime, convert_ltime_columns

# CSV 文件路径
file_path = r"C:\Users\WSE6SZH\OneDrive - Bosch Group\WSE6SZH\00_DA\000_DA project\ServoAndCylinderMonitor\data\input\MECN_MOE6_RUNTIMEPARAMMONITOR_WEBSCADA_JSON_PROCESSED_V02_202610121415.csv"

# 读取 CSV 文件，转换为 DataFrame
df = pd.read_csv(file_path, encoding="utf-8-sig")


# 查看数据类型
print(df.dtypes)

# 查看数据
df_1000 = df.head(1000)

ltime_columns = [
    "MOVETOTBASTIME",
    "MOVETOWORKTIME",
    "ACTTIME",
    "AVGTIME",
    "MINTIME",
    "MAXTIME",
    "TOTTIME"
]

df_1000 = convert_ltime_columns(
    df=df_1000,
    columns=ltime_columns,
    byteorder="little",
    include_ns=False
)
df_1000.to_excel(
    r"C:\Users\WSE6SZH\OneDrive - Bosch Group\WSE6SZH\00_DA\000_DA project\ServoAndCylinderMonitor\data\output\df_1000.xlsx",
    index=False)