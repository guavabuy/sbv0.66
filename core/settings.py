import os
from pathlib import Path

class Settings:
    """
    SecondBrain 核心配置管理。
    """
    ROOT_DIR = Path(__file__).resolve().parents[1]
    
    # 数据目录：优先环境变量，其次项目根目录下的 data/，兼容旧 outputs/
    DATA_DIR = Path(os.getenv("SB_DATA_DIR", "")).expanduser() if os.getenv("SB_DATA_DIR") else (ROOT_DIR / "data")
    LEGACY_DATA_DIR = ROOT_DIR / "outputs"
    
    @classmethod
    def get_data_path(cls, filename: str) -> Path:
        """
        获取数据文件路径，自动处理 data/ 和 outputs/ 的兼容。
        """
        new_path = cls.DATA_DIR / filename
        old_path = cls.LEGACY_DATA_DIR / filename
        return new_path if new_path.exists() else old_path

    # 模型配置默认值
    DEFAULT_LLM_PROVIDER = "google_genai"
    DEFAULT_LLM_MODEL = "gemini-2.5-flash"
    
settings = Settings()

