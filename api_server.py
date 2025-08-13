#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import uvicorn
import logging
import time
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import sys
import os
import traceback
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 直接导入必要的模块，避免循环依赖
try:
    from source.module.manager import Manager
    from source.module import logging as module_logging
    from source.translation import _
    from source.expansion import Cleaner, beautify_string
except ImportError as e:
    logging.error(f"导入模块失败: {e}")
    # 如果导入失败，创建简单的替代类
    class Manager:
        def __init__(self):
            pass
    
    class Cleaner:
        def __init__(self):
            pass
    
    def _(text):
        return text
    
    def beautify_string(text):
        return text
from config.auth_middleware import APIAuthMiddleware, get_client_info

# 尝试导入生产环境配置，如果没有则使用简单配置
try:
    from config.production_config import get_production_config, get_production_auth, setup_production_environment
    # 设置生产环境
    setup_production_environment()
    # 获取生产环境配置
    api_config = get_production_config()
    env_config = get_production_auth().get_environment_info()
    print("✅ 使用生产环境配置")
except ImportError:
    from config.simple_config import get_simple_config, get_simple_auth, setup_simple_environment
    # 设置简单环境
    setup_simple_environment()
    # 获取简单配置
    api_config = get_simple_config()
    env_config = get_simple_auth().get_environment_info()
    print("⚠️ 使用简单环境配置")

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 获取API根路径配置
api_root_path = os.getenv("API_ROOT_PATH", "")
if api_root_path and not api_root_path.startswith("/"):
    api_root_path = "/" + api_root_path

# 创建FastAPI应用
app = FastAPI(
    title="XHS Downloader API",
    description="小红书下载器API服务 - 支持API Key认证",
    version="1.0.0",
    docs_url=f"{api_root_path}/docs" if env_config["debug"] else None,
    redoc_url=f"{api_root_path}/redoc" if env_config["debug"] else None,
    root_path=api_root_path
)

# 添加CORS中间件 - 允许所有跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有域名
    allow_credentials=True,  # 允许携带凭证
    allow_methods=["*"],  # 允许所有HTTP方法
    allow_headers=["*"],  # 允许所有请求头
)

# 添加认证中间件（自动选择配置）
app.add_middleware(APIAuthMiddleware)

# 全局变量

@app.on_event("startup")
async def startup_event():
    """应用启动时初始化"""
    try:
        # 修复：使用容器内的正确路径
        project_root = Path(__file__).parent
        
        # 确保下载目录存在
        downloads_dir = project_root / "downloads"
        downloads_dir.mkdir(exist_ok=True)
        logger.info(f"✅ 下载目录已创建/确认: {downloads_dir}")
        
        # 创建临时目录
        temp_dir = project_root / "temp"
        temp_dir.mkdir(exist_ok=True)
        logger.info(f"✅ 临时目录已创建/确认: {temp_dir}")
        
        # 创建Volume目录（如果ROOT常量需要）
        volume_dir = project_root / "Volume"
        volume_dir.mkdir(exist_ok=True)
        logger.info(f"✅ Volume目录已创建/确认: {volume_dir}")
        
        # 创建日志目录
        log_dir = project_root / "logs"
        log_dir.mkdir(exist_ok=True)
        logger.info(f"✅ 日志目录已创建/确认: {log_dir}")
        
        # 目录初始化完成
        
        # 记录启动信息
        logger.info(f"✅ API服务器启动成功")
        logger.info(f"🌍 环境: {env_config['environment']}")
        logger.info(f"🔐 认证: {'启用' if env_config['api_enabled'] else '禁用'}")
        logger.info(f"🚀 端口: {env_config['port']}")
        logger.info(f"⚡ 频率限制: {'启用' if api_config.rate_limit_enabled else '禁用'}")
        
    except Exception as e:
        logger.error(f"❌ API服务器启动失败: {e}")
        logger.error(f"错误堆栈: {traceback.format_exc()}")

class DownloadRequest(BaseModel):
    """下载请求模型"""
    url: str
    save_path: Optional[str] = None
    quality: Optional[str] = "high"
    cookie: Optional[str] = ""  # 添加Cookie支持
    proxy: Optional[str] = None  # 添加代理支持
    image_download: Optional[bool] = False  # 是否下载图片，默认为false
    video_download: Optional[bool] = True   # 是否下载视频，默认为true
    live_download: Optional[bool] = False   # 是否下载动图，默认为false

class DownloadResponse(BaseModel):
    """下载响应模型"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None

@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "XHS Downloader API 服务正在运行",
        "environment": env_config["environment"],
        "auth_enabled": env_config["api_enabled"],
        "version": "1.0.0"
    }

@app.get("/health")
async def health_check():
    """健康检查"""
    try:
        return {
            "status": "healthy",
            "service": "XHS Downloader API",
            "environment": env_config["environment"],
            "auth_enabled": env_config["api_enabled"],
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "service": "XHS Downloader API",
                "message": f"服务异常: {str(e)}",
                "timestamp": time.time()
            }
        )

@app.get("/info")
async def get_info():
    """获取服务信息"""
    try:
        auth_status = get_auth_status()
        return {
            "service": "XHS Downloader API",
            "version": "1.0.0",
            "environment": auth_status["environment"],
            "python_version": sys.version,
            "platform": sys.platform,
            "auth_enabled": auth_status["auth_enabled"],
            "rate_limit_enabled": auth_status["rate_limit_enabled"],
            "port": auth_status["port"],
            "debug": auth_status["debug"]
        }
    except Exception as e:
        logger.error(f"获取服务信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"无法获取服务信息: {str(e)}")

@app.get("/status")
async def get_status():
    """获取当前服务运行状态"""
    try:
        return {
            "status": "running",
            "environment": env_config["environment"],
            "auth_enabled": env_config["api_enabled"],
            "rate_limit": {
                "enabled": api_config.rate_limit_enabled,
                "max_requests": api_config.rate_limit_requests,
                "window_seconds": api_config.rate_limit_window
            },
            "downloads": [],  # 当前下载队列
            "service": "initialized"
        }
    except Exception as e:
        logger.error(f"获取服务状态失败: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "message": f"服务异常: {str(e)}",
                "error_code": "SERVICE_ERROR",
                "timestamp": asyncio.get_event_loop().time()
            }
        )

@app.get("/auth/status")
async def get_auth_status_endpoint():
    """获取认证状态信息"""
    try:
        return get_auth_status()
    except Exception as e:
        logger.error(f"获取认证状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"无法获取认证状态: {str(e)}")

@app.post("/download", response_model=DownloadResponse)
async def download_content(request: DownloadRequest, client_info: Dict = Depends(get_client_info)):
    """下载小红书内容"""
    try:
        # 记录下载请求
        logger.info(f"下载请求: {request.url} - 客户端: {client_info['client_id']}")
        
        # 导入XHS类
        try:
            from source.application import XHS
        except ImportError as e:
            logger.error(f"无法导入XHS类: {e}")
            return DownloadResponse(
                success=False,
                message="系统错误：无法加载下载模块",
                data=None
            )
        
        # 创建XHS实例
        project_root = Path(__file__).parent
        xhs = XHS(
            work_path=str(project_root / "downloads"),
            folder_name="APIDownload",
            name_format="API_作品标题",
            user_agent=None,
            cookie=request.cookie if request.cookie else None,
            proxy=request.proxy if request.proxy else None,
            timeout=30,
            max_retry=3,
            record_data=True,
            image_format="PNG",
            image_download=request.image_download,  # 使用请求参数，默认false
            video_download=request.video_download,  # 使用请求参数，默认true
            live_download=request.live_download,    # 使用请求参数，默认false
            folder_mode=True,
            download_record=True,
            author_archive=False,
            write_mtime=False,
            language="zh_CN"
        )
        
        # 执行下载
        async with xhs:
            result = await xhs.extract(
                request.url,
                download=True,
                index=None
            )
        
        # 处理结果
        if result:
            download_info = {
                "url": request.url,
                "status": "completed",
                "message": "下载完成",
                "result_count": len(result),
                "results": result,
                "timestamp": datetime.now().isoformat()
            }
            
            return DownloadResponse(
                success=True,
                message="下载成功完成",
                data=download_info
            )
        else:
            return DownloadResponse(
                success=False,
                message="下载失败：未获取到内容",
                data=None
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"下载请求处理失败: {e}")
        logger.error(f"错误堆栈: {traceback.format_exc()}")
        return DownloadResponse(
            success=False,
            message=f"下载失败: {str(e)}",
            data=None
        )

@app.get("/client/info")
async def get_client_info_endpoint(client_info: Dict = Depends(get_client_info)):
    """获取当前客户端信息"""
    return client_info

if __name__ == "__main__":
    print(f"🚀 启动XHS-Downloader API服务器...")
    print(f"🌍 环境: {env_config['environment']}")
    print(f"🔐 认证: {'启用' if env_config['api_enabled'] else '禁用'}")
    print(f"🚀 端口: {env_config['port']}")
    print(f"📚 API文档: http://{env_config.get('host', '127.0.0.1')}:{env_config['port']}/docs")
    print(f"🔧 按 Ctrl+C 停止服务器")
    
    try:
        uvicorn.run(
            app,
            host=env_config.get("host", "0.0.0.0"),
            port=env_config["port"],
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n👋 服务器已停止")
    except Exception as e:
        print(f"❌ 服务器启动失败: {e}")
        sys.exit(1)
